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
from handgame_scraper.extract import (  # noqa: E402
    find_dates,
    find_location,
    topic_score,
)
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


def test_hint_cannot_supply_the_keyword():
    """10. a config hint must not score a page on its own.

    config.yaml lets a site carry `hint: stickgame handgame tournament` to
    help thin pages. Every call site used to pass that hint as one of the
    *texts* arguments, so it was concatenated into the blob being searched
    and supplied the strong keyword itself. Result: a casino bingo listing
    scored 0.8 and every page on a hinted site passed the topic filter.
    Found on the first live run, where powwows.com/calendar/ scored 1.0
    with no handgame keyword anywhere on the page.
    """
    print("\n10. a config hint cannot make a page on topic by itself")
    hint = "stickgame handgame tournament"

    off_topic = "Bingo night at the casino, doors at 6pm"
    check("hint alone does not clear the threshold",
          topic_score(off_topic, hint=hint) < 0.5, True)
    check_true("and the hint is not silently ignored either",
               topic_score(off_topic, hint=hint) >= topic_score(off_topic))

    # The old behaviour, spelled out so nobody reintroduces it by passing
    # the hint positionally again.
    check_true("passing a hint positionally is what broke it",
               topic_score(off_topic, hint) >= 0.7)

    # A page that really is about handgame still scores, hint or not.
    real = "38th Annual Labor Day Handgame Tournament, double elimination"
    check_true("a real handgame page still scores high",
               topic_score(real, hint=hint) >= 0.7)
    check_true("and scores high with no hint at all",
               topic_score(real) >= 0.7)

    # A hint must not rescue something the negative list has ruled out.
    check("a hint cannot rescue an esports listing",
          topic_score("Fortnite video game tournament", hint=hint), 0.0)


def test_weekday_contradicts_the_date():
    """11. a printed weekday that disagrees with the date must warn.

    Found on the first real flyer run. Tesseract read the Nespelem
    Celebration flyer's "Thursday, July 9, 2026" as "July 7, 2026" — a
    clean parse, high confidence, no warning, and off by two days. Nothing
    in the pipeline could have caught it: the date is well-formed and in
    range. The flyer prints the weekday right next to the date, and July
    7th 2026 is a Tuesday, so the contradiction was there to be found.

    A wrong date sends someone to an empty gym, so this warns rather than
    guessing which of the two was misread.
    """
    print("\n11. a weekday that contradicts its date is flagged")

    def warn(text):
        return find_dates(text, today=TODAY)[2]

    # The real OCR output that motivated this.
    misread = "Thursday, July 7, 2026 Registration closes 8pm"
    check_true("the actual misread flyer is flagged",
               any("Thursday" in w and "Tuesday" in w for w in warn(misread)))

    # What the flyer really says must stay silent.
    for good in ("Thursday, July 9, 2026",
                 "Friday, July 10, 2026",
                 "Saturday, July 11, 2026",
                 "Sunday, July 12, 2026"):
        check(f"{good!r} is consistent",
              [w for w in warn(good) if "flyer says" in w], [])

    # Other spellings of the same contradiction.
    check_true("day-first form is checked",
               any("flyer says" in w for w in warn("Monday 27 June 2026")))
    check_true("abbreviations are checked",
               any("flyer says" in w for w in warn("Wed, Jun 27 2026")))
    check("abbreviations do not false-positive",
          [w for w in warn("Sat, Jun 27 2026") if "flyer says" in w], [])

    # A weekday that is not next to the date proves nothing about it.
    check("a distant weekday is not paired with the date",
          [w for w in warn("Saturday is our big day. Come out June 27, 2026")
           if "flyer says" in w], [])
    check("no weekday printed means nothing to check",
          [w for w in warn("September 12-14, 2026") if "flyer says" in w], [])

    # Without a printed year the weekday cannot pick the year, so only a
    # day that fits no nearby year at all is a real contradiction.
    check("a correct weekday with no year stays silent",
          [w for w in warn("Saturday, June 27") if "flyer says" in w], [])

    # The warning must name the date that actually got queued.
    start, _end, warnings = find_dates("Monday, June 27", today=TODAY)
    named = [w for w in warnings if "flyer says" in w]
    check_true("the warning names the year that was queued",
               named and str(start.year) in named[0])

    # A warning must never rewrite the date it warns about.
    start, _end, _w = find_dates(misread, today=TODAY)
    check("the contradicted date is reported unchanged, not corrected",
          start.isoformat(), "2026-07-07")


def test_ocr_does_not_outrank_the_flyer_reader():
    """12. Tesseract must not lock the vision reader out of a field.

    _fill_from_vision only wrote to fields that were still empty, and OCR
    always runs first. So whatever Tesseract produced — a garbled title, a
    misread date — was final, and the vision call was reduced to filling
    blanks. On the first paid run the reader read the Nespelem flyer
    correctly as "Nespelem Celebration Stickgames", July 9th; the event kept
    OCR's junk title and OCR's July 7th and was dropped as off topic.

    The reader now wins on title, dates and location. It never overrules a
    value a person typed into a sidecar note, and a date it disagrees with
    is reported rather than swapped silently.
    """
    print("\n12. the flyer reader corrects OCR instead of filling its blanks")
    from handgame_scraper.pipeline import Pipeline

    fill = Pipeline.__new__(Pipeline)._fill_from_vision
    read = {
        "is_handgame": True,
        "title": "Nespelem Celebration Stickgames",
        "start_date": "2026-07-09",
        "end_date": "2026-07-12",
        "location": "Nespelem, WA",
        "confidence": 0.95,
    }

    # The real failure: OCR's junk title and wrong date must both be replaced.
    ev = Event(title="ae a i om Lelebraliogse", start_date="2026-07-07",
               source="inbox", extraction="ocr")
    fill(ev, dict(read))
    check("the garbled title is replaced", ev.title, "Nespelem Celebration Stickgames")
    check("the misread date is corrected", ev.start_date, "2026-07-09")
    check_true("and the event is now on topic", topic_score(ev.title) >= 0.5)
    check_true("the date disagreement is reported, not hidden",
               any("flyer reader read 2026-07-09" in w for w in ev.warnings))
    check("a replaced title is no longer provisional", ev.title_provisional, False)

    # A person who typed the answer outranks any reader.
    typed = Event(title="38th Annual Labor Day Stickgame",
                  start_date="2026-09-05", location="Nespelem, WA",
                  source="inbox", extraction="ocr")
    typed._manual_fields = frozenset({"title", "start_date", "location"})
    fill(typed, dict(read))
    check("a sidecar title is never overruled",
          typed.title, "38th Annual Labor Day Stickgame")
    check("a sidecar date is never overruled", typed.start_date, "2026-09-05")
    check("and overruling nothing raises no warning", typed.warnings, [])

    # Agreement must not generate review noise.
    agree = Event(title="Nespelem Celebration Stickgames",
                  start_date="2026-07-09", source="inbox", extraction="ocr")
    fill(agree, dict(read))
    check("agreement is silent", agree.warnings, [])

    # Contact details are accumulated by the OCR pass; don't clobber them.
    kept = Event(title="x", start_date="2026-07-09", source="inbox",
                 details="Contact: Darnell Sam (509) 634-0772")
    fill(kept, dict(read, details="unrelated blurb"))
    check("existing details survive", kept.details,
          "Contact: Darnell Sam (509) 634-0772")

    # A reader that says this is not a handgame event still short-circuits.
    not_ours = Event(title="Canning Class", start_date="2026-08-25", source="inbox")
    fill(not_ours, {"is_handgame": False, "title": "Something Else"})
    check("is_handgame False still stops everything", not_ours.title, "Canning Class")

    # Malformed dates from the reader are still refused.
    bad = Event(title="x", start_date="2026-07-07", source="inbox")
    fill(bad, dict(read, start_date="July 9th 2026"))
    check("a non-ISO date from the reader is ignored", bad.start_date, "2026-07-07")

    # A machine-readable feed states the date; the reader is looking at a
    # picture of it. An image read must not overrule a feed.
    feed = Event(title="Fall Handgame Tournament", start_date="2026-10-17",
                 source="calendars", extraction="structured", confidence=0.92)
    fill(feed, dict(read, title="Reader Title", start_date="2026-10-19"))
    check("a feed date is not overruled by the reader", feed.start_date, "2026-10-17")
    check("nor is a feed title", feed.title, "Fall Handgame Tournament")
    check("but the reader still fills what the feed left empty",
          feed.location, "Nespelem, WA")


def test_mirroring_never_costs_us_an_event():
    """13. mirroring a flyer must not be able to break a publish.

    upload_flyer existed but nothing called it, so every published event
    linked to a flyer on somebody else's server. Those rot, and a calendar
    of broken images is worse than one with none.

    Wiring it in adds a network call to the publish path, so the rules are:
    a failure keeps the original URL rather than losing the event, the same
    event always maps to the same object name, and a repeat upload is a
    success — the publishable key can write to the bucket but cannot delete,
    so there is no cleaning up after a needless re-upload.
    """
    print("\n13. a flyer that will not mirror never costs us the event")
    import run

    class FakeSB:
        url = "https://x.supabase.co"

        def __init__(self, ok=True):
            self.ok, self.calls = ok, []

        def upload_flyer(self, data, name, content_type="image/jpeg"):
            self.calls.append(name)
            return f"{self.url}/storage/v1/object/public/event-flyers/{name}" if self.ok else None

    class FakeFetch:
        def __init__(self, data=b"IMG"):
            self.data = data

        def get_image(self, url, **kw):
            return self.data

    def ev(flyer):
        return Event(title="Fall Handgame Tournament", start_date="2026-10-17",
                     location="Keller, WA", flyer_url=flyer).tidy()

    remote = ev("https://other.example/flyers/a.JPG")
    sb = FakeSB()
    out = run.mirror_flyer(sb, FakeFetch(), remote)
    check_true("a remote flyer is mirrored", out and "event-flyers" in out)
    check_true("the object keeps the image extension", sb.calls[0].endswith(".jpg"))

    check("a local file is not uploaded",
          run.mirror_flyer(FakeSB(), FakeFetch(), ev("local:///tmp/x.jpg")), None)
    check("an event with no flyer is skipped",
          run.mirror_flyer(FakeSB(), FakeFetch(), ev(None)), None)
    check("a flyer already in our bucket is not re-uploaded",
          run.mirror_flyer(FakeSB(), FakeFetch(),
                           ev("https://x.supabase.co/storage/v1/object/public/event-flyers/z.jpg")),
          None)
    check("a non-image url is left alone",
          run.mirror_flyer(FakeSB(), FakeFetch(), ev("https://other.example/a.pdf")), None)

    # The important one: a failed upload must not lose the flyer or the event.
    keep = ev("https://other.example/a.jpg")
    check("a failed upload returns nothing",
          run.mirror_flyer(FakeSB(ok=False), FakeFetch(), keep), None)
    check("and the original url is untouched",
          keep.flyer_url, "https://other.example/a.jpg")

    # Same event twice must not create a second object; the key cannot delete.
    one, two = ev("https://o.example/a.jpg"), ev("https://o.example/a.jpg")
    a, b = FakeSB(), FakeSB()
    run.mirror_flyer(a, FakeFetch(), one)
    run.mirror_flyer(b, FakeFetch(), two)
    check("re-publishing maps to the same object", a.calls[0], b.calls[0])


def test_a_rate_limiting_host_is_dropped_not_retried():
    """14. a host that 429s everything must not be retried per URL.

    A scheduled run comes from a datacenter address and is treated very
    differently from a laptop. On 2026-08-13 every single request to
    calendar.powwows.com returned 429 from a GitHub runner while the same
    URLs returned 200 locally. Retries are per URL, so the run worked
    through the list burning three attempts and two backoffs on each,
    spent about four minutes on it, and collected 14 candidates where a
    local run collected 54.

    Retrying cannot help when a host is refusing everything. After three
    refusals the host is dropped for the rest of the run.
    """
    print("\n14. a host that rate limits us is dropped, not retried per URL")
    from handgame_scraper.fetch import Fetcher, RATE_LIMIT_GIVE_UP

    class Resp:
        def __init__(self, code, headers=None):
            self.status_code = code
            self.headers = headers or {}
            self.text = ""
            self.content = b""

    class Seq:
        """Serves a scripted sequence of status codes, counting real calls."""

        def __init__(self, codes):
            self.codes = list(codes)
            self.calls = 0

        def get(self, url, **kw):
            if url.endswith("/robots.txt"):
                return Resp(404)
            code = self.codes[min(self.calls, len(self.codes) - 1)]
            self.calls += 1
            return Resp(code)

    def fetcher(codes):
        f = Fetcher(cache_dir=None, delay=0.0)
        f.session = Seq(codes)
        return f

    # Eight URLs on a host that refuses everything: three calls, not 24.
    f = fetcher([429])
    for i in range(8):
        check("every request returns nothing", f.get(f"https://t.example/{i}"), None)
    check("it stopped after the give-up threshold", f.session.calls, RATE_LIMIT_GIVE_UP)
    check_true("and the host is marked for the rest of the run",
               "t.example" in f._rate_limited)

    # Below the threshold it recovers, because one 429 is not a rate limit.
    f2 = fetcher([429, 200])
    check_true("one 429 then success still returns the page",
               f2.get("https://blip.example/a") is not None)
    check("the refusal count is cleared on success",
          f2._host_429.get("blip.example"), None)
    check("and the host is not dropped", "blip.example" in f2._rate_limited, False)

    # One host misbehaving must not affect another.
    f3 = fetcher([429])
    for i in range(4):
        f3.get(f"https://bad.example/{i}")
    f3.session.codes = [200]
    check_true("a different host is still fetched",
               f3.get("https://good.example/ok") is not None)

    # Retry-After is honoured, but must not park a run for an hour.
    f4 = fetcher([429])
    check("an hour-long Retry-After is capped",
          f4._note_rate_limit("h.example", "3600"), 60.0)
    check_true("a malformed Retry-After does not raise",
               f4._note_rate_limit("h2.example", "soon") is not None)

    # Server errors are a different thing and still get their retries.
    f5 = fetcher([500])
    f5.get("https://slow.example/x")
    check("a 500 still retries", f5.session.calls, 3)


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
        test_hint_cannot_supply_the_keyword,
        test_weekday_contradicts_the_date,
        test_ocr_does_not_outrank_the_flyer_reader,
        test_mirroring_never_costs_us_an_event,
        test_a_rate_limiting_host_is_dropped_not_retried,
    ]:
        fn()
    print(f"\n  {PASS} passed, {FAIL} failed\n")
    for failure in FAILURES:
        print(f"  FAIL  {failure}")
    sys.exit(1 if FAIL else 0)
