"""Slow down repeated login failures, per client address and per user name."""

import time
from collections import OrderedDict

FREE_FAILURES = 3  # failures allowed before any delay
MAX_DELAY = 300  # seconds
FORGET_AFTER = 3600  # failures older than this no longer count
MAX_KEYS = 10000


class LoginThrottle:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        # key -> (failure count, time of last failure)
        self._failures: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def _delay(self, key: str) -> float:
        count, last = self._failures.get(key, (0, 0.0))
        if count < FREE_FAILURES:
            return 0.0
        wait = min(2 ** (count - FREE_FAILURES), MAX_DELAY)
        return max(0.0, last + wait - self._clock())

    def retry_after(self, ip: str, user: str) -> float:
        """Seconds until another attempt is allowed (0 if allowed now)."""
        self._expire()
        return max(self._delay(f"ip:{ip}"), self._delay(f"user:{user}"))

    def failed(self, ip: str, user: str) -> None:
        now = self._clock()
        for key in (f"ip:{ip}", f"user:{user}"):
            count, _ = self._failures.pop(key, (0, 0.0))
            self._failures[key] = (count + 1, now)
        while len(self._failures) > MAX_KEYS:
            self._failures.popitem(last=False)

    def succeeded(self, ip: str, user: str) -> None:
        self._failures.pop(f"ip:{ip}", None)
        self._failures.pop(f"user:{user}", None)

    def _expire(self) -> None:
        cutoff = self._clock() - FORGET_AFTER
        for key in [k for k, (_, last) in self._failures.items() if last < cutoff]:
            del self._failures[key]
