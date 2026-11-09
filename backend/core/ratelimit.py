"""Rate limiting for /generate (per-IP daily, per-IP burst, global daily).

Two interchangeable backends with the same async `check()`:
- `RedisRateLimiter`: counters in Redis, survive restarts (used in Docker).
- `MemoryRateLimiter`: fallback for local dev without Redis.
IPs are stored only as a short hash, never in plain text.
"""

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)

BURST_WINDOW_S = 60
DAY_S = 24 * 60 * 60
MAX_TRACKED_IPS = 5000

MSG_GLOBAL = "This demo has hit its shared daily limit. Please check back tomorrow."
MSG_BURST = "Slow down a moment, then try again."


@dataclass
class RateLimitResult:
    ok: bool
    remaining: int = 0
    scope: str = ""
    retry_after: int = 0
    error: str = ""


# Random key that only lives in memory. A plain hash of an IPv4 address could be
# reversed by trying all ~4 billion addresses; with this secret it cannot.
# A restart creates a new key (counters start fresh), which is fine for a demo.
_IP_HASH_KEY = secrets.token_bytes(32)


def hash_ip(ip: str) -> str:
    """Short keyed one-way hash of an IP address. The plain IP is never stored."""
    return hmac.new(_IP_HASH_KEY, ip.encode(), hashlib.sha256).hexdigest()[:16]


def seconds_until_utc_midnight(now: float) -> int:
    current = datetime.fromtimestamp(now, UTC)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - current).total_seconds() + 0.999))


def utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")


class _Limits:
    """Shared limit values and the decision logic for both backends."""

    def __init__(self, per_ip_daily: int, per_ip_burst: int, global_daily: int):
        self.per_ip_daily = per_ip_daily
        self.per_ip_burst = per_ip_burst
        self.global_daily = global_daily

    def decide(self, ip_day: int, ip_burst: int, global_count: int, now: float) -> RateLimitResult:
        if ip_burst > self.per_ip_burst:
            return deny("burst", BURST_WINDOW_S, MSG_BURST)
        if ip_day > self.per_ip_daily:
            return deny("ip-daily", seconds_until_utc_midnight(now),
                        f"Daily limit reached ({self.per_ip_daily} per day). Try again tomorrow.")
        if global_count > self.global_daily:
            return deny("global-daily", seconds_until_utc_midnight(now), MSG_GLOBAL)
        return RateLimitResult(ok=True, remaining=max(0, self.per_ip_daily - ip_day))


def deny(scope: str, retry_after: int, error: str) -> RateLimitResult:
    return RateLimitResult(ok=False, scope=scope, retry_after=retry_after, error=error)


class MemoryRateLimiter(_Limits):
    def __init__(self, per_ip_daily: int, per_ip_burst: int, global_daily: int):
        super().__init__(per_ip_daily, per_ip_burst, global_daily)
        self._hits: dict[str, list[float]] = {}
        self._global_day = ""
        self._global_count = 0

    async def check(self, ip_hash: str, now: float | None = None) -> RateLimitResult:
        now = time.time() if now is None else now

        if self._global_day != utc_day(now):
            self._global_day, self._global_count = utc_day(now), 0
        self._global_count += 1

        if len(self._hits) > MAX_TRACKED_IPS:
            self._hits.clear()
        hits = [t for t in self._hits.get(ip_hash, []) if now - t < DAY_S]
        hits.append(now)
        self._hits[ip_hash] = hits

        burst = sum(1 for t in hits if now - t < BURST_WINDOW_S)
        return self.decide(len(hits), burst, self._global_count, now)


class RedisRateLimiter(_Limits):
    """Fixed-window counters via INCR/EXPIRE."""

    def __init__(self, redis, per_ip_daily: int, per_ip_burst: int, global_daily: int, prefix: str = "gen"):
        super().__init__(per_ip_daily, per_ip_burst, global_daily)
        self.redis = redis
        self.prefix = prefix  # separate counters per endpoint type ("gen", "photo")

    async def check(self, ip_hash: str, now: float | None = None) -> RateLimitResult:
        now = time.time() if now is None else now
        day = utc_day(now)
        ip_day_key = f"cac:{self.prefix}:ip:{ip_hash}:{day}"
        burst_key = f"cac:{self.prefix}:burst:{ip_hash}"
        global_key = f"cac:{self.prefix}:global:{day}"
        try:
            pipe = self.redis.pipeline(transaction=True)
            pipe.incr(ip_day_key)
            pipe.expire(ip_day_key, DAY_S + 60)
            pipe.incr(burst_key)
            pipe.expire(burst_key, BURST_WINDOW_S, nx=True)
            pipe.incr(global_key)
            pipe.expire(global_key, DAY_S + 60)
            ip_day, _, burst, _, global_count, _ = await pipe.execute()
        except Exception:
            # Redis hiccup: fail open so the demo keeps working.
            log.exception("Rate limit check failed, allowing request")
            return RateLimitResult(ok=True, remaining=-1)
        return self.decide(int(ip_day), int(burst), int(global_count), now)


def create_rate_limiter(redis_url: str, per_ip_daily: int, per_ip_burst: int, global_daily: int, prefix: str = "gen"):
    """Redis if REDIS_URL is set, otherwise in-memory."""
    if redis_url:
        from redis.asyncio import Redis

        log.info("Rate limiting: Redis")
        return RedisRateLimiter(Redis.from_url(redis_url), per_ip_daily, per_ip_burst, global_daily, prefix)
    log.info("Rate limiting: in-memory (set REDIS_URL to use Redis)")
    return MemoryRateLimiter(per_ip_daily, per_ip_burst, global_daily)
