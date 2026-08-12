"""Regression tests for bugs found in review.

Each one published wrong data or silently lost real events. They are kept
separate from the main suites so it stays obvious why they exist.

Run:  python3 tests/test_regressions.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handgame_scraper import dedupe  # noqa: E402
from handgame_scraper.extract import find_dates, find_location  # noqa: E402
from handgame_scraper.models import Event, location_state, normalize_location  # noqa: E402
from handgame_scraper.supabase import Supabase, SupabaseError  # noqa: E402
from handgame_scraper.sources.webpages import WebPagesSource  # noqa: E402

PASS = FAIL = 0
FAILURES: list[str] = []
TODAY = date(2026, 8, 12)


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


def dates(text):
    s, e, w = find_dates(text, today=TODAY)
    return (s.strftime("%Y-%m-%d") if s else None,
            e.strftime("%Y-%m-%d") if e else None)


# 1 -------------------------------------------------------------------
def test_day_list_is_not_a_year():
    """"AUGUST 29, 30, 31" once parsed as August 29th, 2030."""
    print("\n1. a list of days is not a two-digit year")
    check("AUGUST 29, 30, 31", dates("AUGUST 29, 30, 31"), ("2026-08-29", "2026-08-31"))
    check("SEPT 12, 13 & 14", dates("SEPT 12, 13 & 14"), ("2026-09-12", "2026-09-14"))
    check("printed year survives a day list",
          dates("OCTOBER 10, 11, 2026"), ("2026-10-10", "2026-10-11"))
    check("MAY 30, 31 rolls to next year",
          dates("MAY 30, 31"), ("2027-05-30", "2027-05-31"))
    check("scattered days are not a range",
          dates("JUNE 6, 27 & 28"), ("2027-06-06", None))
    check("apostrophe year still works", dates("Sept 12 '26"), ("2026-09-12", None))
    check("plain range unaffected",
          dates("September 12-14, 2026"), ("2026-09-12", "2026-09-14"))
    check("month rollover unaffected",
          dates("Aug 29 - Sep 1, 2026"), ("2026-08-29", "2026-09-01"))


# 2 -------------------------------------------------------------------
LISTING_PAGE = """<html><body>
<header><a href="/">Example Tribe</a></header>
<h2>Fall Handgame Tournament</h2>
<p>October 17, 2026 in Keller, WA. Stick game all weekend.</p>
</body></html>"""

SECOND_PAGE = """<html><body>
<header><a href="/">Example Tribe</a></header>
<h2>Winter Handgame Tournament</h2>
<p>December 12, 2026 in Inchelium, WA. Bone game tourney.</p>
</body></html>"""


def test_events_do_not_share_a_fingerprint():
    """Every event from a site once collapsed into one ledger entry."""
    print("\n2. two events on one site get two fingerprints")

    class Stub:
        def __init__(self, pages):
            self.pages = pages
            self.session = type("S", (), {"headers": {"User-Agent": "t"}})()

        def get_text(self, url, **kw):
            return self.pages.get(url)

        def get_json(self, url, **kw):
            return None

        def get_image(self, url, **kw):
            return None

    pages = {
        "https://tribe.example/fall": LISTING_PAGE,
        "https://tribe.example/winter": SECOND_PAGE,
    }
    source = WebPagesSource(
        Stub(pages),
        {"sites": [{"url": u, "follow_links": False} for u in pages]},
    )
    events = [e.tidy() for e in source.collect()]
    check("both pages produced an event", len(events), 2)
    if len(events) == 2:
        check("fingerprints differ",
              events[0].fingerprint != events[1].fingerprint, True)
        check_true("a header logo link is not used as the event url",
                   all(e.source_url in pages for e in events))

    # Two events on one page, no per-event links, must still differ.
    a = Event(title="Fall Tournament", start_date="2026-10-17",
              location="Keller, WA", source_url="https://tribe.example/events")
    b = Event(title="Winter Tournament", start_date="2026-12-12",
              location="Inchelium, WA", source_url="https://tribe.example/events")
    check("same page url, different events, different fingerprints",
          a.fingerprint != b.fingerprint, True)


# 3 -------------------------------------------------------------------
def test_la_is_not_louisiana():
    """"...Lodge, La Conner, WA" once became "Lodge, Louisiana"."""
    print("\n3. a town starting with a state code is read correctly")
    check("La Conner behind a venue name",
          find_location("Swinomish Casino & Lodge, La Conner, WA"),
          "La Conner, Washington")
    check("La Conner after a comma",
          find_location("Swinomish Casino, La Conner, WA"), "La Conner, Washington")
    check("shouted state name", find_location("WELLPINIT, WASHINGTON"),
          "Wellpinit, Washington")
    check("plain abbreviation", find_location("Nespelem, WA"), "Nespelem, Washington")
    check("canadian province", find_location("Kamloops, BC"),
          "Kamloops, British Columbia")
    check("rightmost address wins",
          find_location("Meet at Tribal Hall, Omak, WA before heading out"),
          "Omak, Washington")


# 4 -------------------------------------------------------------------
def test_two_letter_words_are_not_states():
    """"in" was expanded to Indiana, which broke duplicate detection."""
    print("\n4. ordinary two-letter words are not states")
    check("'in' is left alone",
          normalize_location("Community Center in Omak, WA"),
          "community center in omak washington")
    check("state read from the end", location_state("Community Center in Omak, WA"),
          "Washington")
    check("'la' is left alone", location_state("La Conner, WA"), "Washington")

    a = Event(title="Swinomish Handgame Tournament", start_date="2026-09-12",
              location="La Conner, WA").tidy()
    b = Event(title="Swinomish Handgame Tournament", start_date="2026-09-12",
              location="Swinomish Casino, La Conner, Washington").tidy()
    check("no false state conflict", dedupe._states_conflict(a.location, b.location), False)
    check("so the duplicate is caught", dedupe.against_existing(a, [b])[0], "duplicate")

    c = Event(title="Handgame Tournament", start_date="2026-09-12",
              location="Fort Hall, ID").tidy()
    check("a real state conflict still blocks a match",
          dedupe._states_conflict(a.location, c.location), True)


# 5 -------------------------------------------------------------------
def test_supabase_survives_junk():
    """A 200 carrying HTML once aborted the whole run."""
    print("\n5. a bad Supabase response degrades instead of crashing")

    class FakeResponse:
        def __init__(self, status, text):
            self.status_code = status
            self.text = text

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    import handgame_scraper.supabase as sb

    client = Supabase(url="https://x.supabase.co", key="k")
    original = sb.requests.get
    sb.requests.get = lambda *a, **k: FakeResponse(200, "<html>proxy error</html>")
    try:
        check("html body returns no events, no crash", client.fetch_events(), [])
    finally:
        sb.requests.get = original

    original_post = sb.requests.post
    sb.requests.post = lambda *a, **k: (_ for _ in ()).throw(
        sb.requests.RequestException("connection reset")
    )
    try:
        ev = Event(title="T", start_date="2026-09-05", location="Omak, WA")
        try:
            client.insert_event(ev)
            check("network error becomes SupabaseError", False, True)
        except SupabaseError:
            check("network error becomes SupabaseError", True, True)
        except Exception as exc:  # noqa: BLE001
            check(f"network error becomes SupabaseError (got {type(exc).__name__})",
                  False, True)
    finally:
        sb.requests.post = original_post


# 6 -------------------------------------------------------------------
def test_contact_is_not_duplicated():
    """The same phone number was published twice."""
    print("\n6. a phone number is added once, not twice")
    import tempfile as tf
    from handgame_scraper.pipeline import Pipeline

    with tf.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pipeline = Pipeline(
            {"settings": {"cache_dir": str(root / "c"),
                          "ledger_path": str(root / "seen.json")},
             "sources": {}},
            root,
        )
        ev = Event(title="Handgame Tournament", start_date="2026-09-05",
                   location="Omak, WA")
        text = "Handgame Tournament Sept 5 2026 Call Marie 509-555-0142"
        pipeline._fill_from_text(ev, text, "ocr")
        pipeline._fill_from_text(ev, text + " also marie@example.org", "ocr")
        check("phone appears once", (ev.details or "").count("509-555-0142"), 1)
        check_true("the email was still added", "marie@example.org" in (ev.details or ""))


# 7 -------------------------------------------------------------------
def test_merge_keeps_the_other_link():
    """merge() had a line that computed nothing."""
    print("\n7. merging two write-ups keeps the second link")
    primary = Event(title="Handgame Tournament", start_date="2026-09-05",
                    location="Omak, WA", source="reddit",
                    source_url="https://reddit.example/a")
    extra = Event(title="38th Annual Handgame Tournament", start_date="2026-09-05",
                  location="Omak, WA", source="calendars",
                  source_url="https://tribe.example/b", tribe="Colville")
    merged = dedupe.merge(primary, extra)
    check_true("second url noted for the reviewer",
               any("tribe.example/b" in w for w in merged.warnings))
    check("fuller title kept", merged.title, "38th Annual Handgame Tournament")
    check("tribe filled in", merged.tribe, "Colville")


# 8 -------------------------------------------------------------------
def test_approved_column_falls_back():
    """The events table has an `approved` column that admin.html writes.

    A reviewed event should be marked approved, but if the column is missing
    or a policy blocks it, the insert must still go through with exactly the
    payload the public submission form sends.
    """
    print("\n8. the approved column is optional, never fatal")
    import handgame_scraper.supabase as sb

    class Resp:
        def __init__(self, status, payload=None, text=""):
            self.status_code = status
            self._payload = payload
            self.text = text

        def json(self):
            if self._payload is None:
                raise ValueError("no body")
            return self._payload

    client = Supabase(url="https://x.supabase.co", key="k")
    ev = Event(title="T", start_date="2026-09-05", location="Omak, WA")
    original = sb.requests.post
    sent: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json[0])
        if "approved" in json[0]:
            return Resp(400, text="column \"approved\" of relation \"events\" does not exist")
        return Resp(201, [{"id": 7, **json[0]}])

    sb.requests.post = fake_post
    try:
        result = client.insert_event(ev)
        check("insert succeeded on the retry", bool(result), True)
        check("first attempt included approved", "approved" in sent[0], True)
        check("second attempt dropped it", "approved" in sent[1], False)
        check("retry payload matches the public form",
              sorted(sent[1]),
              ["details", "end_date", "flyer_url", "location", "start_date",
               "title", "tribe"])
    finally:
        sb.requests.post = original

    sent.clear()
    sb.requests.post = lambda url, headers=None, json=None, timeout=None: (
        sent.append(json[0]) or Resp(201, [{"id": 8, **json[0]}])
    )
    try:
        client.insert_event(ev)
        check("when the column works, approved is set", sent[0].get("approved"), True)
        check("only one request needed", len(sent), 1)
    finally:
        sb.requests.post = original


# 9 -------------------------------------------------------------------
def test_community_flags_are_respected():
    """script.js hides an event once report_count reaches 3.

    A flagged-down event must still count as "on the site" for duplicate
    purposes, or the collector would re-add something the community just
    voted off, every run, forever.
    """
    print("\n9. an event flagged off the site is never re-added")
    import tempfile as tf
    from handgame_scraper.pipeline import Pipeline
    from handgame_scraper.supabase import REPORT_THRESHOLD, Supabase
    import handgame_scraper.supabase as sb

    check("threshold matches script.js", REPORT_THRESHOLD, 3)

    class Resp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return [
                {"id": 1, "title": "Spam Handgame Tournament",
                 "start_date": "2026-11-07", "location": "Omak, WA",
                 "report_count": 4},
                {"id": 2, "title": "Real Handgame Tournament",
                 "start_date": "2026-11-21", "location": "Keller, WA",
                 "report_count": 1},
            ]

    original = sb.requests.get
    sb.requests.get = lambda *a, **k: Resp()
    try:
        live = Supabase(url="https://x.supabase.co", key="k").fetch_events()
    finally:
        sb.requests.get = original

    check("both rows returned, flagged one included", len(live), 2)
    check("flagged row is marked", live[0].source, "live-site-flagged")
    check("lightly reported row is not", live[1].source, "live-site")

    with tf.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pipeline = Pipeline(
            {"settings": {"cache_dir": str(root / "c"),
                          "ledger_path": str(root / "seen.json")},
             "sources": {}},
            root,
        )
        pipeline.supabase = type("S", (), {"fetch_events": lambda self, **k: live})()

        rediscovered = Event(title="Spam Handgame Tournament",
                             start_date="2026-11-07", location="Omak, WA",
                             source="webpages",
                             source_url="https://spam.example/e").tidy()
        genuinely_new = Event(title="Winter Handgame Tournament",
                              start_date="2026-12-19", location="Inchelium, WA",
                              source="webpages",
                              source_url="https://tribe.example/w").tidy()

        queued = pipeline._compare_to_live([rediscovered, genuinely_new])
        titles = [e.title for e in queued]
        check("the flagged event is not queued again",
              "Spam Handgame Tournament" in titles, False)
        check("counted as community-flagged, not a plain duplicate",
              pipeline.stats.community_flagged, 1)
        check("and not double counted", pipeline.stats.already_live, 0)
        check("a genuinely new event still gets through",
              "Winter Handgame Tournament" in titles, True)
        check("the ledger records why",
              pipeline.ledger.entries[rediscovered.fingerprint]["outcome"],
              "community-flagged")


if __name__ == "__main__":
    for fn in [
        test_day_list_is_not_a_year,
        test_events_do_not_share_a_fingerprint,
        test_la_is_not_louisiana,
        test_two_letter_words_are_not_states,
        test_supabase_survives_junk,
        test_contact_is_not_duplicated,
        test_merge_keeps_the_other_link,
        test_approved_column_falls_back,
        test_community_flags_are_respected,
    ]:
        fn()
    print(f"\n  {PASS} passed, {FAIL} failed\n")
    for failure in FAILURES:
        print(f"  FAIL  {failure}")
    sys.exit(1 if FAIL else 0)
