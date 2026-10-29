import random

import httpx
import pytest

from app.config import Settings
from app.llm.base import LLMResponse, Message
from app.llm.resilience import (CachingLLM, RateLimitedLLM, RetryingLLM, build_llm, is_retryable,
                                retry_after_s)

MSGS = [Message(role="user", content="hi")]


class APIError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class Flaky:
    """Raises the given errors in order, then returns a response."""

    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def generate(self, system, messages, tools):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return LLMResponse(text="ok", input_tokens=1, output_tokens=1)


@pytest.mark.parametrize("code,expected", [(429, True), (500, True), (503, True), (599, True),
                                           (400, False), (401, False), (404, False), (None, False)])
def test_is_retryable(code, expected):
    exc = APIError(code) if code else ValueError("x")
    assert is_retryable(exc) is expected


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectTimeout("t"), httpx.ConnectError("c")])
def test_network_timeouts_are_retryable(exc):
    assert is_retryable(exc)
    inner = Flaky([exc])
    assert RetryingLLM(inner, sleep=lambda s: None).generate("s", MSGS, []).text == "ok"


def test_retry_succeeds_after_transient_errors():
    inner, sleeps = Flaky([APIError(429), APIError(503)]), []
    llm = RetryingLLM(inner, max_retries=4, base_delay=1.0, sleep=sleeps.append, rng=random.Random(0))
    assert llm.generate("s", MSGS, []).text == "ok"
    assert inner.calls == 3
    assert len(sleeps) == 2


def test_backoff_grows_exponentially_and_is_capped():
    sleeps = []
    inner = Flaky([APIError(500)] * 5)
    llm = RetryingLLM(inner, max_retries=5, base_delay=1.0, max_delay=6.0, sleep=sleeps.append, rng=random.Random(1))
    llm.generate("s", MSGS, [])
    assert len(sleeps) == 5
    for attempt, d in enumerate(sleeps):
        ceiling = min(6.0, 2**attempt)
        assert ceiling * 0.5 <= d <= ceiling


def test_retry_gives_up_after_max_retries():
    inner = Flaky([APIError(429)] * 10)
    llm = RetryingLLM(inner, max_retries=2, sleep=lambda s: None)
    with pytest.raises(APIError):
        llm.generate("s", MSGS, [])
    assert inner.calls == 3  # first try + 2 retries


def test_non_retryable_error_is_not_retried():
    inner = Flaky([APIError(400)])
    with pytest.raises(APIError):
        RetryingLLM(inner, sleep=lambda s: None).generate("s", MSGS, [])
    assert inner.calls == 1


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_rate_limiter_blocks_when_window_is_full():
    clock, inner = FakeClock(), Flaky([])
    llm = RateLimitedLLM(inner, rpm=2, clock=clock.now, sleep=clock.sleep)
    for _ in range(3):
        llm.generate("s", MSGS, [])
    assert inner.calls == 3
    assert clock.slept == [60.0]  # third call waited for the first slot to expire


def test_rate_limiter_does_not_block_under_limit():
    clock = FakeClock()
    llm = RateLimitedLLM(Flaky([]), rpm=5, clock=clock.now, sleep=clock.sleep)
    for _ in range(5):
        llm.generate("s", MSGS, [])
    assert clock.slept == []


def test_rate_limiter_slot_frees_after_window():
    clock = FakeClock()
    llm = RateLimitedLLM(Flaky([]), rpm=1, clock=clock.now, sleep=clock.sleep)
    llm.generate("s", MSGS, [])
    clock.t += 61
    llm.generate("s", MSGS, [])
    assert clock.slept == []


def test_rate_limiter_rejects_bad_rpm():
    with pytest.raises(ValueError):
        RateLimitedLLM(Flaky([]), rpm=0)


def test_cache_hit_skips_inner(tmp_path):
    inner = Flaky([])
    llm = CachingLLM(inner, tmp_path, namespace="m")
    a = llm.generate("s", MSGS, [])
    b = llm.generate("s", MSGS, [])
    assert inner.calls == 1 and (llm.hits, llm.misses) == (1, 1)
    assert a == b


def test_cache_key_depends_on_input_and_namespace(tmp_path):
    inner = Flaky([])
    llm = CachingLLM(inner, tmp_path, namespace="m1")
    llm.generate("s", MSGS, [])
    llm.generate("other system", MSGS, [])
    llm.generate("s", [Message(role="user", content="different")], [])
    CachingLLM(inner, tmp_path, namespace="m2").generate("s", MSGS, [])
    assert inner.calls == 4


def test_cache_persists_across_instances(tmp_path):
    CachingLLM(Flaky([]), tmp_path, "m").generate("s", MSGS, [])
    inner = Flaky([APIError(500)])  # would fail if called
    assert CachingLLM(inner, tmp_path, "m").generate("s", MSGS, []).text == "ok"
    assert inner.calls == 0


def test_corrupt_cache_entry_is_ignored(tmp_path):
    llm = CachingLLM(Flaky([]), tmp_path, "m")
    llm.generate("s", MSGS, [])
    for f in tmp_path.glob("*.json"):
        f.write_text("{not json")
    assert llm.generate("s", MSGS, []).text == "ok"


def test_errors_are_not_cached(tmp_path):
    inner = Flaky([APIError(500)])
    llm = CachingLLM(inner, tmp_path, "m")
    with pytest.raises(APIError):
        llm.generate("s", MSGS, [])
    assert llm.generate("s", MSGS, []).text == "ok"


def test_build_llm_cache_is_off_by_default(tmp_path):
    s = Settings(_env_file=None, llm_cache_dir=str(tmp_path / "c"))
    assert not s.llm_cache_enabled
    assert not isinstance(build_llm(s, Flaky([])), CachingLLM)
    assert not (tmp_path / "c").exists()


def test_build_llm_cache_enabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_ENABLED", "true")
    s = Settings(_env_file=None, llm_cache_dir=str(tmp_path / "c"))
    assert isinstance(build_llm(s, Flaky([])), CachingLLM)


class QuotaError(APIError):
    def __init__(self, delay):
        super().__init__(429)
        self.details = {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}}


def test_retry_after_parsing():
    assert retry_after_s(QuotaError("28s")) == 28.0
    assert retry_after_s(QuotaError("bogus")) is None
    assert retry_after_s(APIError(429)) is None


def test_retry_honours_server_retry_delay():
    sleeps = []
    llm = RetryingLLM(Flaky([QuotaError("28s")]), base_delay=1.0, sleep=sleeps.append, rng=random.Random(0))
    llm.generate("s", MSGS, [])
    assert sleeps == [28.0]  # backoff would have been <= 1s
