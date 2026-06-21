"""HTTP client behaviour without network: cache hit, request-budget cap, robots parse."""
import pytest

from hkjc_edge.sources.http_client import (
    FetchResult, PoliteClient, RequestBudgetExceeded, RobotsDisallowed,
)


def _client(tmp_path, **kw):
    return PoliteClient(user_agent="hkjc-test/0.1", cache_dir=tmp_path / "cache",
                        base_delay_seconds=0, jitter_seconds=0, **kw)


def test_cache_hit_avoids_network(tmp_path):
    c = _client(tmp_path)
    url = "https://example.com/page"
    # Prime the cache directly (no network).
    c._cache_put("GET " + url, b"<html>cached</html>")
    res = c.get(url)
    assert res.from_cache is True
    assert res.content == b"<html>cached</html>"
    assert c.requests_made == 0  # never hit the network


def test_request_budget_enforced(tmp_path):
    c = _client(tmp_path, respect_robots=False, max_requests_per_run=0)
    with pytest.raises(RequestBudgetExceeded):
        c.get("https://example.com/never", use_cache=False)
    assert c.requests_made == 0


def test_robots_disallow(tmp_path, monkeypatch):
    c = _client(tmp_path, respect_robots=True)
    # Inject a robots parser that disallows everything for our host.
    from urllib.robotparser import RobotFileParser
    rp = RobotFileParser()
    rp.parse(["User-agent: *", "Disallow: /"])
    c._robots["https://example.com"] = rp
    with pytest.raises(RobotsDisallowed):
        c.get("https://example.com/blocked", use_cache=False)


def test_fetchresult_helpers():
    r = FetchResult("u", 200, b"hello", from_cache=False)
    assert r.ok and r.text == "hello"
    assert FetchResult("u", 404, b"", from_cache=False).ok is False
