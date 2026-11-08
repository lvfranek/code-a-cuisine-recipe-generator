"""Rate limiting for /generate (per-IP daily, per-IP burst, global daily).

In-memory for now (one server process). Step 0.3 moves the counters to Redis.
IPs are stored only as a short hash, never in plain text.
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

BURST_WINDOW_S = 60
DAY_S = 24 * 60 * 60
MAX_TRACKED_IPS = 5000


@dataclass
class RateLimitResult:
    ok: bool
    remaining: int = 0
    scope: str = ""
    retry_after: int = 0
    error: str = ""


def hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def seconds_until_utc_midnight(now: float) -> int:
    current = datetime.fromtimestamp(now, UTC)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - current).total_seconds() + 0.999))


def _utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")


class RateLimiter:
    def __init__(self, per_ip_daily: int, per_ip_burst: int, global_daily: int):
        self.per_ip_daily = per_ip_daily
        self.per_ip_burst = per_ip_burst
        self.global_daily = global_daily
        self._hits: dict[str, list[float]] = {}
        self._global_day = ""
        self._global_count = 0

    def check(self, ip_hash: str, now: float | None = None) -> RateLimitResult:
        now = time.time() if now is None else now

        if self._global_day != _utc_day(now):
            self._global_day, self._global_count = _utc_day(now), 0
        self._global_count += 1
        if self._global_count > self.global_daily:
            return self._deny("global-daily", seconds_until_utc_midnight(now),
                              "This demo has hit its shared daily limit. Please check back tomorrow.")

        if len(self._hits) > MAX_TRACKED_IPS:
            self._hits.clear()
        hits = [t for t in self._hits.get(ip_hash, []) if now - t < DAY_S]
        hits.append(now)
        self._hits[ip_hash] = hits

        burst = sum(1 for t in hits if now - t < BURST_WINDOW_S)
        if burst > self.per_ip_burst:
            return self._deny("burst", BURST_WINDOW_S, "Slow down a moment, then try again.")
        if len(hits) > self.per_ip_daily:
            return self._deny("ip-daily", seconds_until_utc_midnight(now),
                              f"Daily limit reached ({self.per_ip_daily} recipes per day). Try again tomorrow.")
        return RateLimitResult(ok=True, remaining=max(0, self.per_ip_daily - len(hits)))

    @staticmethod
    def _deny(scope: str, retry_after: int, error: str) -> RateLimitResult:
        return RateLimitResult(ok=False, scope=scope, retry_after=retry_after, error=error)
