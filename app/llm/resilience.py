"""Wrappers around any LLMClient: rate limiting, retry with backoff, optional disk cache.

Compose as cache -> retry -> rate limit -> client, so every real attempt (including
retries) consumes a rate-limit slot and cache hits cost nothing.
"""
import hashlib
import json
import logging
import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import httpx

from app.config import Settings
from app.llm.base import LLMClient, LLMResponse, Message, ToolSpec
from app.llm.timing import record_wait

log = logging.getLogger("agent_ops.llm")


def is_daily_quota(exc: BaseException) -> bool:
    """True for a per-day quota 429: retrying within this process cannot help (reset is hours away)."""
    body = getattr(exc, "details", None)
    details = body.get("error", {}).get("details", []) if isinstance(body, dict) else []
    return any("PerDay" in str(v.get("quotaId", "")) for d in details if isinstance(d, dict)
               for v in d.get("violations", []))


def is_retryable(exc: BaseException) -> bool:
    """429, 5xx and network timeouts/connection errors. Works with google-genai errors (`.code`)
    and httpx-style errors (`.status_code`)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if is_daily_quota(exc):
        return False
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return isinstance(code, int) and (code == 429 or 500 <= code <= 599)


def retry_after_s(exc: BaseException) -> float | None:
    """Server-suggested wait from a Google RetryInfo detail (e.g. '28s'), if present."""
    body = getattr(exc, "details", None)
    details = body.get("error", {}).get("details", []) if isinstance(body, dict) else []
    for d in details:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                pass
    return None


class RateLimitedLLM:
    """Sliding-window limiter: at most `rpm` calls in any 60 s."""

    def __init__(self, inner: LLMClient, rpm: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if rpm < 1:
            raise ValueError("rpm must be >= 1")
        self.inner, self.rpm, self._clock, self._sleep = inner, rpm, clock, sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _reserve(self) -> float:
        """Returns seconds to wait; reserves the slot if none is needed."""
        with self._lock:
            now = self._clock()
            while self._calls and now - self._calls[0] >= 60:
                self._calls.popleft()
            if len(self._calls) < self.rpm:
                self._calls.append(now)
                return 0.0
            return 60 - (now - self._calls[0])

    def generate(self, system, messages, tools):
        while (wait := self._reserve()) > 0:
            log.info("rate limit reached, sleeping %.1fs", wait)
            record_wait(wait)
            self._sleep(wait)
        return self.inner.generate(system, messages, tools)


class RetryingLLM:
    """Retries 429/5xx with exponential backoff and jitter; other errors propagate at once."""

    def __init__(self, inner: LLMClient, max_retries: int = 4, base_delay: float = 1.0,
                 max_delay: float = 30.0, max_server_delay: float = 120.0, sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None):
        self.inner, self.max_retries = inner, max_retries
        self.base_delay, self.max_delay = base_delay, max_delay
        self.max_server_delay = max_server_delay  # a longer server-requested wait is not worth blocking a request for
        self._sleep, self._rng = sleep, rng or random.Random()

    def generate(self, system, messages, tools):
        for attempt in range(self.max_retries + 1):
            try:
                return self.inner.generate(system, messages, tools)
            except Exception as e:
                if attempt == self.max_retries or not is_retryable(e):
                    raise
                server_delay = retry_after_s(e) or 0.0
                if server_delay > self.max_server_delay:
                    log.error("server asked for a %.0fs wait; giving up instead of blocking", server_delay)
                    raise
                delay = min(self.max_delay, self.base_delay * 2**attempt) * self._rng.uniform(0.5, 1.0)
                delay = max(delay, server_delay)  # never retry sooner than the server asked
                log.warning("LLM call failed (%s), retry %d/%d in %.1fs", e, attempt + 1, self.max_retries, delay)
                record_wait(delay)
                self._sleep(delay)
        raise AssertionError("unreachable")


class CachingLLM:
    """On-disk response cache keyed by (namespace, system, messages, tools).

    Provider-native `raw` content is not cached; a replayed turn is rebuilt from text/tool calls.
    """

    def __init__(self, inner: LLMClient, cache_dir: str | Path, namespace: str):
        self.inner, self.dir, self.namespace = inner, Path(cache_dir), namespace
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = self.misses = 0

    def _key(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> str:
        payload = {
            "ns": self.namespace,
            "system": system,
            "messages": [m.model_dump(exclude={"raw"}) for m in messages],
            "tools": [t.model_dump() for t in tools],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def generate(self, system, messages, tools):
        path = self.dir / f"{self._key(system, messages, tools)}.json"
        if path.exists():
            try:
                resp = LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
                self.hits += 1
                return resp
            except ValueError:
                log.warning("corrupt cache entry %s, ignoring", path.name)
        self.misses += 1
        resp = self.inner.generate(system, messages, tools)
        path.write_text(resp.model_dump_json(exclude={"raw"}), encoding="utf-8")
        return resp


def build_llm(s: Settings, inner: LLMClient) -> LLMClient:
    llm: LLMClient = RateLimitedLLM(inner, s.effective_rpm)
    llm = RetryingLLM(llm, s.llm_max_retries, s.llm_retry_base_delay)
    if s.llm_cache_enabled:
        llm = CachingLLM(llm, s.llm_cache_dir, namespace=s.gemini_model)
    return llm
