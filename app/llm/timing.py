"""Per-thread tally of time spent *waiting* (rate limiter, retry backoff) rather than in the model.

Latency numbers that include our own throttling would mostly measure the limiter, so the agent
reports this separately from model time.
"""
import threading

_local = threading.local()


def record_wait(seconds: float) -> None:
    _local.waited = getattr(_local, "waited", 0.0) + seconds


def pop_wait_ms() -> int:
    """Return and reset the wait accumulated on this thread."""
    waited, _local.waited = getattr(_local, "waited", 0.0), 0.0
    return round(waited * 1000)
