"""Reliability patterns: circuit breaker, timeout budgets, backpressure.

Kiro audit recommendation, 2026-11-21:
  Without bounded timeouts and admission control, slow dependencies accumulate requests
  until the application exhausts connections, memory, or worker capacity. This module
  provides:

  CircuitBreaker — tracks consecutive failures per dependency and opens (stops sending
      requests) after a threshold. After a cool-down period it allows one probe request
      through; on success it closes again. AI unavailability must never silently authorize
      a payment; the circuit breaker makes the failure explicit.

  with_timeout() — wraps a callable with an explicit wall-clock deadline, raising
      TimeoutError rather than hanging indefinitely.

  ConcurrencyLimiter — a simple semaphore-based admission gate. When the limit is reached
      new requests are rejected immediately (HTTP 429) rather than queued indefinitely.

Usage::

    from .reliability import circuit_breaker, ConcurrencyLimiter, with_timeout

    # Register circuits once at startup (or lazily on first use):
    paypal_circuit = circuit_breaker("paypal")
    llm_circuit    = circuit_breaker("llm")

    # Wrap a PayPal call:
    with paypal_circuit:
        result = client.capture_order(order_id, request_id=rid)

    # Wrap an LLM call with a strict timeout:
    response = with_timeout(lambda: llm.complete(system, user), seconds=10, name="llm.complete")

    # Admission control at the endpoint level:
    capture_limiter = ConcurrencyLimiter(max_concurrent=20)
    with capture_limiter:
        ...
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Circuit breaker

_CIRCUITS: dict[str, "CircuitBreaker"] = {}
_CIRCUIT_LOCK = threading.Lock()

# Defaults — can be overridden per circuit at registration time.
DEFAULT_FAILURE_THRESHOLD = 5     # consecutive failures before opening
DEFAULT_RECOVERY_TIMEOUT = 30.0   # seconds before trying a probe request
DEFAULT_HALF_OPEN_SUCCESSES = 2   # successes needed to close again


class CircuitOpen(RuntimeError):
    """Raised when a call is attempted while the circuit is open."""


class CircuitBreaker:
    """Thread-safe circuit breaker with closed → open → half-open → closed lifecycle."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
                 recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
                 half_open_successes: int = DEFAULT_HALF_OPEN_SUCCESSES):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_successes = half_open_successes
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at: float = 0.0
        self._half_open_ok = 0
        self._probe_active = False
        self._lock = threading.Lock()

    # Context-manager interface so callers can write ``with circuit: ...``
    def __enter__(self):
        with self._lock:
            if self._state == self.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    log.info("circuit %r: open → half-open (probe allowed)", self.name)
                    self._state = self.HALF_OPEN
                    self._half_open_ok = 0
                else:
                    raise CircuitOpen(
                        f"Circuit '{self.name}' is open. Dependency unavailable; try again shortly."
                    )
            if self._state == self.HALF_OPEN:
                if self._probe_active:
                    raise CircuitOpen("Recovery probe already running")
                self._probe_active = True
        return self

    def __exit__(self, exc_type, exc_val, _tb):
        with self._lock:
            self._probe_active = False
            if exc_type is None:
                self._on_success()
            else:
                self._on_failure(exc_val)
        return False  # never suppress exceptions

    def _on_success(self):
        if self._state == self.HALF_OPEN:
            self._half_open_ok += 1
            if self._half_open_ok >= self.half_open_successes:
                log.info("circuit %r: half-open → closed", self.name)
                self._state = self.CLOSED
                self._failures = 0
        elif self._state == self.CLOSED:
            self._failures = 0

    def _on_failure(self, exc):
        self._failures += 1
        if self._state == self.HALF_OPEN or self._failures >= self.failure_threshold:
            log.warning("circuit %r: → open after %d failure(s): %s",
                        self.name, self._failures, exc)
            self._state = self.OPEN
            self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        return self._state

    def status(self) -> dict:
        with self._lock:
            return {"name": self.name, "state": self._state,
                    "failures": self._failures,
                    "seconds_until_probe": max(0.0, self.recovery_timeout - (
                        time.monotonic() - self._opened_at)) if self._state == self.OPEN else 0.0}


def circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Return (or create) the named circuit breaker. Idempotent."""
    with _CIRCUIT_LOCK:
        if name not in _CIRCUITS:
            _CIRCUITS[name] = CircuitBreaker(name, **kwargs)
        return _CIRCUITS[name]


def all_circuit_status() -> list[dict]:
    """Snapshot of every registered circuit — useful for the health/metrics endpoint."""
    with _CIRCUIT_LOCK:
        return [cb.status() for cb in _CIRCUITS.values()]


# ---------------------------------------------------------------------------
# Timeout wrapper

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ciq-timeout")
_timeout_slots = threading.BoundedSemaphore(8)


def with_timeout(fn: Callable[[], T], *, seconds: float, name: str = "call") -> T:
    """Run *fn* in a thread and raise TimeoutError if it doesn't finish within *seconds*.

    Use this for optional work (LLM calls, non-critical enrichment) where you want a hard
    deadline without blocking the event loop. Do NOT use it for database writes where
    abandoning the thread mid-write could leave data inconsistent — use SQLAlchemy's own
    statement timeout for that.
    """
    if not _timeout_slots.acquire(blocking=False):
        raise CapacityExceeded("Optional dependency capacity reached")
    try:
        future = _executor.submit(fn)
    except Exception:
        _timeout_slots.release()
        raise
    future.add_done_callback(lambda _: _timeout_slots.release())
    try:
        return future.result(timeout=seconds)
    except FuturesTimeoutError:
        future.cancel()
        log.warning("with_timeout: %r exceeded %.1fs deadline", name, seconds)
        raise TimeoutError(f"{name} did not complete within {seconds:.0f}s")


# ---------------------------------------------------------------------------
# Concurrency limiter

class CapacityExceeded(RuntimeError):
    pass


class ConcurrencyLimiter:
    """Semaphore-based admission gate. Raises RuntimeError when at capacity."""

    def __init__(self, max_concurrent: int, name: str = ""):
        self.name = name
        self._sem = threading.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent

    def __enter__(self):
        acquired = self._sem.acquire(blocking=False)
        if not acquired:
            raise CapacityExceeded(
                f"Concurrency limit reached{f' for {self.name}' if self.name else ''}. "
                "Try again shortly."
            )
        return self

    def __exit__(self, *_):
        self._sem.release()
        return False


# Pre-registered circuits used by the PayPal adapter and LLM layer.
paypal_circuit = circuit_breaker("paypal", failure_threshold=5, recovery_timeout=30.0)
llm_circuit    = circuit_breaker("llm",    failure_threshold=3, recovery_timeout=20.0)
llm_limiter = ConcurrencyLimiter(max_concurrent=4, name="optional AI")

# Concurrency limits: capture and refund are financial operations; keep them tight.
capture_limiter = ConcurrencyLimiter(max_concurrent=25, name="capture")
refund_limiter  = ConcurrencyLimiter(max_concurrent=10, name="refund")
