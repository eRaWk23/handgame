"""Tests for the parts that would quietly corrupt the calendar if wrong.

Run:  python3 tests/test_core.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handgame_scraper import dedupe
from handgame_scraper.extract import (
    find_contact, find_dates, find_location, find_tribe, guess_title, topic_score,
)
from handgame_scraper.ledger import Ledger
from handgame_scraper.models import Event, normalize_key

PASS = FAIL = 0
FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label}\n      got:  {got!r}\n      want: {want!r}")


def check_true(label: str, got) -> None:
    check(label, bool(got), True)


TODAY = date(2026, 8, 12)


# ---------------------------------------------------------------- dates
def test_dates() -> None:
    cases = [
        ("SEPTEMBER 12-14, 2026", "2026-09-12", "2026-09-14"),
        ("Sept 12th - 14th, 2026", "2026-09-12", "2026-09-14"),
        ("September 12, 2026", "2026-09-12", None),
        ("AUGUST 29 - SEPTEMBER 1, 2026", "2026-08-29", "2026-09-01"),
        ("12 September 2026", "2026-09-12", None),
        ("9/12/2026", "2026-09-12", None),
        ("2026-09-12", "2026-09-12", None),
        # A flyer with no year means the next occurrence.
        ("LABOR DAY WEEKEND - SEPT 5 & 6", "2026-09-05", "2026-09-06"),
        # December from an August run must roll to this year, not next.
        ("December 5, 2026", "2026-12-05", None),
        # A month already past rolls forward a year.
        ("March 14", "2027-03-14", None),
        # Times must not be read as dates.
        ("Doors 5:00 PM · Games start 7:00 PM · October 3, 2026", "2026-10-03", None),
    ]
    for text, want_start, want_end in cases:
        start, end, _ = find_dates(text, today=TODAY)
        check(
            f"date {text!r}",
            (start.strftime("%Y-%m-%d") if start else None,
             end.strftime("%Y-%m-%d") if end else None),
            (want_start, want_end),
        )

    _, _, warnings = find_dates("July 4, 2019", today=TODAY)
    check_true("past date is flagged", any("past" in w for w in warnings))
    check("no date found", find_dates("come on down, prizes for all", today=TODAY)[0], None)


# ------------------------------------------------------------ locations
def test_locations() -> None:
    cases = [
        ("Held at Nespelem, WA on the powwow grounds", "Nespelem, Washington"),
        ("WELLPINIT, WASHINGTON", "Wellpinit, Washington"),
        ("Fort Hall, ID", "Fort Hall, Idaho"),
        ("at the Spokane Tribal Gym", "the Spokane Tribal Gym"),
        ("Kamloops, BC", "Kamloops, British Columbia"),
        # Regions the table missed until the first live run: real flyers from
        # California and Alberta parsed a clean date and no location at all.
        ("Big Time Handgame at Win-River Resort in Redding", "Redding, California"),
        ("Treaty Day Celebration in Goodfish Lake", "Goodfish Lake, Alberta"),
        ("Handgame at Ft Duchesne", "Fort Duchesne, Utah"),
        ("Stommish grounds, Lummi", "Lummi, Washington"),
        # A person's name must not be read as a town. Memorial tournaments are
        # common here, so single-token surnames are kept out of KNOWN_PLACES.
        ("Winston Sam Nixon Memorial Handgame Tournament", None),
        ("Sparks fly at the annual tournament", None),
    ]
    for text, want in cases:
        check(f"location {text!r}", find_location(text), want)

    check("tribe found", find_tribe("Hosted by the Colville Confederated Tribes"), "Colville")
    check("tribe absent", find_tribe("Hosted by the neighbourhood association"), None)


# ---------------------------------------------------------------- topic
def test_topic() -> None:
    check_true("handgame is on topic", topic_score("Annual Handgame Tournament") >= 0.7)
    check_true("stickgame is on topic", topic_score("STICK GAME TOURNEY, big payout") >= 0.7)
    check_true("slahal is on topic", topic_score("Slahal gathering and giveaway") >= 0.7)
    check("esports is not", topic_score("Fortnite video game tournament, $500 payout"), 0.0)
    check("empty is not", topic_score(""), 0.0)
    check_true(
        "handgame beats the video-game filter",
        topic_score("Handgame tournament, no video game consoles allowed") >= 0.7,
    )


# -------------------------------------------------------------- titling
def test_titles() -> None:
    flyer = """38TH ANNUAL
LABOR DAY HANDGAME TOURNAMENT
September 5-7, 2026
Nespelem, WA
Call Sherry 509-555-0142"""
    title = guess_title(flyer)
    check_true("title picks the handgame line", "HANDGAME" in title.upper())
    check("contact found", find_contact(flyer), "509-555-0142")


# ----------------------------------------------------------- normalizing
def test_normalize() -> None:
    check(
        "stickgame and handgame normalize the same",
        normalize_key("Stick Game Tourney"),
        normalize_key("Handgame Tournament"),
    )
    check_true(
        "bone game normalizes too",
        normalize_key("Bone Game") == normalize_key("hand game"),
    )
    e = Event(title="TEST EVENT NAME HERE", start_date="2026-09-05")
    check("shouting titles are softened", e.tidy().title, "Test Event Name Here")


# ----------------------------------------------------------------- dedupe
def test_dedupe() -> None:
    a = Event(
        title="Colville Labor Day Stickgame Tournament",
        start_date="2026-09-05", location="Nespelem, WA", source="webpages",
    ).tidy()
    b = Event(
        title="38th Annual Labor Day Hand Game Tourney",
        start_date="2026-09-05", location="Nespelem, Washington", source="reddit",
    ).tidy()
    score, _ = dedupe.similarity(a, b)
    check_true(f"same event, two write-ups (scored {score})", score >= dedupe.CERTAIN)

    c = Event(title="Handgame Tournament", start_date="2026-09-05",
              location="Fort Hall, ID").tidy()
    score2, _ = dedupe.similarity(a, c)
    check_true(f"same day, different state is not a dup ({score2})", score2 < dedupe.CERTAIN)

    d = Event(title="Colville Labor Day Stickgame Tournament",
              start_date="2027-09-04", location="Nespelem, WA").tidy()
    score3, _ = dedupe.similarity(a, d)
    check(f"next year's edition is not a dup ({score3})", score3, 0.0)

    e1 = Event(title="Flyer A", start_date="2026-10-01", location="Omak, WA",
               flyer_phash="ffff0000ffff0000")
    e2 = Event(title="Totally different words", start_date="2026-10-01",
               location="Omak, WA", flyer_phash="ffff0000ffff0000")
    score4, reasons = dedupe.similarity(e1, e2)
    check("identical flyer image is a certain dup", score4, 1.0)
    check("and says why", reasons, ["identical flyer image"])

    kept, merged = dedupe.deduplicate_batch([a, b, c])
    check("batch collapses the pair", (len(kept), merged), (2, 1))

    verdict, match, _, _ = dedupe.against_existing(b, [a])
    check("existing-event check flags the duplicate", verdict, "duplicate")
    verdict2, _, _, _ = dedupe.against_existing(c, [a])
    check("and lets a real new one through", verdict2, "new")


# -------------------------------------------------------- merge behaviour
def test_merge() -> None:
    thin = Event(title="Handgame Tournament", start_date="2026-09-05",
                 location="Nespelem, WA", source="reddit")
    rich = Event(title="38th Annual Labor Day Handgame Tournament",
                 start_date="2026-09-05", location="Nespelem, WA",
                 tribe="Colville", details="Entry $50", end_date="2026-09-07",
                 flyer_url="https://example.org/f.jpg", source="calendars")
    merged = dedupe.merge(thin, rich)
    check("merge takes the fuller title", merged.title, rich.title)
    check("merge fills the tribe", merged.tribe, "Colville")
    check("merge fills the flyer", merged.flyer_url, "https://example.org/f.jpg")
    check("merge fills the end date", merged.end_date, "2026-09-07")
    check_true("merge notes both sources", "calendars" in merged.source)


# ---------------------------------------------------------------- ledger
def test_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "seen.json"
        ledger = Ledger(path)
        ev = Event(title="Handgame Tournament", start_date="2026-09-05",
                   location="Nespelem, WA",
                   source_url="https://example.org/e/1").tidy()

        check("nothing known at first", ledger.seen(ev.fingerprint), False)
        ledger.record(ev.fingerprint, title=ev.title, start_date=ev.start_date,
                      match_key=ev.match_key, phash="aabbccdd", source_url=ev.source_url)
        ledger.save()

        reloaded = Ledger(path)
        check("survives a restart", reloaded.seen(ev.fingerprint), True)
        check("near-identical flyer is recognised",
              reloaded.phash_seen("aabbccdc"), ev.fingerprint)
        check("a different flyer is not", reloaded.phash_seen("00112233"), None)
        check("same day and place is recognised",
              reloaded.match_key_seen(ev.match_key), ev.fingerprint)

        # The same event from a different URL still gets caught by match_key.
        other = Event(title="Hand Game Tourney", start_date="2026-09-05",
                      location="Nespelem, Washington",
                      source_url="https://elsewhere.org/x").tidy()
        check("different URL, same event, still caught",
              reloaded.match_key_seen(other.match_key), ev.fingerprint)

        check("prune keeps future events", reloaded.prune(keep_days=900), 0)
        check("forget works", reloaded.forget([ev.fingerprint]), 1)


# ----------------------------------------------------------------- model
def test_model() -> None:
    ev = Event(title="Test", start_date="2026-09-05", location="Omak, WA")
    check("publishable when complete", ev.is_publishable(), True)
    check("not publishable without a date",
          Event(title="Test", location="Omak, WA").is_publishable(), False)
    check("future check", ev.is_future(today=date(2026, 8, 1)), True)
    check("past check", ev.is_future(today=date(2026, 10, 1)), False)
    check("multi-day event stays live on its last day",
          Event(title="T", start_date="2026-09-05", end_date="2026-09-07",
                location="X").is_future(today=date(2026, 9, 7)), True)

    bad = Event(title="T", start_date="2026-09-10", end_date="2026-09-01",
                location="X").tidy()
    check("backwards end date is dropped", bad.end_date, None)
    check_true("and flagged", any("end_date" in w for w in bad.warnings))

    row = ev.to_supabase_row()
    check("row matches the site's columns", sorted(row),
          ["details", "end_date", "flyer_url", "location", "start_date", "title", "tribe"])
    check("round trip", Event.from_dict(ev.to_dict()).title, "Test")


if __name__ == "__main__":
    for fn in [
        test_dates, test_locations, test_topic, test_titles, test_normalize,
        test_dedupe, test_merge, test_ledger, test_model,
    ]:
        fn()
    print(f"\n  {PASS} passed, {FAIL} failed\n")
    for failure in FAILURES:
        print(f"  FAIL  {failure}\n")
    sys.exit(1 if FAIL else 0)
