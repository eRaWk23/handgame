"""Adapter tests against canned pages.

The scraper runs in GitHub Actions where it can reach the open web, but the
parsing logic should be provable without a network, so every adapter is
exercised here against fixture documents.

Run:  python3 tests/test_adapters.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handgame_scraper.sources.calendars import CalendarFeedSource  # noqa: E402
from handgame_scraper.sources.reddit import RedditSource  # noqa: E402
from handgame_scraper.sources.webpages import WebPagesSource  # noqa: E402

PASS = FAIL = 0
FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


def check_true(label: str, got) -> None:
    check(label, bool(got), True)


class StubFetcher:
    """Serves canned responses instead of making requests."""

    def __init__(self, text_map=None, json_map=None):
        self.text_map = text_map or {}
        self.json_map = json_map or {}
        self.session = type("S", (), {"headers": {"User-Agent": "test"}})()
        self.requested: list[str] = []

    def get_text(self, url, **kw):
        self.requested.append(url)
        return self.text_map.get(url)

    def get_json(self, url, **kw):
        self.requested.append(url)
        return self.json_map.get(url)

    def get_image(self, url, **kw):
        return None


# ---------------------------------------------------------------- JSON-LD
JSONLD_PAGE = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event",
 "name":"49th Annual Handgame Tournament",
 "startDate":"2026-09-18T09:00:00-07:00",
 "endDate":"2026-09-20T22:00:00-07:00",
 "url":"https://example.org/events/handgame-2026",
 "image":"https://example.org/img/handgame-flyer-2026.jpg",
 "description":"Three days of stick game. Entry $500 per team, $30,000 payout.",
 "location":{"@type":"Place","name":"Tribal Longhouse",
   "address":{"@type":"PostalAddress","addressLocality":"Wellpinit",
     "addressRegion":"WA"}}}
</script></head><body><h1>Events</h1></body></html>"""


def test_jsonld():
    print("\nschema.org JSON-LD")
    fetcher = StubFetcher({"https://example.org/events": JSONLD_PAGE})
    source = WebPagesSource(
        fetcher, {"sites": [{"url": "https://example.org/events", "follow_links": False}]}
    )
    events = [e.tidy() for e in source.collect()]
    check("one event parsed", len(events), 1)
    if events:
        ev = events[0]
        check("title", ev.title, "49th Annual Handgame Tournament")
        check("start date", ev.start_date, "2026-09-18")
        check("end date", ev.end_date, "2026-09-20")
        check("location", ev.location, "Tribal Longhouse, Wellpinit, WA")
        check("flyer", ev.flyer_url, "https://example.org/img/handgame-flyer-2026.jpg")
        check("source url", ev.source_url, "https://example.org/events/handgame-2026")
        check_true("high confidence for structured data", ev.confidence >= 0.8)


# ------------------------------------------------------- JSON-LD @graph
GRAPH_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"WebPage","name":"Events"},
 {"@type":["Event","SocialEvent"],"name":"Fall Stick Game Tourney",
  "startDate":"2026-10-10","location":"Pablo, MT"}]}
</script></head><body></body></html>"""


def test_jsonld_graph():
    print("\nJSON-LD inside @graph")
    fetcher = StubFetcher({"https://example.org/g": GRAPH_PAGE})
    source = WebPagesSource(
        fetcher, {"sites": [{"url": "https://example.org/g", "follow_links": False}]}
    )
    events = [e.tidy() for e in source.collect()]
    check("event found inside @graph", len(events), 1)
    if events:
        check("title", events[0].title, "Fall Stick Game Tourney")
        check("date", events[0].start_date, "2026-10-10")


# ------------------------------------------------------------ plain HTML
HTML_PAGE = """<!DOCTYPE html><html><body>
<nav><a href="/login">Login</a></nav>
<article class="event">
  <h2>Memorial Day Bone Game Tournament</h2>
  <p>May 22-25, 2026 at the Kalispel Community Center, Usk, WA.</p>
  <p>Entry fee $300 per team. Call Marvin 509-555-0188 to register.</p>
  <img src="/uploads/2026-bonegame-flyer.jpg" width="800" height="1200" alt="Tournament flyer">
  <a href="/events/memorial-bone-game">Details</a>
</article>
<article class="event">
  <h2>Craft Fair</h2><p>June 1, 2026. Handmade goods.</p>
</article>
</body></html>"""


def test_plain_html():
    print("\nplain HTML event block")
    url = "https://kalispel.example/events"
    fetcher = StubFetcher({url: HTML_PAGE})
    source = WebPagesSource(
        fetcher, {"sites": [{"url": url, "follow_links": False, "tribe": "Kalispel"}]}
    )
    events = [e.tidy() for e in source.collect()]
    check("only the handgame event is kept", len(events), 1)
    if events:
        ev = events[0]
        check("title", ev.title, "Memorial Day Bone Game Tournament")
        check("start date", ev.start_date, "2026-05-22")
        check("end date", ev.end_date, "2026-05-25")
        check("tribe", ev.tribe, "Kalispel")
        check("flyer url is absolute",
              ev.flyer_url, "https://kalispel.example/uploads/2026-bonegame-flyer.jpg")
        check_true("phone captured", "509-555-0188" in (ev.details or ""))
        check("link followed to the detail page",
              ev.source_url, "https://kalispel.example/events/memorial-bone-game")


# ---------------------------------------------------- WordPress calendar
WP_JSON = {
    "events": [
        {
            "title": "Annual Handgame Tournament &#038; Powwow",
            "description": "<p>Come play <strong>stick game</strong>. $15,000 payout.</p>",
            "start_date": "2026-07-24 08:00:00",
            "end_date": "2026-07-26 23:00:00",
            "url": "https://tribe.example/event/handgame-2026/",
            "image": {"url": "https://tribe.example/wp/flyer.jpg"},
            "venue": {"venue": "Powwow Grounds", "city": "Toppenish", "state": "WA"},
        },
        {
            "title": "Budget Hearing",
            "description": "Quarterly budget meeting.",
            "start_date": "2026-07-30 10:00:00",
            "url": "https://tribe.example/event/budget/",
        },
    ]
}


def test_wordpress():
    print("\nWordPress 'The Events Calendar' feed")
    base = "https://tribe.example"
    fetcher = StubFetcher(
        json_map={f"{base}/wp-json/tribe/events/v1/events": WP_JSON}
    )
    source = CalendarFeedSource(fetcher, {"sites": [{"url": base, "tribe": "Yakama"}]})
    events = [e.tidy() for e in source.collect()]
    check("only the handgame event is kept", len(events), 1)
    if events:
        ev = events[0]
        check("html entities decoded", ev.title, "Annual Handgame Tournament & Powwow")
        check("start date", ev.start_date, "2026-07-24")
        check("end date", ev.end_date, "2026-07-26")
        check("venue assembled", ev.location, "Powwow Grounds, Toppenish, WA")
        check("flyer from nested image object", ev.flyer_url, "https://tribe.example/wp/flyer.jpg")
        check_true("tags stripped from details", "<p>" not in (ev.details or ""))


# ------------------------------------------------------------------ iCal
ICS_FEED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Winter Handgame Tournament
DTSTART;VALUE=DATE:20261212
DTEND;VALUE=DATE:20261214
LOCATION:Fort Hall\\, ID
DESCRIPTION:Stick game tournament with a $10\\,000 payout. Entry fee
  is $400 per team.
URL:https://sbt.example/events/winter-handgame
END:VEVENT
BEGIN:VEVENT
SUMMARY:Council Meeting
DTSTART;VALUE=DATE:20261215
LOCATION:Fort Hall\\, ID
END:VEVENT
END:VCALENDAR"""


def test_ical():
    print("\niCal feed")
    base = "https://sbt.example"
    fetcher = StubFetcher(text_map={f"{base}/events/?ical=1": ICS_FEED})
    source = CalendarFeedSource(fetcher, {"sites": [{"url": base}]})
    events = [e.tidy() for e in source.collect()]
    check("only the handgame event is kept", len(events), 1)
    if events:
        ev = events[0]
        check("title", ev.title, "Winter Handgame Tournament")
        check("start date", ev.start_date, "2026-12-12")
        check("end date", ev.end_date, "2026-12-14")
        check("escaped comma unescaped", ev.location, "Fort Hall, ID")
        check_true("folded description rejoined", "400 per team" in (ev.details or ""))
        check("url field used", ev.source_url, "https://sbt.example/events/winter-handgame")


# ---------------------------------------------------------------- Reddit
REDDIT_JSON = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc123",
                    "title": "Handgame tournament in Nespelem Sept 4-6 2026",
                    "selftext": "Colville powwow grounds. $20,000 payout. Call 509-555-0142.",
                    "permalink": "/r/IndianCountry/comments/abc123/handgame/",
                    "created_utc": 1767225600,
                    "preview": {
                        "images": [
                            {"source": {"url": "https://preview.redd.it/x.jpg?width=1080&amp;auto=webp"}}
                        ]
                    },
                }
            },
            {
                "data": {
                    "id": "def456",
                    "title": "Best gaming mouse for FPS?",
                    "selftext": "Looking for a video game mouse.",
                    "permalink": "/r/IndianCountry/comments/def456/mouse/",
                }
            },
        ]
    }
}


def test_reddit():
    print("\nReddit")
    source = RedditSource(StubFetcher(), {"allow_unauthenticated": True})
    source._api_get = lambda path, params: REDDIT_JSON  # type: ignore[assignment]
    source.settings["subreddits"] = ["IndianCountry"]
    source.settings["queries"] = ["handgame"]

    events = [e.tidy() for e in source.collect()]
    check("only the handgame post is kept", len(events), 1)
    if events:
        ev = events[0]
        check("date from the post title", ev.start_date, "2026-09-04")
        check("end date", ev.end_date, "2026-09-06")
        check("location", ev.location, "Nespelem, Washington")
        check("tribe", ev.tribe, "Colville")
        check("preview image unescaped",
              ev.flyer_url, "https://preview.redd.it/x.jpg?width=1080&auto=webp")
        check("permalink built",
              ev.source_url, "https://www.reddit.com/r/IndianCountry/comments/abc123/handgame/")

    off = RedditSource(StubFetcher(), {})
    ok, reason = off.available()
    check("stays off without credentials", ok, False)
    check_true("and explains why", "REDDIT_CLIENT_ID" in reason)


# ------------------------------------------------------------ robustness
def test_robustness():
    print("\nbroken input")
    bad_pages = {
        "https://a.example": "<html><script type='application/ld+json'>{not json</script></html>",
        "https://b.example": "",
        "https://c.example": "<html><body>handgame tournament</body></html>",  # no date
    }
    fetcher = StubFetcher(bad_pages)
    source = WebPagesSource(
        fetcher,
        {"sites": [{"url": u, "follow_links": False} for u in bad_pages]},
    )
    try:
        events = list(source.collect())
        check("malformed pages produce no events, no crash", len(events), 0)
    except Exception as exc:  # noqa: BLE001
        check(f"malformed pages crashed: {exc}", False, True)

    empty = CalendarFeedSource(StubFetcher(), {"sites": [{"url": "https://none.example"}]})
    check("missing feeds produce nothing", len(list(empty.collect())), 0)


if __name__ == "__main__":
    for fn in [
        test_jsonld, test_jsonld_graph, test_plain_html, test_wordpress,
        test_ical, test_reddit, test_robustness,
    ]:
        fn()
    print(f"\n  {PASS} passed, {FAIL} failed\n")
    for failure in FAILURES:
        print(f"  FAIL  {failure}")
    sys.exit(1 if FAIL else 0)
