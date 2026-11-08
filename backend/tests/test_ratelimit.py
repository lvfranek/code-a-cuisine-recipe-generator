from core.ratelimit import RateLimiter, hash_ip, seconds_until_utc_midnight

T0 = 1_800_000_000.0  # fixed timestamp


def test_burst_limit():
    rl = RateLimiter(per_ip_daily=100, per_ip_burst=2, global_daily=100)
    assert rl.check("a", T0).ok
    assert rl.check("a", T0 + 1).ok
    third = rl.check("a", T0 + 2)
    assert not third.ok and third.scope == "burst"
    assert rl.check("a", T0 + 120).ok  # window passed


def test_daily_limit_per_ip_and_remaining():
    rl = RateLimiter(per_ip_daily=2, per_ip_burst=100, global_daily=100)
    assert rl.check("a", T0).remaining == 1
    assert rl.check("a", T0 + 1).remaining == 0
    denied = rl.check("a", T0 + 2)
    assert not denied.ok and denied.scope == "ip-daily"
    assert rl.check("b", T0 + 3).ok  # other IP unaffected


def test_global_limit():
    rl = RateLimiter(per_ip_daily=100, per_ip_burst=100, global_daily=2)
    rl.check("a", T0)
    rl.check("b", T0)
    assert rl.check("c", T0).scope == "global-daily"


def test_ip_is_hashed():
    assert hash_ip("1.2.3.4") != "1.2.3.4"
    assert len(hash_ip("1.2.3.4")) == 16


def test_seconds_until_midnight_is_positive():
    assert 0 < seconds_until_utc_midnight(T0) <= 86400
