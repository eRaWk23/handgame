"""Generic website adapter — the workhorse for tribal, casino and powwow sites.

For each site in config.yaml it tries three things in order of reliability:

  1. schema.org Event JSON-LD, which many modern event pages emit. This gives
     clean structured dates with no guessing at all.
  2. Microdata / meta tags as a weaker structured fallback.
  3. Plain HTML: find blocks of text mentioning handgame, pull the date out,
     and grab any nearby flyer image.

Anything it finds that has a flyer image gets OCR'd later in the pipeline, so
even a page that yields only "here is a picture" ends up useful.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Iterator, Optional

from bs4 import BeautifulSoup

from ..extract import (
    find_contact,
    find_dates,
    find_location,
    find_tribe,
    guess_title,
    topic_score,
)
from ..models import Event
from .base import Source

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
FLYER_HINT = re.compile(r"flyer|flier|poster|tourn|handgame|stickgame|bone.?game|event", re.I)


class WebPagesSource(Source):
    name = "webpages"
    label = "Tribal, casino and powwow websites"

    def collect(self) -> Iterator[Event]:
        sites: list[Any] = self.settings.get("sites") or []
        max_links = int(self.settings.get("max_links_per_site", 25))
        min_topic = float(self.settings.get("min_topic_score", 0.5))

        for entry in sites:
            site = entry if isinstance(entry, dict) else {"url": entry}
            url = site.get("url")
            if not url:
                continue
            self.log.info("scanning %s", url)
            html = self.fetch.get_text(url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")

            found_any = False
            for event in self._from_jsonld(soup, url, site):
                found_any = True
                yield event

            for event in self._from_html(soup, url, site, min_topic):
                found_any = True
                yield event

            # Follow a small number of promising links deeper into the site.
            if site.get("follow_links", True):
                for link in self._promising_links(soup, url)[:max_links]:
                    sub_html = self.fetch.get_text(link)
                    if not sub_html:
                        continue
                    sub = BeautifulSoup(sub_html, "html.parser")
                    for event in self._from_jsonld(sub, link, site):
                        yield event
                    for event in self._from_html(sub, link, site, min_topic):
                        yield event

    # ------------------------------------------------------------------
    def _from_jsonld(
        self, soup: BeautifulSoup, page_url: str, site: dict
    ) -> Iterator[Event]:
        for tag in soup.find_all("script", type="application/ld+json"):
            raw = tag.string or tag.get_text() or ""
            try:
                data = json.loads(raw.strip())
            except (json.JSONDecodeError, AttributeError):
                continue
            for node in _walk_jsonld(data):
                types = node.get("@type")
                types = [types] if isinstance(types, str) else (types or [])
                if not any("event" in str(t).lower() for t in types):
                    continue
                title = _text(node.get("name"))
                description = _text(node.get("description"))
                if topic_score(title, description, hint=site.get("hint")) < 0.5:
                    continue
                yield self._event(
                    title=title or "",
                    start_date=_iso_date(node.get("startDate")),
                    end_date=_iso_date(node.get("endDate")),
                    location=_jsonld_place(node.get("location")) or site.get("location"),
                    tribe=find_tribe(f"{title} {description} {site.get('hint','')}")
                    or site.get("tribe"),
                    details=description,
                    flyer_url=_jsonld_image(node.get("image")),
                    source_url=_text(node.get("url")) or page_url,
                    extraction="structured",
                    confidence=0.85,
                    raw_text=description,
                )

    # ------------------------------------------------------------------
    def _from_html(
        self, soup: BeautifulSoup, page_url: str, site: dict, min_topic: float
    ) -> Iterator[Event]:
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        page_text = soup.get_text("\n", strip=True)
        if topic_score(page_text, hint=site.get("hint")) < min_topic:
            return

        # Prefer a tight container over the whole page so dates stay near titles.
        blocks = soup.select(
            "article, .event, .events, .tribe-events-calendar-list__event, "
            ".event-item, .post, li.event, .eventitem, .em-item"
        )
        # When nothing matches we read the whole page as one block. In that
        # case there is no per-event link to trust: the first <a> is a site
        # logo, not this event.
        whole_page = not blocks
        if whole_page:
            blocks = [soup]

        for block in blocks[:40]:
            text = block.get_text("\n", strip=True)
            if len(text) < 25 or topic_score(text, hint=site.get("hint")) < min_topic:
                continue
            start, end, warnings = find_dates(text)
            flyer = self._flyer_in(block, page_url) or self._flyer_in(soup, page_url)
            if not start and not flyer:
                continue

            heading = block.find(["h1", "h2", "h3", "h4"])
            title = (
                heading.get_text(" ", strip=True)
                if heading
                else guess_title(text, site.get("name", ""))
            )
            source_url = page_url
            if not whole_page:
                link = block.find("a", href=True)
                if link:
                    candidate = urllib.parse.urljoin(page_url, link["href"])
                    # Ignore links back to the page itself or to the site root.
                    if candidate.rstrip("/") != page_url.rstrip("/") and (
                        urllib.parse.urlsplit(candidate).path.strip("/")
                    ):
                        source_url = candidate

            yield self._event(
                title=title,
                start_date=start,
                end_date=end,
                location=find_location(text) or site.get("location"),
                tribe=find_tribe(text) or site.get("tribe"),
                details=find_contact(text) or _snippet(text),
                flyer_url=flyer,
                source_url=source_url,
                extraction="structured",
                confidence=0.6 if start else 0.3,
                raw_text=text[:3000],
                warnings=list(warnings),
            )

    # ------------------------------------------------------------------
    def _flyer_in(self, node, page_url: str) -> Optional[str]:
        best: Optional[str] = None
        best_score = -1
        for img in node.find_all("img", limit=40):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or ""
            )
            if not src or src.startswith("data:"):
                continue
            absolute = urllib.parse.urljoin(page_url, src)
            path = urllib.parse.urlsplit(absolute).path.lower()
            if not path.endswith(IMAGE_EXT):
                continue
            if re.search(r"logo|icon|avatar|banner|header|sprite|spacer", path):
                continue
            score = 0
            haystack = f"{path} {img.get('alt','')} {img.get('class','')}"
            if FLYER_HINT.search(haystack):
                score += 3
            try:
                width = int(str(img.get("width", "0")).rstrip("px") or 0)
                height = int(str(img.get("height", "0")).rstrip("px") or 0)
                if width and height:
                    if width < 200 or height < 200:
                        continue
                    # Flyers are portrait; wide images are usually page banners.
                    if height >= width:
                        score += 2
            except (ValueError, TypeError):
                pass
            if score > best_score:
                best, best_score = absolute, score
        return best

    def _promising_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        host = urllib.parse.urlsplit(page_url).netloc
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            absolute = urllib.parse.urljoin(page_url, a["href"]).split("#")[0]
            if absolute in seen:
                continue
            parts = urllib.parse.urlsplit(absolute)
            # The Events Calendar publishes its subscribe links as webcal://,
            # which shares the site's host and so used to pass the check below
            # and then die in requests with "no connection adapters".
            if parts.scheme not in ("http", "https"):
                continue
            if parts.netloc != host:
                continue
            seen.add(absolute)
            label = f"{a.get_text(' ', strip=True)} {absolute}".lower()
            score = 0
            if re.search(r"handgame|hand.game|stickgame|stick.game|bone.game|slahal", label):
                score += 5
            if re.search(r"\bevents?\b|calendar|tournament|powwow|pow.wow", label):
                score += 3
            if re.search(r"news|announce|upcoming|community", label):
                score += 1
            if re.search(r"login|cart|privacy|terms|careers|jobs|\.pdf$", label):
                score -= 5
            if score > 2:
                scored.append((score, absolute))
        scored.sort(key=lambda x: -x[0])
        return [url for _, url in scored]


# ----------------------------------------------------------------------
def _walk_jsonld(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        # No special case for @graph: the recursion below already walks it,
        # and handling it separately yielded every node inside it twice.
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _walk_jsonld(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return re.sub(r"<[^>]+>", " ", value).strip() or None
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@value"))
    if isinstance(value, list) and value:
        return _text(value[0])
    return None


def _iso_date(value: Any) -> Optional[str]:
    text = _text(value)
    if not text:
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


def _jsonld_place(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    name = _text(value.get("name"))
    address = value.get("address")
    if isinstance(address, dict):
        city = _text(address.get("addressLocality"))
        region = _text(address.get("addressRegion"))
        place = ", ".join(p for p in (city, region) if p)
        if place:
            return f"{name}, {place}" if name else place
    elif isinstance(address, str):
        return address.strip() or name
    return name


def _jsonld_image(value: Any) -> Optional[str]:
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _text(value.get("url") or value.get("contentUrl"))
    return None


def _snippet(text: str, limit: int = 400) -> Optional[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:limit] or None
