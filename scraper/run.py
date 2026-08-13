#!/usr/bin/env python3
"""Command line entry point for the handgame.info event collector.

  python run.py scrape                    collect, dedupe, build the review queue
  python run.py scrape --only calendars   run one source
  python run.py scrape --dry-run          change nothing on disk
  python run.py publish approved.json     push reviewed events to Supabase
  python run.py status                    what the ledger knows
  python run.py forget <fingerprint>...   let an item be collected again
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from handgame_scraper.fetch import Fetcher  # noqa: E402
from handgame_scraper.ledger import Ledger  # noqa: E402
from handgame_scraper.models import Event  # noqa: E402
from handgame_scraper.pipeline import Pipeline  # noqa: E402
from handgame_scraper.review import build_review_page  # noqa: E402
from handgame_scraper.supabase import Supabase, SupabaseError  # noqa: E402


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no config file at {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)-22s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ----------------------------------------------------------------------
def cmd_scrape(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    pipeline = Pipeline(config, ROOT)
    result = pipeline.run(only=args.only, dry_run=args.dry_run)

    out_dir = ROOT / config.get("settings", {}).get("output_dir", "out")
    out_dir.mkdir(parents=True, exist_ok=True)

    pending_path = out_dir / "pending.json"
    review_path = out_dir / "review.html"

    if not args.dry_run:
        pending_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        build_review_page(result, review_path)

    stats = result["stats"]
    print("\n" + "=" * 62)
    print(f"  {stats['queued_for_review']} events waiting for review")
    print("=" * 62)
    for key, value in stats.items():
        if key == "per_source":
            continue
        print(f"  {key.replace('_', ' '):<38} {value}")
    if stats["per_source"]:
        print("  found per source:")
        for name, count in stats["per_source"].items():
            print(f"      {name:<22} {count}")
    print()

    for ev in result["events"][:12]:
        flag = " ⚠" if ev.get("warnings") else ""
        print(f"  {ev.get('start_date','?')}  {ev.get('title','')[:52]:<52}{flag}")
    if len(result["events"]) > 12:
        print(f"  ... and {len(result['events']) - 12} more")

    if args.dry_run:
        print("\n  dry run: nothing written\n")
    else:
        print(f"\n  review queue:  {review_path}")
        print(f"  raw data:      {pending_path}\n")
    return 0


#: Extension -> content type for flyers we mirror. Anything else is left on
#: whatever server it came from rather than guessing at its type.
_FLYER_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
}


def mirror_flyer(supabase: Supabase, fetcher, event: Event) -> Optional[str]:
    """Copy an event's flyer into our own bucket and return the new URL.

    Flyers linked on someone else's server rot, and a calendar of broken
    images is worse than a calendar with none. Returns None when there is
    nothing to do or the copy failed — the caller keeps the original URL,
    because a flyer that is merely at risk beats no event at all.
    """
    url = event.flyer_url
    if not url or url.startswith("local://"):
        return None
    if supabase.url and url.startswith(f"{supabase.url}/storage/"):
        return None  # already ours; mirroring it again would be a no-op
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    content_type = _FLYER_TYPES.get(suffix)
    if not content_type:
        return None
    image = fetcher.get_image(url)
    if not image:
        return None
    # Fingerprint-derived so the same event always maps to the same object,
    # which is what makes a re-publish idempotent.
    return supabase.upload_flyer(
        image, f"{event.fingerprint}{suffix}", content_type=content_type
    )


def cmd_publish(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        rows = rows.get("events", [])

    supabase = Supabase()
    if not supabase.configured:
        raise SystemExit("set SUPABASE_URL and SUPABASE_ANON_KEY first")

    fetcher = Fetcher(cache_dir=None)
    added = failed = mirrored = 0
    for row in rows:
        event = Event.from_dict(row)
        try:
            # Before inserting, not after: if mirroring throws, the event has
            # not been published yet and re-running the file is still safe.
            if not args.no_mirror:
                try:
                    hosted = mirror_flyer(supabase, fetcher, event)
                    if hosted:
                        event.flyer_url = hosted
                        mirrored += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"  note    flyer not mirrored ({exc}); keeping original")
            supabase.insert_event(event)
            added += 1
            print(f"  added   {event.start_date}  {event.title}")
        except Exception as exc:  # noqa: BLE001
            # Never abort partway through: a half-published file leaves the
            # user unable to safely re-run it without double-inserting.
            failed += 1
            print(f"  FAILED  {event.title}: {exc}")
    note = f", {mirrored} flyer(s) mirrored" if mirrored else ""
    print(f"\n  {added} added, {failed} failed{note}\n")
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    ledger = Ledger(ROOT / config.get("settings", {}).get("ledger_path", "state/seen.json"))
    print(f"\n  ledger: {ledger.path}")
    print(f"  {len(ledger.entries)} items remembered\n")
    outcomes: dict[str, int] = {}
    for entry in ledger.entries.values():
        outcomes[entry.get("outcome", "?")] = outcomes.get(entry.get("outcome", "?"), 0) + 1
    for name, count in sorted(outcomes.items(), key=lambda kv: -kv[1]):
        print(f"    {name:<22} {count}")
    recent = sorted(
        ledger.entries.items(), key=lambda kv: kv[1].get("last_seen", ""), reverse=True
    )[:15]
    print("\n  most recent:")
    for fp, entry in recent:
        print(f"    {fp}  {entry.get('start_date','?')}  {entry.get('title','')[:44]}")
    print()
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    ledger = Ledger(ROOT / config.get("settings", {}).get("ledger_path", "state/seen.json"))
    removed = ledger.forget(args.fingerprints)
    ledger.save()
    print(f"  forgot {removed} item(s); they can be collected again next run")
    return 0


# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run.py", description="handgame.info event collector"
    )
    parser.add_argument("-c", "--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="collect events and build the review queue")
    p_scrape.add_argument("--only", nargs="*", help="limit to these source names")
    p_scrape.add_argument("--dry-run", action="store_true")
    p_scrape.set_defaults(func=cmd_scrape)

    p_pub = sub.add_parser("publish", help="insert reviewed events into Supabase")
    p_pub.add_argument("file", help="approved.json from the review page")
    p_pub.add_argument(
        "--no-mirror",
        action="store_true",
        help="keep flyer_url pointing at the original host",
    )
    p_pub.set_defaults(func=cmd_publish)

    p_status = sub.add_parser("status", help="show what the ledger remembers")
    p_status.set_defaults(func=cmd_status)

    p_forget = sub.add_parser("forget", help="remove items from the ledger")
    p_forget.add_argument("fingerprints", nargs="+")
    p_forget.set_defaults(func=cmd_forget)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
