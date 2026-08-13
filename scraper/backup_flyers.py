#!/usr/bin/env python3
"""Copy every flyer out of Supabase Storage and into the repo.

Supabase Storage has no undo. Database backups do not cover storage objects —
they carry only the metadata rows — and point-in-time recovery restores the
database, not the files. A flyer deleted from the bucket is gone, and on
2026-08-12 nineteen of them went that way in one click.

Git is the opposite: additive, versioned, and a deletion is always one
`git checkout` from coming back. So this walks the bucket and writes anything
missing into `flyers/`, then records what it saw in `flyers/manifest.json`.

Two rules make it a backup rather than a mirror:

  * It never deletes a local file. An object that disappears from the bucket
    stays here and is marked `in_bucket: false` in the manifest. That is the
    entire point — if it deleted alongside the bucket it would have propagated
    the accident instead of surviving it.
  * It never uploads. This process only ever reads from Supabase.

Run it from the repo root, or anywhere with SUPABASE_URL and
SUPABASE_ANON_KEY set:

    python3 scraper/backup_flyers.py
    python3 scraper/backup_flyers.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BUCKET = "event-flyers"
DEFAULT_URL = "https://atorftwulkabkmhaeeir.supabase.co"
#: Repo root, whichever directory this is invoked from.
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "flyers"
MANIFEST = DEST / "manifest.json"
TIMEOUT = 120


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_objects(url: str, key: str) -> list[dict]:
    """Every object in the bucket. Paginated: the API caps a page at 100."""
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    out: list[dict] = []
    offset = 0
    while True:
        resp = requests.post(
            f"{url}/storage/v1/object/list/{BUCKET}",
            headers=headers,
            json={"prefix": "", "limit": 100, "offset": offset},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            raise SystemExit(f"could not list {BUCKET}: {resp.status_code} {resp.text[:200]}")
        page = resp.json()
        if not page:
            break
        out.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    # A placeholder row with no id shows up in empty folders; it is not a file.
    return [o for o in out if o.get("id")]


def download(url: str, name: str) -> bytes | None:
    resp = requests.get(f"{url}/storage/v1/object/public/{BUCKET}/{name}", timeout=TIMEOUT)
    if resp.status_code >= 400:
        print(f"  FAILED   {name}: HTTP {resp.status_code}")
        return None
    return resp.content


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    url = (os.environ.get("SUPABASE_URL") or DEFAULT_URL).rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY") or ""
    if not key:
        raise SystemExit("SUPABASE_ANON_KEY is not set")

    DEST.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8")).get("objects", {})
        except (ValueError, OSError):
            manifest = {}

    objects = list_objects(url, key)
    live = {o["name"] for o in objects}
    print(f"  {len(objects)} object(s) in {BUCKET}")

    added = skipped = failed = 0
    for obj in objects:
        name = obj["name"]
        size = (obj.get("metadata") or {}).get("size")
        target = DEST / name
        # Same name and same size means we already hold this exact object.
        if target.exists() and (size is None or target.stat().st_size == size):
            skipped += 1
            manifest.setdefault(name, {"first_backed_up": _now()})
            manifest[name].update({"size": size, "in_bucket": True, "last_seen": _now()})
            continue
        if args.dry_run:
            print(f"  would copy  {name} ({size} bytes)")
            added += 1
            continue
        blob = download(url, name)
        if blob is None:
            failed += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        print(f"  backed up   {name} ({len(blob)} bytes)")
        added += 1
        manifest.setdefault(name, {"first_backed_up": _now()})
        manifest[name].update({"size": len(blob), "in_bucket": True, "last_seen": _now()})

    # Anything we hold that is no longer in the bucket stays on disk. Recording
    # it is how a deletion becomes visible instead of silent.
    vanished = [n for n in manifest if n not in live and manifest[n].get("in_bucket") is not False]
    for name in vanished:
        manifest[name]["in_bucket"] = False
        manifest[name]["gone_since"] = _now()
        print(f"  GONE from bucket, kept here: {name}")

    if not args.dry_run:
        MANIFEST.write_text(
            json.dumps(
                {"bucket": BUCKET, "updated": _now(), "objects": dict(sorted(manifest.items()))},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    held = len([p for p in DEST.iterdir() if p.is_file() and p.name != "manifest.json"])
    print(
        f"\n  {added} newly backed up, {skipped} already held, {failed} failed, "
        f"{len(vanished)} newly missing from the bucket"
    )
    print(f"  {held} flyer(s) now safe in {DEST.relative_to(ROOT)}/\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
