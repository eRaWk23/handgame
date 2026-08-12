"""Duplicate detection.

Three separate questions, answered in order of cost:

  1. Have we literally seen this item before?        -> ledger fingerprint
  2. Is this the same flyer image as something else?  -> perceptual hash
  3. Is this the same real-world event described
     differently by two sources?                     -> fuzzy field matching

Question 3 is the interesting one. "Colville Labor Day Stickgame Tournament"
and "38th Annual Labor Day Hand Game Tourney - Nespelem" are the same weekend
in the same place, and a naive string compare says they share nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional, Sequence

from rapidfuzz import fuzz

from .models import Event, location_state, normalize_key, normalize_location

log = logging.getLogger(__name__)

# Tuned so that near-certain matches auto-merge and plausible ones are
# surfaced to the reviewer rather than silently dropped.
CERTAIN = 0.90
LIKELY = 0.72


def _date_proximity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """1.0 for the same day, sliding to 0 about a week out."""
    if not a or not b:
        return None
    try:
        da = datetime.strptime(a, "%Y-%m-%d").date()
        db = datetime.strptime(b, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    gap = abs((da - db).days)
    if gap == 0:
        return 1.0
    if gap <= 1:
        return 0.85  # flyers disagree on whether setup day counts
    if gap <= 3:
        return 0.55
    if gap <= 7:
        return 0.25
    return 0.0


def _text_sim(a: Optional[str], b: Optional[str]) -> Optional[float]:
    ka, kb = normalize_key(a), normalize_key(b)
    if not ka or not kb:
        return None
    # token_set_ratio ignores word order and extra words, which is exactly
    # what differs between two write-ups of the same tournament.
    return max(fuzz.token_set_ratio(ka, kb), fuzz.partial_ratio(ka, kb)) / 100.0


def _location_sim(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """Location similarity with state codes expanded first."""
    ka, kb = normalize_location(a), normalize_location(b)
    if not ka or not kb:
        return None
    return max(fuzz.token_set_ratio(ka, kb), fuzz.partial_ratio(ka, kb)) / 100.0


def _states_conflict(a: Optional[str], b: Optional[str]) -> bool:
    """Two named places in different states are not the same gathering."""
    sa, sb = location_state(a), location_state(b)
    return bool(sa and sb and sa != sb)


def similarity(a: Event, b: Event) -> tuple[float, list[str]]:
    """Weighted 0..1 likelihood that a and b are the same real event."""
    reasons: list[str] = []

    date_score = _date_proximity(a.start_date, b.start_date)

    # An identical flyer image is normally conclusive, but hosts do reuse last
    # year's artwork with the date swapped, so a clear date conflict outranks
    # the image. Without this guard the new year's tournament gets silently
    # merged into the old one and never reaches the queue.
    if a.flyer_phash and b.flyer_phash and a.flyer_phash == b.flyer_phash:
        if date_score is None or date_score > 0.0:
            return 1.0, ["identical flyer image"]
        return 0.0, []
    loc_score = _location_sim(a.location, b.location)
    title_score = _text_sim(a.title, b.title)

    # Without a date match there is very little chance it is the same event.
    if date_score is not None and date_score == 0.0:
        return 0.0, []

    # Same weekend, different state: two separate tournaments. This matters
    # because generic titles like "Handgame Tournament" score as a perfect
    # text match against every other handgame tournament in the country.
    if _states_conflict(a.location, b.location):
        return 0.0, []

    parts: list[tuple[float, float]] = []  # (score, weight)
    if date_score is not None:
        parts.append((date_score, 0.45))
        if date_score >= 0.85:
            reasons.append("same or adjacent date")
    if loc_score is not None:
        parts.append((loc_score, 0.30))
        if loc_score >= 0.80:
            reasons.append("same location")
    if title_score is not None:
        parts.append((title_score, 0.25))
        if title_score >= 0.80:
            reasons.append("very similar title")

    if not parts:
        return 0.0, []
    total_weight = sum(w for _, w in parts)
    score = sum(s * w for s, w in parts) / total_weight

    # A date plus a location is strong evidence on its own; two events rarely
    # share a day and a town.
    if date_score and date_score >= 0.85 and loc_score and loc_score >= 0.85:
        score = max(score, 0.92)
        reasons.append("same day and place")

    return round(score, 3), reasons


def best_match(
    candidate: Event, pool: Sequence[Event]
) -> tuple[Optional[Event], float, list[str]]:
    best: Optional[Event] = None
    best_score = 0.0
    best_reasons: list[str] = []
    for other in pool:
        score, reasons = similarity(candidate, other)
        if score > best_score:
            best, best_score, best_reasons = other, score, reasons
    return best, best_score, best_reasons


def merge(primary: Event, extra: Event) -> Event:
    """Fold a duplicate's better-populated fields into the one we are keeping."""
    for attr in ("end_date", "location", "tribe", "details", "flyer_url"):
        if not getattr(primary, attr) and getattr(extra, attr):
            setattr(primary, attr, getattr(extra, attr))
    # A longer title usually carries more information ("38th Annual ...").
    if len(extra.title or "") > len(primary.title or "") + 8:
        primary.title = extra.title
    if extra.source and extra.source not in primary.source:
        primary.source = f"{primary.source}+{extra.source}"
    # Keep the duplicate's link so a reviewer can check the second write-up.
    if extra.source_url and extra.source_url != primary.source_url:
        primary.warnings.append(f"also listed at {extra.source_url}")
    primary.confidence = max(primary.confidence, extra.confidence)
    if not primary.raw_text and extra.raw_text:
        primary.raw_text = extra.raw_text
    return primary


def deduplicate_batch(events: Iterable[Event]) -> tuple[list[Event], int]:
    """Collapse duplicates inside a single scrape run."""
    kept: list[Event] = []
    collapsed = 0
    # Process the most complete records first so they become the primaries.
    ordered = sorted(
        events,
        key=lambda e: (
            e.confidence,
            sum(bool(getattr(e, f)) for f in ("end_date", "tribe", "details", "flyer_url")),
        ),
        reverse=True,
    )
    for ev in ordered:
        match, score, reasons = best_match(ev, kept)
        if match is not None and score >= CERTAIN:
            merge(match, ev)
            collapsed += 1
            log.debug("merged %r into %r (%.2f: %s)", ev.title, match.title, score, reasons)
        else:
            # Kept, but if something already kept carries the same artwork on a
            # different date, one of the two dates is wrong. Say so rather than
            # letting a reviewer approve both.
            if ev.flyer_phash:
                twin = next(
                    (k for k in kept if k.flyer_phash == ev.flyer_phash and k is not ev),
                    None,
                )
                if twin and twin.start_date != ev.start_date:
                    note = (
                        f"same flyer image as another event in this batch "
                        f"({twin.start_date}) - check which date is right"
                    )
                    ev.warnings.append(note)
                    twin.warnings.append(
                        f"same flyer image as another event in this batch "
                        f"({ev.start_date}) - check which date is right"
                    )
            kept.append(ev)
    return kept, collapsed


def against_existing(
    candidate: Event, existing: Sequence[Event]
) -> tuple[str, Optional[Event], float, list[str]]:
    """Compare one candidate to everything already live on the site.

    Returns a verdict of "new", "possible" or "duplicate".
    """
    match, score, reasons = best_match(candidate, existing)
    if score >= CERTAIN:
        return "duplicate", match, score, reasons
    if score >= LIKELY:
        return "possible", match, score, reasons
    return "new", None, score, reasons
