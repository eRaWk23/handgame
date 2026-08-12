"""The run itself: collect, enrich, dedupe, queue.

Order matters here. Enrichment happens before dedup because two sources often
carry the same flyer under different titles, and it is the flyer hash and the
OCR'd date that reveal they are the same event.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from . import dedupe
from .extract import find_contact, find_dates, find_location, find_tribe, guess_title, topic_score
from .fetch import Fetcher
from .ledger import Ledger
from .models import Event
from .ocr import ocr_text, perceptual_hash, vision_extract
from .sources import REGISTRY, safe_collect
from .supabase import Supabase

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    collected: int = 0
    off_topic: int = 0
    past: int = 0
    incomplete: int = 0
    batch_duplicates: int = 0
    already_seen: int = 0
    already_live: int = 0
    community_flagged: int = 0
    queued: int = 0
    needs_check: int = 0
    per_source: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "collected": self.collected,
            "rejected_off_topic": self.off_topic,
            "rejected_past_dates": self.past,
            "rejected_incomplete": self.incomplete,
            "merged_duplicates_in_batch": self.batch_duplicates,
            "skipped_seen_in_previous_runs": self.already_seen,
            "skipped_already_on_site": self.already_live,
            "skipped_flagged_by_community": self.community_flagged,
            "queued_for_review": self.queued,
            "queued_needing_extra_check": self.needs_check,
            "per_source": self.per_source,
        }


class Pipeline:
    def __init__(self, config: dict[str, Any], root: Path) -> None:
        self.config = config
        self.root = root
        settings = config.get("settings", {})

        self.fetcher = Fetcher(
            cache_dir=root / settings.get("cache_dir", ".cache"),
            delay=float(settings.get("request_delay_seconds", 2.0)),
            respect_robots=bool(settings.get("respect_robots", True)),
            cache_ttl_hours=int(settings.get("cache_ttl_hours", 12)),
        )
        self.ledger = Ledger(root / settings.get("ledger_path", "state/seen.json"))
        self.supabase = Supabase()
        self.use_vision = bool(settings.get("use_vision_ocr", True)) and bool(
            os.environ.get("ANTHROPIC_API_KEY")
        )
        self.min_topic = float(settings.get("min_topic_score", 0.5))
        self.max_flyers = int(settings.get("max_flyers_per_run", 120))
        self.stats = RunStats()
        self._flyer_budget = self.max_flyers

    # ==================================================================
    def run(self, only: Optional[list[str]] = None, dry_run: bool = False) -> dict[str, Any]:
        candidates = self._collect(only)
        self.stats.collected = len(candidates)

        enriched = [self._enrich(ev) for ev in candidates]
        kept = self._filter(enriched)

        kept, merged = dedupe.deduplicate_batch(kept)
        self.stats.batch_duplicates = merged

        fresh = self._drop_seen(kept)
        queued = self._compare_to_live(fresh)

        queued.sort(key=lambda e: (e.start_date or "9999", -e.confidence))
        self.stats.queued = len(queued)
        self.stats.needs_check = sum(1 for e in queued if e.warnings)

        if not dry_run:
            self._record(queued)
            self.ledger.prune()
            self.ledger.save()

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "stats": self.stats.as_dict(),
            "events": [e.to_dict() for e in queued],
        }

    # ==================================================================
    def _collect(self, only: Optional[list[str]]) -> list[Event]:
        out: list[Event] = []
        for name, cls in REGISTRY.items():
            block = (self.config.get("sources") or {}).get(name) or {}
            enabled = block.get("enabled", cls.enabled_by_default)
            if only and name not in only:
                continue
            if not only and not enabled:
                log.info("source %s disabled in config", name)
                continue
            source = cls(self.fetcher, block)
            found = safe_collect(source)
            self.stats.per_source[name] = len(found)
            out.extend(found)
        return out

    # ==================================================================
    def _enrich(self, event: Event) -> Event:
        """Read the flyer and fill in whatever the source could not."""
        image_bytes = self._flyer_bytes(event)
        if image_bytes:
            event.flyer_phash = perceptual_hash(image_bytes)

            text = ocr_text(image_bytes)
            if text:
                event.raw_text = ((event.raw_text or "") + "\n" + text).strip()[:4000]
                self._fill_from_text(event, text, extraction="ocr")

            if self.use_vision and self._needs_vision(event):
                data = vision_extract(image_bytes)
                if data:
                    self._fill_from_vision(event, data)

        # Last resort: whatever text the source already gave us.
        if event.raw_text:
            self._fill_from_text(event, event.raw_text, extraction=event.extraction)

        event.confidence = self._score(event)
        return event.tidy()

    def _flyer_bytes(self, event: Event) -> Optional[bytes]:
        local = getattr(event, "_local_bytes", None)
        if local:
            return local
        if not event.flyer_url or event.flyer_url.startswith("local://"):
            return None
        if self._flyer_budget <= 0:
            event.warnings.append("flyer not read: per-run download budget spent")
            return None
        self._flyer_budget -= 1
        return self.fetcher.get_image(event.flyer_url)

    @staticmethod
    def _needs_vision(event: Event) -> bool:
        """Only spend an API call when cheap extraction fell short."""
        return not (event.start_date and event.location and event.title)

    def _fill_from_text(self, event: Event, text: str, extraction: str) -> None:
        if not event.start_date:
            start, end, warnings = find_dates(text)
            if start:
                event.start_date = start.strftime("%Y-%m-%d")
                event.end_date = end.strftime("%Y-%m-%d") if end else event.end_date
                event.extraction = extraction
                event.warnings.extend(warnings)
        if not event.location:
            event.location = find_location(text)
        if not event.tribe:
            event.tribe = find_tribe(text)
        # A filename is a worse title than anything printed on the flyer.
        if not event.title or event.title_provisional:
            better = guess_title(text)
            if better:
                event.title = better
                event.title_provisional = False
        # Add only contact details that are not already there. Comparing the
        # whole joined string missed partial overlaps and published the same
        # phone number twice, because this runs once on the OCR text and again
        # on raw_text, which by then contains that same OCR text.
        contact = find_contact(text)
        if contact:
            existing = event.details or ""
            new_bits = [
                bit.strip()
                for bit in contact.split(",")
                if bit.strip() and bit.strip() not in existing
            ]
            if new_bits:
                joined = ", ".join(new_bits)
                event.details = f"{existing} · {joined}" if existing else joined

    def _fill_from_vision(self, event: Event, data: dict[str, Any]) -> None:
        if data.get("is_handgame") is False:
            event.warnings.append("flyer reader says this is not a handgame event")
            return
        mapping = {
            "title": "title",
            "start_date": "start_date",
            "end_date": "end_date",
            "location": "location",
            "tribe": "tribe",
            "details": "details",
        }
        changed = False
        for src_key, attr in mapping.items():
            value = data.get(src_key)
            if value and not getattr(event, attr):
                if attr in ("start_date", "end_date"):
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
                        continue
                setattr(event, attr, str(value))
                changed = True
        if changed:
            event.extraction = "llm"
        if data.get("year_printed") is False:
            event.warnings.append("year was not printed on the flyer; it was inferred")
        try:
            event.confidence = max(event.confidence, float(data.get("confidence", 0)))
        except (TypeError, ValueError):
            pass

    def _score(self, event: Event) -> float:
        """Confidence the reviewer can sort by."""
        score = 0.0
        if event.start_date:
            score += 0.35
        if event.location:
            score += 0.2
        if event.title:
            score += 0.1
        if event.flyer_url:
            score += 0.1
        if event.tribe:
            score += 0.05
        score += 0.2 * topic_score(event.title, event.details, event.raw_text)
        # Structured feeds print their dates; OCR guesses at them.
        if event.extraction == "structured":
            score += 0.05
        elif event.extraction == "ocr":
            score -= 0.05
        score -= 0.07 * len(event.warnings)
        return round(max(0.0, min(1.0, score)), 2)

    # ==================================================================
    def _filter(self, events: list[Event]) -> list[Event]:
        kept: list[Event] = []
        for ev in events:
            if topic_score(ev.title, ev.details, ev.raw_text) < self.min_topic:
                self.stats.off_topic += 1
                continue
            if not ev.is_publishable():
                self.stats.incomplete += 1
                log.debug("incomplete: %r (%s)", ev.title, ev.source_url)
                continue
            if not ev.is_future():
                self.stats.past += 1
                continue
            kept.append(ev)
        return kept

    # ==================================================================
    def _drop_seen(self, events: list[Event]) -> list[Event]:
        fresh: list[Event] = []
        for ev in events:
            if self.ledger.seen(ev.fingerprint):
                self.stats.already_seen += 1
                continue
            twin = self.ledger.phash_seen(ev.flyer_phash)
            if twin:
                # An identical image usually means an identical event, but a
                # host reusing last year's artwork with a new date is common
                # enough that the date gets the final say.
                known = self.ledger.entries.get(twin, {})
                known_date = known.get("start_date")
                if known_date and ev.start_date and known_date != ev.start_date:
                    ev.warnings.append(
                        f"same flyer image as an item already reviewed for "
                        f"{known_date}, but this one reads as {ev.start_date} - "
                        f"check which date is right"
                    )
                else:
                    self.stats.already_seen += 1
                    log.info("same flyer image as a previously queued item: %r", ev.title)
                    continue
            if self.ledger.match_key_seen(ev.match_key):
                self.stats.already_seen += 1
                log.info("same date and place as a previously queued item: %r", ev.title)
                continue
            fresh.append(ev)
        return fresh

    def _compare_to_live(self, events: list[Event]) -> list[Event]:
        live = self.supabase.fetch_events()
        if not live:
            log.warning(
                "no live events available to compare against; everything will "
                "look new. Set SUPABASE_URL and SUPABASE_ANON_KEY."
            )
        queued: list[Event] = []
        for ev in events:
            verdict, match, score, reasons = dedupe.against_existing(ev, live)
            if verdict == "duplicate":
                # The community flagging an event down is a decision. Never
                # re-add it, and count it separately so it is visible in the
                # run summary rather than blending into ordinary duplicates.
                was_flagged = bool(match and match.source == "live-site-flagged")
                if was_flagged:
                    self.stats.community_flagged += 1
                    log.info(
                        "not re-adding %r: the matching event on the site was "
                        "flagged down by the community",
                        ev.title,
                    )
                else:
                    self.stats.already_live += 1
                # Still record it, so the same page does not re-surface forever.
                self.ledger.record(
                    ev.fingerprint,
                    title=ev.title,
                    start_date=ev.start_date,
                    match_key=ev.match_key,
                    phash=ev.flyer_phash,
                    source=ev.source,
                    source_url=ev.source_url,
                    outcome="community-flagged" if was_flagged else "already-on-site",
                )
                continue
            if verdict == "possible" and match is not None:
                if match.source == "live-site-flagged":
                    ev.warnings.append(
                        f"resembles an event the community flagged off the site: "
                        f"{match.title!r} on {match.start_date} - worth checking "
                        f"why before you approve this"
                    )
                ev.warnings.append(
                    f"looks close to an event already on the site: "
                    f"{match.title!r} on {match.start_date} ({int(score * 100)}% match, "
                    f"{', '.join(reasons) or 'weak signals'})"
                )
            queued.append(ev)
        return queued

    def _record(self, events: list[Event]) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        for ev in events:
            ev.first_seen = stamp
            self.ledger.record(
                ev.fingerprint,
                title=ev.title,
                start_date=ev.start_date,
                match_key=ev.match_key,
                phash=ev.flyer_phash,
                source=ev.source,
                source_url=ev.source_url,
                outcome="queued",
            )
