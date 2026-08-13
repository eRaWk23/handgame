"""Machine-readable calendar feeds.

A large share of tribal, casino and community sites run WordPress with "The
Events Calendar" plugin, which exposes a clean JSON API, or publish an .ics
feed. Both give exact dates with no parsing guesswork, so this adapter is the
highest-quality source available and is worth pointing at every site you can.

The adapter probes the usual endpoints automatically, so config.yaml only
needs the site's home page.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Iterator, Optional

from ..extract import find_tribe, topic_score
from ..models import Event
from .base import Source

WP_PATHS = [
    "/wp-json/tribe/events/v1/events",
    "/wp-json/tribe/events/v1/events?per_page=50",
]
ICS_PATHS = [
    "/events/?ical=1",
    "/events.ics",
    "/calendar.ics",
    "/?post_type=tribe_events&ical=1",
]


class CalendarFeedSource(Source):
    name = "calendars"
    label = "Event calendar feeds (WordPress / iCal)"

    def collect(self) -> Iterator[Event]:
        sites: list[Any] = self.settings.get("sites") or []
        min_topic = float(self.settings.get("min_topic_score", 0.5))

        for entry in sites:
            site = entry if isinstance(entry, dict) else {"url": entry}
            base = (site.get("url") or "").rstrip("/")
            if not base:
                continue

            got = 0
            found_feed = False
            for path in ([site["feed"]] if site.get("feed") else WP_PATHS):
                url = path if path.startswith("http") else base + path
                data = self.fetch.get_json(url)
                if isinstance(data, dict) and data.get("events"):
                    found_feed = True
                    nodes = data["events"]
                    for node in nodes:
                        event = self._from_wp(node, site, min_topic)
                        if event:
                            got += 1
                            yield event
                    # A feed that answers but yields nothing is a completely
                    # different problem from a site with no feed at all, and
                    # the two used to look identical in the run output.
                    self.log.info(
                        "%s: WordPress feed carried %d events, kept %d "
                        "(topic score >= %.2f)",
                        url,
                        len(nodes),
                        got,
                        min_topic,
                    )
                    break

            if got:
                continue

            for path in ([site["ics"]] if site.get("ics") else ICS_PATHS):
                url = path if path.startswith("http") else base + path
                text = self.fetch.get_text(url)
                if text and "BEGIN:VEVENT" in text:
                    found_feed = True
                    in_feed = text.count("BEGIN:VEVENT")
                    kept = 0
                    for event in self._from_ics(text, site, url, min_topic):
                        kept += 1
                        yield event
                    self.log.info(
                        "%s: iCal feed carried %d events, kept %d "
                        "(topic score >= %.2f)",
                        url,
                        in_feed,
                        kept,
                        min_topic,
                    )
                    break

            if not found_feed:
                self.log.info("%s: no machine-readable feed found", base)

    # ------------------------------------------------------------------
    def _from_wp(self, node: dict, site: dict, min_topic: float) -> Optional[Event]:
        title = _strip_html(node.get("title"))
        description = _strip_html(node.get("description"))
        if topic_score(title, description, hint=site.get("hint")) < min_topic:
            return None

        venue = node.get("venue") or {}
        parts = [venue.get("venue"), venue.get("city"), venue.get("state")]
        location = ", ".join(p for p in parts if p) or site.get("location")

        image = node.get("image")
        if isinstance(image, dict):
            image = image.get("url")

        return self._event(
            title=title or "",
            start_date=_date_part(node.get("start_date") or node.get("utc_start_date")),
            end_date=_date_part(node.get("end_date") or node.get("utc_end_date")),
            location=location,
            tribe=find_tribe(f"{title} {description} {site.get('hint','')}")
            or site.get("tribe"),
            details=description,
            flyer_url=image if isinstance(image, str) else None,
            source_url=node.get("url") or site.get("url"),
            extraction="structured",
            confidence=0.92,
            raw_text=description,
        )

    # ------------------------------------------------------------------
    def _from_ics(
        self, text: str, site: dict, feed_url: str, min_topic: float
    ) -> Iterator[Event]:
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
            fields = _parse_ics_block(block)
            title = fields.get("SUMMARY", "")
            description = fields.get("DESCRIPTION", "")
            if topic_score(title, description, hint=site.get("hint")) < min_topic:
                continue
            start = _ics_date(fields.get("DTSTART"))
            if not start:
                continue
            end = _ics_date(fields.get("DTEND"))
            yield self._event(
                title=title,
                start_date=start,
                end_date=end if end and end != start else None,
                location=fields.get("LOCATION") or site.get("location"),
                tribe=find_tribe(f"{title} {description}") or site.get("tribe"),
                details=description or None,
                source_url=fields.get("URL") or feed_url,
                extraction="structured",
                confidence=0.9,
                raw_text=description,
            )


# ----------------------------------------------------------------------
def _strip_html(value: Any) -> str:
    if not isinstance(value, str):
        if isinstance(value, dict):
            value = value.get("rendered", "")
        else:
            return ""
    text = re.sub(r"<[^>]+>", " ", value)
    # WordPress emits numeric entities like &#038; as well as named ones;
    # html.unescape covers the whole set instead of a hand-picked few.
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _date_part(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else None


def _parse_ics_block(block: str) -> dict[str, str]:
    # Unfold continuation lines, which iCal wraps at 75 octets.
    unfolded = re.sub(r"\r?\n[ \t]", "", block)
    fields: dict[str, str] = {}
    for line in unfolded.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.split(";")[0].strip().upper()
        if key and value and key not in fields:
            fields[key] = (
                value.strip()
                .replace("\\,", ",")
                .replace("\\n", " ")
                .replace("\\;", ";")
            )
    return fields


def _ics_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = re.match(r"(\d{4})(\d{2})(\d{2})", value.strip())
    if not match:
        return None
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        ).strftime("%Y-%m-%d")
    except ValueError:
        return None
