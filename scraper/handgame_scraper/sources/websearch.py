"""Discovery: find handgame flyers on sites we do not know about yet.

The configured site list only finds events from places already on the list.
This adapter is how the list grows — it searches the open web for new flyer
pages, then hands each result to the same page parser used elsewhere.

Needs one search API key (both have free tiers). Set whichever you have:
    BRAVE_SEARCH_API_KEY   https://brave.com/search/api/
    SERPER_API_KEY         https://serper.dev

Without a key the adapter stays quiet rather than falling back to scraping a
search engine's HTML, which gets blocked and violates their terms anyway.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Iterator, Optional

import requests
from bs4 import BeautifulSoup

from ..extract import find_contact, find_dates, find_location, find_tribe, guess_title, topic_score
from ..models import Event
from .base import Source
from .webpages import WebPagesSource

DEFAULT_QUERIES = [
    "handgame tournament flyer {year}",
    "stickgame tournament {year} flyer",
    "hand game tournament schedule {year}",
    "bone game tournament {year}",
    "slahal tournament {year}",
    "stick game tournament powwow {year}",
    "handgame tournament payout entry fee {year}",
]

SKIP_HOSTS = {
    "pinterest.com", "www.pinterest.com", "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com", "twitter.com", "x.com",
    "youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com",
    "amazon.com", "ebay.com", "etsy.com", "www.handgame.info", "handgame.info",
}


class WebSearchSource(Source):
    name = "websearch"
    label = "Open web search"
    enabled_by_default = False

    def available(self) -> tuple[bool, str]:
        if os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("SERPER_API_KEY"):
            return True, ""
        return False, "no BRAVE_SEARCH_API_KEY or SERPER_API_KEY set"

    # ------------------------------------------------------------------
    def collect(self) -> Iterator[Event]:
        from datetime import date

        year = date.today().year
        queries = self.settings.get("queries") or DEFAULT_QUERIES
        per_query = int(self.settings.get("results_per_query", 15))
        max_pages = int(self.settings.get("max_pages", 40))

        seen_urls: set[str] = set()
        pages_done = 0

        for template in queries:
            for yr in (year, year + 1):
                query = template.format(year=yr)
                for result in self._search(query, per_query):
                    url = result.get("url") or ""
                    if not url or url in seen_urls:
                        continue
                    host = urllib.parse.urlsplit(url).netloc.lower()
                    if host in SKIP_HOSTS or pages_done >= max_pages:
                        continue
                    seen_urls.add(url)

                    snippet = f"{result.get('title','')} {result.get('description','')}"
                    if topic_score(snippet) < 0.5:
                        continue

                    pages_done += 1
                    yield from self._parse_page(url, snippet)

    # ------------------------------------------------------------------
    def _search(self, query: str, count: int) -> list[dict[str, Any]]:
        brave = os.environ.get("BRAVE_SEARCH_API_KEY")
        if brave:
            try:
                resp = requests.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"Accept": "application/json", "X-Subscription-Token": brave},
                    params={"q": query, "count": min(count, 20)},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return [
                        {
                            "url": r.get("url"),
                            "title": r.get("title"),
                            "description": r.get("description"),
                        }
                        for r in resp.json().get("web", {}).get("results", [])
                    ]
                self.log.info("brave search %s", resp.status_code)
            except requests.RequestException as exc:
                self.log.info("brave search failed: %s", exc)

        serper = os.environ.get("SERPER_API_KEY")
        if serper:
            try:
                resp = requests.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": serper, "Content-Type": "application/json"},
                    json={"q": query, "num": min(count, 20)},
                    timeout=30,
                )
                if resp.status_code == 200:
                    return [
                        {
                            "url": r.get("link"),
                            "title": r.get("title"),
                            "description": r.get("snippet"),
                        }
                        for r in resp.json().get("organic", [])
                    ]
                self.log.info("serper search %s", resp.status_code)
            except requests.RequestException as exc:
                self.log.info("serper search failed: %s", exc)

        return []

    # ------------------------------------------------------------------
    def _parse_page(self, url: str, snippet: str) -> Iterator[Event]:
        html = self.fetch.get_text(url)
        if not html:
            return
        soup = BeautifulSoup(html, "html.parser")

        # Reuse the tribal-site parser so search hits get the same treatment.
        helper = WebPagesSource(self.fetch, {})
        found = False
        for event in helper._from_jsonld(soup, url, {}):
            event.source = self.name
            event.confidence = min(event.confidence, 0.8)
            found = True
            yield event
        if found:
            return

        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        if topic_score(text) < 0.5:
            return

        start, end, warnings = find_dates(text)
        flyer = helper._flyer_in(soup, url)
        if not start and not flyer:
            return

        title_tag = soup.find(["h1", "h2"])
        yield self._event(
            title=(
                title_tag.get_text(" ", strip=True)
                if title_tag
                else guess_title(text, snippet[:80])
            ),
            start_date=start,
            end_date=end,
            location=find_location(text),
            tribe=find_tribe(text),
            details=find_contact(text),
            flyer_url=flyer,
            source_url=url,
            extraction="structured",
            confidence=0.5 if start else 0.25,
            raw_text=text[:3000],
            warnings=list(warnings),
        )
