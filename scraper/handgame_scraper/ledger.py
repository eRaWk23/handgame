"""The 'have we seen this before' memory.

Every candidate the pipeline has ever emitted is recorded here, whether it was
eventually approved or rejected. That is the point: a flyer you rejected in
March must not reappear in April's queue.

The ledger is a plain JSON file committed to the repo, so its whole history is
visible in git and it needs no database.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("ledger at %s is unreadable (%s); starting empty", self.path, exc)
            return
        if isinstance(data, dict):
            self.entries = data.get("entries", {})
        log.info("ledger loaded: %d known items", len(self.entries))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA_VERSION,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "entries": self.entries,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        log.info("ledger saved: %d known items", len(self.entries))

    # ------------------------------------------------------------------
    def seen(self, fingerprint: str) -> bool:
        return fingerprint in self.entries

    def phash_seen(self, phash: Optional[str], max_distance: int = 12) -> Optional[str]:
        """Return the fingerprint of a near-identical flyer image, if any."""
        if not phash:
            return None
        for fp, entry in self.entries.items():
            other = entry.get("phash")
            if not other or len(other) != len(phash):
                continue
            if _hex_hamming(phash, other) <= max_distance:
                return fp
        return None

    def match_key_seen(self, key: str) -> Optional[str]:
        if not key or key.startswith("|") or key.endswith("|"):
            return None
        for fp, entry in self.entries.items():
            if entry.get("match_key") == key:
                return fp
        return None

    def record(
        self,
        fingerprint: str,
        *,
        title: str = "",
        start_date: Optional[str] = None,
        match_key: str = "",
        phash: Optional[str] = None,
        source: str = "",
        source_url: Optional[str] = None,
        outcome: str = "queued",
    ) -> None:
        existing = self.entries.get(fingerprint, {})
        self.entries[fingerprint] = {
            "title": title or existing.get("title", ""),
            "start_date": start_date or existing.get("start_date"),
            "match_key": match_key or existing.get("match_key", ""),
            "phash": phash or existing.get("phash"),
            "source": source or existing.get("source", ""),
            "source_url": source_url or existing.get("source_url"),
            "outcome": outcome,
            "first_seen": existing.get(
                "first_seen", datetime.now().isoformat(timespec="seconds")
            ),
            "last_seen": datetime.now().isoformat(timespec="seconds"),
        }

    def forget(self, fingerprints: Iterable[str]) -> int:
        removed = 0
        for fp in fingerprints:
            if self.entries.pop(fp, None) is not None:
                removed += 1
        return removed

    def prune(self, keep_days: int = 900) -> int:
        """Drop entries for events that ended long ago, to keep the file small."""
        cutoff = date.today() - timedelta(days=keep_days)
        drop = []
        for fp, entry in self.entries.items():
            sd = entry.get("start_date")
            if not sd:
                continue
            try:
                if datetime.strptime(sd, "%Y-%m-%d").date() < cutoff:
                    drop.append(fp)
            except (ValueError, TypeError):
                continue
        for fp in drop:
            del self.entries[fp]
        return len(drop)


def _hex_hamming(a: str, b: str) -> int:
    """Bitwise distance between two hex-encoded hashes."""
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 999
