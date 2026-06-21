"""Polite HTTP client: robots.txt, rate limiting, disk cache, retries, request cap.

Designed for personal/research-scale collection consistent with HKJC's ToS posture
(see research_report.md §4): identify ourselves, throttle, cache aggressively so we
never re-hit the server for immutable historical pages, and refuse to exceed a hard
per-run request budget.
"""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from ..logging_setup import get_logger

log = get_logger("http")


class RequestBudgetExceeded(RuntimeError):
    pass


class RobotsDisallowed(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    content: bytes
    from_cache: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class PoliteClient:
    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: str | Path,
        base_delay_seconds: float = 4.0,
        jitter_seconds: float = 2.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        respect_robots: bool = True,
        cache_ttl_hours: float = 336.0,
        max_requests_per_run: int = 600,
    ):
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_delay = base_delay_seconds
        self.jitter = jitter_seconds
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.backoff = backoff_factor
        self.respect_robots = respect_robots
        self.cache_ttl_s = cache_ttl_hours * 3600.0
        self.max_requests = max_requests_per_run

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent,
                                     "Accept-Language": "en-US,en;q=0.9"})
        self._last_request_at: dict[str, float] = {}     # host -> monotonic ts
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self.requests_made = 0                            # network requests this run (excl. cache)

    # -- robots ------------------------------------------------------------------------
    def _robots_for(self, url: str) -> Optional[RobotFileParser]:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host in self._robots:
            return self._robots[host]
        rp = RobotFileParser()
        robots_url = host + "/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None  # no robots (e.g. 404) => not an affirmative grant, but no disallow
        except requests.RequestException:
            rp = None
        self._robots[host] = rp
        return rp

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        if rp is None:
            return True  # absence of robots.txt is not a disallow
        return rp.can_fetch(self.user_agent, url)

    # -- rate limiting -----------------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            wait = self.base_delay + random.uniform(0, self.jitter) - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    # -- caching -----------------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.bin"

    def _cache_get(self, key: str, ttl_s: float) -> Optional[bytes]:
        p = self._cache_path(key)
        if not p.exists():
            return None
        if ttl_s >= 0 and (time.time() - p.stat().st_mtime) > ttl_s:
            return None
        return p.read_bytes()

    def _cache_put(self, key: str, content: bytes) -> None:
        self._cache_path(key).write_bytes(content)

    # -- core fetch --------------------------------------------------------------------
    def get(self, url: str, *, params: dict | None = None,
            ttl_hours: float | None = None, use_cache: bool = True) -> FetchResult:
        """GET with caching, throttling, robots, retries. Raises on disallow/budget."""
        full = requests.Request("GET", url, params=params).prepare().url or url
        ttl_s = self.cache_ttl_s if ttl_hours is None else ttl_hours * 3600.0
        key = "GET " + full

        if use_cache:
            cached = self._cache_get(key, ttl_s)
            if cached is not None:
                log.debug("cache hit %s", full)
                return FetchResult(full, 200, cached, from_cache=True)

        if not self._allowed(full):
            raise RobotsDisallowed(f"robots.txt disallows fetching {full}")
        if self.requests_made >= self.max_requests:
            raise RequestBudgetExceeded(
                f"hit max_requests_per_run={self.max_requests}; refusing to fetch more")

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(full)
            try:
                self.requests_made += 1
                resp = self.session.get(full, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"retryable status {resp.status_code}")
                content = resp.content
                if use_cache and resp.status_code == 200:
                    self._cache_put(key, content)
                log.info("GET %s -> %s (%d bytes)", full, resp.status_code, len(content))
                return FetchResult(full, resp.status_code, content, from_cache=False)
            except requests.RequestException as e:
                last_exc = e
                sleep_for = self.backoff ** attempt
                log.warning("fetch error (attempt %d/%d): %s; backoff %.1fs",
                            attempt, self.max_retries, e, sleep_for)
                time.sleep(sleep_for)
        raise RuntimeError(f"GET failed after {self.max_retries} retries: {full}") from last_exc

    def post_json(self, url: str, payload: dict, *, headers: dict | None = None) -> FetchResult:
        """POST JSON (for GraphQL). Not cached (used for live odds). Honours robots+budget."""
        if not self._allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        if self.requests_made >= self.max_requests:
            raise RequestBudgetExceeded("hit max_requests_per_run")
        self._throttle(url)
        self.requests_made += 1
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        resp = self.session.post(url, json=payload, headers=h, timeout=self.timeout)
        return FetchResult(url, resp.status_code, resp.content, from_cache=False)
