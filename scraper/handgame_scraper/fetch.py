"""Polite HTTP layer.

Every network call in this project goes through here so that rate limiting,
caching, retries and robots.txt checks are applied uniformly. Scrapers that
hammer small tribal and community web servers get blocked, and deservedly so.
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.parse
import urllib.robotparser
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "handgame.info-event-collector/1.0 "
    "(+https://www.handgame.info; community event calendar; "
    "contact edesoto18@gmail.com)"
)

# Seconds to wait between requests to the same host.
DEFAULT_DELAY = 2.0

#: Consecutive 429s from one host before we stop asking it anything else
#: this run. Three is enough to tell a genuine rate limit from one busy
#: moment, and cheap enough that a false positive costs one run's worth of
#: that host rather than anything permanent.
RATE_LIMIT_GIVE_UP = 3


class Fetcher:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        delay: float = DEFAULT_DELAY,
        timeout: int = 25,
        respect_robots: bool = True,
        cache_ttl_hours: int = 12,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.delay = delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.cache_ttl = cache_ttl_hours * 3600
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        # Per-host rate-limit state. A scheduled run comes from a datacenter
        # address and gets treated very differently from a laptop: on
        # 2026-08-13 every single calendar.powwows.com request returned 429
        # from a GitHub runner while the same URLs returned 200 locally. The
        # run spent about four minutes backing off and collected 14 candidates
        # where a local run collected 54. Retrying each URL individually
        # cannot help when the host is refusing all of them.
        self._host_delay: dict[str, float] = {}
        self._host_429: dict[str, int] = {}
        self._rate_limited: set[str] = set()

    # -- politeness ----------------------------------------------------
    def _throttle(self, host: str) -> None:
        # A host that has answered 429 gets a longer gap for the rest of the
        # run. This only ever slows us down, never speeds us up.
        delay = max(self.delay, self._host_delay.get(host, 0.0))
        last = self._last_hit.get(host)
        if last is not None:
            wait = delay - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.time()

    def _note_rate_limit(self, host: str, retry_after: Optional[str]) -> float:
        """Record a 429 and return how long to wait before trying again."""
        seen = self._host_429.get(host, 0) + 1
        self._host_429[host] = seen
        # Each 429 doubles this host's floor delay for the rest of the run.
        self._host_delay[host] = min(30.0, max(self.delay, self._host_delay.get(host, self.delay)) * 2)

        wait = self._host_delay[host]
        # Retry-After is the host telling us plainly what it wants. Honour it,
        # but do not sit on a run for an hour because a header said 3600.
        if retry_after:
            try:
                wait = max(wait, min(60.0, float(retry_after)))
            except ValueError:
                pass

        if seen >= RATE_LIMIT_GIVE_UP and host not in self._rate_limited:
            self._rate_limited.add(host)
            log.warning(
                "%s has refused %d requests with 429; skipping it for the rest "
                "of this run. It is rate limiting us, and retrying each URL "
                "only burns time. Try again later, or from somewhere else.",
                host,
                seen,
            )
        return wait

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{host}/robots.txt")
            try:
                resp = self.session.get(
                    f"{host}/robots.txt", timeout=self.timeout
                )
                if resp.status_code >= 400:
                    self._robots[host] = None  # no robots.txt means allowed
                else:
                    rp.parse(resp.text.splitlines())
                    self._robots[host] = rp
            except requests.RequestException:
                self._robots[host] = None
        rp = self._robots[host]
        if rp is None:
            return True
        return rp.can_fetch(USER_AGENT, url)

    # -- cache ---------------------------------------------------------
    def _cache_path(self, url: str, suffix: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}{suffix}"

    def _cached(self, path: Optional[Path]) -> Optional[bytes]:
        if path and path.exists():
            if time.time() - path.stat().st_mtime < self.cache_ttl:
                return path.read_bytes()
        return None

    # -- public API ----------------------------------------------------
    def get(
        self,
        url: str,
        *,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        retries: int = 2,
        use_cache: bool = True,
    ) -> Optional[requests.Response]:
        """GET a URL, or return None if it is disallowed or fails."""
        if not self._allowed(url):
            log.info("robots.txt disallows %s - skipping", url)
            return None

        full = url
        if params:
            full = f"{url}?{urllib.parse.urlencode(params)}"

        host = urllib.parse.urlsplit(url).netloc
        # A host that has already refused this many requests is not going to
        # start saying yes to the next one.
        if host in self._rate_limited:
            log.debug("skipping %s: %s is rate limiting this run", full, host)
            return None

        last_error: Optional[Exception] = None
        for attempt in range(retries + 1):
            self._throttle(host)
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                if resp.status_code == 429:
                    backoff = self._note_rate_limit(
                        host, resp.headers.get("Retry-After")
                    )
                    if host in self._rate_limited:
                        return None
                    log.warning(
                        "%s returned 429, backing off %.1fs (this host has "
                        "refused %d request(s) so far)",
                        full,
                        backoff,
                        self._host_429.get(host, 1),
                    )
                    time.sleep(backoff)
                    continue
                if resp.status_code >= 500:
                    backoff = min(30, self.delay * (2 ** (attempt + 1)))
                    log.warning(
                        "%s returned %s, backing off %.1fs",
                        full,
                        resp.status_code,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                # Anything that is not a rate limit means the host is talking
                # to us again, so stop holding its earlier refusals against it.
                self._host_429.pop(host, None)
                if resp.status_code >= 400:
                    log.info("%s returned %s", full, resp.status_code)
                    return None
                return resp
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(20, self.delay * (2 ** attempt)))
        if last_error:
            log.warning("giving up on %s: %s", full, last_error)
        return None

    def get_text(self, url: str, **kwargs) -> Optional[str]:
        path = self._cache_path(url, ".txt")
        if kwargs.get("use_cache", True):
            hit = self._cached(path)
            if hit is not None:
                return hit.decode("utf-8", "replace")
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        text = resp.text
        if path:
            path.write_text(text, encoding="utf-8")
        return text

    def get_json(self, url: str, **kwargs):
        resp = self.get(url, **kwargs)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            log.info("%s did not return JSON", url)
            return None

    def get_image(self, url: str, max_bytes: int = 12_000_000) -> Optional[bytes]:
        """Download an image, refusing anything that is not one."""
        path = self._cache_path(url, ".img")
        hit = self._cached(path)
        if hit is not None:
            return hit
        resp = self.get(url, use_cache=False)
        if resp is None:
            return None
        ctype = resp.headers.get("Content-Type", "")
        if not ctype.startswith("image/"):
            log.info("%s is %s, not an image", url, ctype or "untyped")
            return None
        data = resp.content
        if len(data) > max_bytes:
            log.info("%s is %d bytes, too large", url, len(data))
            return None
        if path:
            path.write_bytes(data)
        return data
