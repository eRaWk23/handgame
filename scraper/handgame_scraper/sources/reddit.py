"""Reddit.

Reddit's robots.txt now disallows general crawling, so this adapter prefers
the official API with a free "script" app credential, which is the supported
and permitted way to read public posts programmatically.

Set these to enable it:
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET

Without credentials the adapter stays off unless you explicitly set
`allow_unauthenticated: true` in config.yaml, which uses the public .json
endpoints instead.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator, Optional

import requests

from ..extract import find_dates, find_location, find_tribe, topic_score
from ..models import Event
from .base import Source

OAUTH_BASE = "https://oauth.reddit.com"
PUBLIC_BASE = "https://www.reddit.com"

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


class RedditSource(Source):
    name = "reddit"
    label = "Reddit"
    enabled_by_default = False

    def __init__(self, fetcher, settings=None):
        super().__init__(fetcher, settings)
        self._token: Optional[str] = None
        self._token_expires: float = 0.0

    # ------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get(
            "REDDIT_CLIENT_SECRET"
        ):
            return True, ""
        if self.settings.get("allow_unauthenticated"):
            return True, ""
        return False, (
            "no REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, and "
            "allow_unauthenticated is not set"
        )

    def _get_token(self) -> Optional[str]:
        cid = os.environ.get("REDDIT_CLIENT_ID")
        secret = os.environ.get("REDDIT_CLIENT_SECRET")
        if not (cid and secret):
            return None
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        try:
            resp = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(cid, secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.fetch.session.headers["User-Agent"]},
                timeout=30,
            )
            if resp.status_code != 200:
                self.log.warning("reddit token %s: %s", resp.status_code, resp.text[:160])
                return None
            data = resp.json()
            self._token = data.get("access_token")
            self._token_expires = time.time() + int(data.get("expires_in", 3600))
            return self._token
        except requests.RequestException as exc:
            self.log.warning("reddit auth failed: %s", exc)
            return None

    def _api_get(self, path: str, params: dict[str, Any]) -> Optional[dict]:
        token = self._get_token()
        if token:
            try:
                resp = requests.get(
                    f"{OAUTH_BASE}{path}",
                    headers={
                        "Authorization": f"bearer {token}",
                        "User-Agent": self.fetch.session.headers["User-Agent"],
                    },
                    params=params,
                    timeout=30,
                )
                time.sleep(1.2)  # stay well under the rate limit
                if resp.status_code == 200:
                    return resp.json()
                self.log.info("reddit %s -> %s", path, resp.status_code)
            except requests.RequestException as exc:
                self.log.info("reddit request failed: %s", exc)
            return None
        # Unauthenticated fallback, only reached when explicitly allowed.
        return self.fetch.get_json(
            f"{PUBLIC_BASE}{path}.json", params=params, use_cache=False
        )

    # ------------------------------------------------------------------
    def collect(self) -> Iterator[Event]:
        queries: list[str] = self.settings.get("queries") or [
            "handgame", "hand game", "stickgame", "stick game",
            "bone game", "slahal", "lahal",
        ]
        subreddits: list[str] = self.settings.get("subreddits") or [
            "IndianCountry", "NativeAmerican", "Native_American", "indigenous",
            "Montana", "Idaho", "Spokane", "Washington", "Oregon",
            "britishcolumbia", "Saskatchewan", "alberta",
        ]
        limit = int(self.settings.get("limit_per_query", 50))
        timeframe = self.settings.get("timeframe", "year")

        seen_ids: set[str] = set()

        for sub in subreddits:
            for query in queries:
                data = self._api_get(
                    f"/r/{sub}/search",
                    {
                        "q": query,
                        "restrict_sr": "1",
                        "sort": "new",
                        "t": timeframe,
                        "limit": limit,
                    },
                )
                for post in _iter_posts(data):
                    pid = post.get("id")
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    event = self._to_event(post)
                    if event:
                        yield event

    # ------------------------------------------------------------------
    def _to_event(self, post: dict[str, Any]) -> Optional[Event]:
        title = (post.get("title") or "").strip()
        body = (post.get("selftext") or "").strip()
        blob = f"{title}\n{body}"

        if topic_score(blob) < 0.5:
            return None

        flyer = _best_image(post)
        start, end, warnings = find_dates(blob)

        # A post with no date and no flyer to OCR is not worth a reviewer's time.
        if not start and not flyer:
            return None

        permalink = post.get("permalink") or ""
        created = post.get("created_utc")

        return self._event(
            title=title,
            start_date=start,
            end_date=end,
            location=find_location(blob),
            tribe=find_tribe(blob),
            details=body[:600] or None,
            flyer_url=flyer,
            source_url=f"https://www.reddit.com{permalink}" if permalink else None,
            source_posted_at=(
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else None
            ),
            extraction="structured",
            raw_text=blob,
            warnings=list(warnings),
        )


def _iter_posts(data: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(data, dict):
        return
    for child in data.get("data", {}).get("children", []) or []:
        if isinstance(child, dict) and isinstance(child.get("data"), dict):
            yield child["data"]


def _best_image(post: dict[str, Any]) -> Optional[str]:
    """Pull the largest available flyer image out of a Reddit post."""
    preview = post.get("preview") or {}
    images = preview.get("images") or []
    if images:
        src = (images[0].get("source") or {}).get("url")
        if src:
            return src.replace("&amp;", "&")
    url = post.get("url_overridden_by_dest") or post.get("url") or ""
    if url.lower().split("?")[0].endswith(IMAGE_EXT):
        return url
    gallery = post.get("media_metadata") or {}
    for meta in gallery.values():
        if isinstance(meta, dict):
            src = (meta.get("s") or {}).get("u")
            if src:
                return src.replace("&amp;", "&")
    return None
