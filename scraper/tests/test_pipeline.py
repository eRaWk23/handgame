"""End-to-end test: a flyer image on disk becomes a reviewable event, and a
second run of the same thing produces nothing.

Run:  python3 tests/test_pipeline.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handgame_scraper.models import Event  # noqa: E402
from handgame_scraper.pipeline import Pipeline  # noqa: E402
from handgame_scraper.review import build_review_page  # noqa: E402
from handgame_scraper import supabase as sb_module  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "flyer_sample.jpg"

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


class FakeSupabase:
    """Stands in for the live site during tests."""

    def __init__(self, events=None):
        self._events = events or []
        self.configured = True

    def fetch_events(self, limit: int = 2000):
        return self._events


def build_config(workdir: Path) -> dict:
    return {
        "settings": {
            "request_delay_seconds": 0,
            "respect_robots": False,
            "cache_dir": str(workdir / ".cache"),
            "output_dir": str(workdir / "out"),
            "ledger_path": str(workdir / "state" / "seen.json"),
            "min_topic_score": 0.5,
            "use_vision_ocr": False,
        },
        "sources": {
            "inbox": {"enabled": True, "path": str(workdir / "inbox")},
            "calendars": {"enabled": False},
            "webpages": {"enabled": False},
            "reddit": {"enabled": False},
            "websearch": {"enabled": False},
        },
    }


def main() -> int:
    if not FIXTURE.exists():
        print(f"  missing fixture {FIXTURE}; generate it first")
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="hg-test-"))
    try:
        inbox = workdir / "inbox"
        inbox.mkdir(parents=True)
        shutil.copy(FIXTURE, inbox / "labor_day_flyer.jpg")

        config = build_config(workdir)

        # ---------------- run 1: a flyer with nothing known about it ------
        print("\nrun 1 - fresh flyer, empty site")
        pipeline = Pipeline(config, workdir)
        pipeline.supabase = FakeSupabase([])
        result = pipeline.run()
        events = result["events"]

        check("one event queued", len(events), 1)
        if events:
            ev = events[0]
            check("date read off the flyer", ev["start_date"], "2026-09-04")
            check("end date read off the flyer", ev["end_date"], "2026-09-06")
            check("location read off the flyer", ev["location"], "Nespelem, Washington")
            check("tribe read off the flyer", ev["tribe"], "Colville")
            check_true("title mentions the game", "GAME" in ev["title"].upper())
            check_true("phone kept in details", "509-555-0142" in (ev["details"] or ""))
            check_true("flyer hashed", ev["flyer_phash"])
            check_true("confidence is high", ev["confidence"] >= 0.7)
            check("no warnings on a clean read", ev["warnings"], [])

        # ---------------- run 2: nothing has changed ---------------------
        print("\nrun 2 - same flyer, same folder")
        pipeline2 = Pipeline(config, workdir)
        pipeline2.supabase = FakeSupabase([])
        result2 = pipeline2.run()
        check("nothing queued the second time", len(result2["events"]), 0)
        check("and it says why", result2["stats"]["skipped_seen_in_previous_runs"], 1)

        # ------- run 3: same event already on the site, ledger cleared ----
        print("\nrun 3 - ledger cleared, but the event is already on the site")
        (workdir / "state" / "seen.json").unlink()
        live = [
            Event(
                title="38th Annual Labor Day Handgame Tourney",
                start_date="2026-09-04",
                location="Nespelem, WA",
                source="live-site",
            ).tidy()
        ]
        pipeline3 = Pipeline(config, workdir)
        pipeline3.supabase = FakeSupabase(live)
        result3 = pipeline3.run()
        check("recognised as already published", len(result3["events"]), 0)
        check("counted as a live duplicate", result3["stats"]["skipped_already_on_site"], 1)

        # ------- run 4: a genuinely different event is not blocked --------
        print("\nrun 4 - a different tournament, same weekend, other state")
        (workdir / "state" / "seen.json").unlink()
        live_elsewhere = [
            Event(
                title="Handgame Tournament",
                start_date="2026-09-04",
                location="Fort Hall, ID",
                source="live-site",
            ).tidy()
        ]
        pipeline4 = Pipeline(config, workdir)
        pipeline4.supabase = FakeSupabase(live_elsewhere)
        result4 = pipeline4.run()
        check("different state still gets queued", len(result4["events"]), 1)

        # ---------------- review page -------------------------------------
        print("\nreview page")
        review_path = workdir / "out" / "review.html"
        build_review_page(result, review_path)
        html = review_path.read_text(encoding="utf-8")
        check_true("page written", review_path.exists())
        check_true("data inlined", '"start_date"' in html)
        check_true("no placeholder left", "__DATA__" not in html and "__GENERATED__" not in html)
        check_true("self contained", "<script>" in html and "src=" not in html.split("<script>")[0])
        check_true("approve control present", "Approve" in html)
        check_true("no browser storage used",
                   "localStorage" not in html and "sessionStorage" not in html)

        # ---------------- inbox sidecar note ------------------------------
        print("\ninbox sidecar note")
        (workdir / "state" / "seen.json").unlink()
        shutil.copy(FIXTURE, inbox / "second_flyer.jpg")
        (inbox / "second_flyer.txt").write_text(
            "title: Fall Classic Handgame Tournament\n"
            "location: Omak, WA\n"
            "tribe: Colville\n"
            "date: October 17 2026\n"
            "url: https://example.org/post/99\n",
            encoding="utf-8",
        )
        pipeline5 = Pipeline(config, workdir)
        pipeline5.supabase = FakeSupabase([])
        result5 = pipeline5.run()
        titles = {e["title"] for e in result5["events"]}
        check_true("sidecar note is used", "Fall Classic Handgame Tournament" in titles)
        noted = [e for e in result5["events"] if e["title"] == "Fall Classic Handgame Tournament"]
        if noted:
            check("sidecar date wins over the flyer", noted[0]["start_date"], "2026-10-17")
            check("sidecar url kept", noted[0]["source_url"], "https://example.org/post/99")
        check("both flyers queued", len(result5["events"]), 2)
        if noted:
            check_true(
                "reused artwork with a new date is flagged, not silently dropped",
                any("same flyer image" in w for w in noted[0]["warnings"]),
            )

        print(f"\n  {PASS} passed, {FAIL} failed\n")
        for failure in FAILURES:
            print(f"  FAIL  {failure}")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
