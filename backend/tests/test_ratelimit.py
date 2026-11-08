import asyncio

from core.ratelimit import (
    MemoryRateLimiter,
    RedisRateLimiter,
    create_rate_limiter,
    hash_ip,
    seconds_until_utc_midnight,
)

T0 = 1_800_000_000.0  # fixed timestamp


def check(rl, ip, now):
    return asyncio.run(rl.check(ip, now))


# ------------------------------- in-memory -------------------------------


def test_burst_limit():
    rl = MemoryRateLimiter(per_ip_daily=100, per_ip_burst=2, global_daily=100)
    assert check(rl, "a", T0).ok
    assert check(rl, "a", T0 + 1).ok
    third = check(rl, "a", T0 + 2)
    assert not third.ok and third.scope == "burst"
    assert check(rl, "a", T0 + 120).ok  # window passed


def test_daily_limit_per_ip_and_remaining():
    rl = MemoryRateLimiter(per_ip_daily=2, per_ip_burst=100, global_daily=100)
    assert check(rl, "a", T0).remaining == 1
    assert check(rl, "a", T0 + 1).remaining == 0
    denied = check(rl, "a", T0 + 2)
    assert not denied.ok and denied.scope == "ip-daily"
    assert check(rl, "b", T0 + 3).ok  # other IP unaffected


def test_global_limit():
    rl = MemoryRateLimiter(per_ip_daily=100, per_ip_burst=100, global_daily=2)
    check(rl, "a", T0)
    check(rl, "b", T0)
    assert check(rl, "c", T0).scope == "global-daily"


# --------------------------------- Redis ---------------------------------


class FakePipeline:
    def __init__(self, store, fail=False):
        self.store, self.fail, self.ops = store, fail, []

    def incr(self, key):
        self.ops.append(("incr", key))

    def expire(self, key, seconds, nx=False):
        self.ops.append(("expire", key))

    async def execute(self):
        if self.fail:
            raise ConnectionError("redis down")
        out = []
        for op, key in self.ops:
            if op == "incr":
                self.store[key] = self.store.get(key, 0) + 1
                out.append(self.store[key])
            else:
                out.append(True)
        return out


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def pipeline(self, transaction=True):
        return FakePipeline(self.store, self.fail)


def test_redis_counts_and_limits():
    rl = RedisRateLimiter(FakeRedis(), per_ip_daily=2, per_ip_burst=100, global_daily=100)
    assert check(rl, "a", T0).remaining == 1
    assert check(rl, "a", T0).ok
    assert check(rl, "a", T0).scope == "ip-daily"


def test_redis_failure_fails_open():
    rl = RedisRateLimiter(FakeRedis(fail=True), per_ip_daily=1, per_ip_burst=1, global_daily=1)
    result = check(rl, "a", T0)
    assert result.ok and result.remaining == -1


def test_factory_picks_backend():
    assert isinstance(create_rate_limiter("", 1, 1, 1), MemoryRateLimiter)
    assert isinstance(create_rate_limiter("redis://localhost:6379/0", 1, 1, 1), RedisRateLimiter)


# -------------------------------- helpers --------------------------------


def test_ip_is_hashed():
    assert hash_ip("1.2.3.4") != "1.2.3.4"
    assert len(hash_ip("1.2.3.4")) == 16


def test_seconds_until_midnight_is_positive():
    assert 0 < seconds_until_utc_midnight(T0) <= 86400
