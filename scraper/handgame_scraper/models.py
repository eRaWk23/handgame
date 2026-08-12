"""Normalized event model shared by every source adapter.

The field names deliberately mirror the Supabase `events` table used by
handgame.info so that publishing is a straight mapping with no translation
layer to get out of sync:

    events(id, title, start_date, end_date, location, tribe, details,
           flyer_url, report_count)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Optional

# Words that show up in stylized flyer OCR and add nothing to a title.
_NOISE = re.compile(
    r"\b(annual|presents?|proudly|welcome[s]? (?:you )?to|come one come all)\b",
    re.I,
)
_WS = re.compile(r"\s+")


def _clean(text: Optional[str], limit: int = 400) -> Optional[str]:
    if not text:
        return None
    text = _WS.sub(" ", str(text)).strip(" \t\n\r-–—|•*")
    return text[:limit] or None


def title_case_if_shouting(text: str) -> str:
    """Flyers are usually ALL CAPS. Keep acronyms, soften the rest."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.85:
        return " ".join(
            w if (len(w) <= 3 and w.isupper()) else w.capitalize()
            for w in text.split()
        )
    return text


def normalize_key(text: Optional[str]) -> str:
    """Aggressive normalization used only for matching, never for display."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"&", " and ", text)
    text = _NOISE.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    # Collapse common spelling variants so they compare equal.
    text = re.sub(r"\bstick ?game[s]?\b", "handgame", text)
    text = re.sub(r"\bbone ?game[s]?\b", "handgame", text)
    text = re.sub(r"\bhand ?game[s]?\b", "handgame", text)
    text = re.sub(r"\bstickgames?\b", "handgame", text)
    text = re.sub(r"\btourn\w*\b", "tournament", text)
    text = re.sub(r"\bcompetitions?\b", "tournament", text)
    return _WS.sub(" ", text).strip()


def normalize_location(text: Optional[str]) -> str:
    """Like normalize_key, but expands state codes first.

    Without this, "Nespelem, WA" and "Nespelem, Washington" look like two
    different places and the same event slips through as new.
    """
    if not text:
        return ""
    from .extract import STATES  # imported here to avoid a circular import

    key = normalize_key(text)
    tokens = key.split()
    # Only the FINAL token can be a state code. Expanding any two-letter token
    # turned "Community Center in Omak, WA" into "...indiana omak washington",
    # and location_state then reported Indiana, which broke duplicate
    # detection for every location containing the words in, at, or, la, me...
    expanded = list(tokens)
    if tokens and len(tokens[-1]) == 2 and tokens[-1].upper() in STATES:
        expanded[-1] = STATES[tokens[-1].upper()].lower()
    # Drop filler that varies between write-ups of the same venue.
    drop = {"the", "at", "on", "near", "reservation", "rez", "grounds"}
    return " ".join(t for t in expanded if t not in drop)


def location_state(text: Optional[str]) -> Optional[str]:
    """The state or province in a location string, normalized."""
    if not text:
        return None
    from .extract import STATES

    tokens = normalize_location(text).split()
    full_names = {v.lower(): v for v in STATES.values()}
    # Check two-word names like "new mexico" before single tokens, and take the
    # last match, because in an address the state comes at the end.
    for size in (3, 2, 1):
        for i in range(len(tokens) - size, -1, -1):
            candidate = " ".join(tokens[i : i + size])
            if candidate in full_names:
                return full_names[candidate]
    return None


@dataclass
class Event:
    """A single candidate event, from any source."""

    # --- columns that map 1:1 onto the Supabase table -------------------
    title: str = ""
    start_date: Optional[str] = None  # ISO YYYY-MM-DD
    end_date: Optional[str] = None
    location: Optional[str] = None
    tribe: Optional[str] = None
    details: Optional[str] = None
    flyer_url: Optional[str] = None

    # --- provenance and scoring, never published ------------------------
    source: str = ""  # adapter name, e.g. "reddit"
    source_url: Optional[str] = None  # where a human can verify this
    source_posted_at: Optional[str] = None
    extraction: str = "structured"  # structured | ocr | llm | manual
    confidence: float = 0.0  # 0..1
    warnings: list[str] = field(default_factory=list)
    flyer_phash: Optional[str] = None  # perceptual hash of the flyer image
    raw_text: Optional[str] = None  # OCR / post body, kept for the reviewer
    first_seen: Optional[str] = None
    # True when `title` is only a stand-in (a filename, say) that anything
    # read off the flyer itself should be allowed to replace.
    title_provisional: bool = False

    # ------------------------------------------------------------------
    def tidy(self) -> "Event":
        """Clean up whitespace and casing in place, then return self."""
        self.title = _clean(title_case_if_shouting(self.title or ""), 200) or ""
        self.location = _clean(self.location, 200)
        self.tribe = _clean(self.tribe, 120)
        self.details = _clean(self.details, 2000)
        self.raw_text = _clean(self.raw_text, 4000)
        for attr in ("start_date", "end_date"):
            val = getattr(self, attr)
            if isinstance(val, (date, datetime)):
                setattr(self, attr, val.strftime("%Y-%m-%d"))
        if self.end_date and self.start_date and self.end_date < self.start_date:
            self.warnings.append("end_date was before start_date; dropped it")
            self.end_date = None
        return self

    @property
    def fingerprint(self) -> str:
        """Stable id for the 'have I seen this exact item before' ledger.

        Built from the source URL when we have one, because that is the most
        durable identifier, and otherwise from the normalized content.
        """
        # The URL alone is not enough. One listing page can carry a dozen
        # events, and when a parser cannot find a per-event link they all fall
        # back to the page URL - which collapsed every event from a site into a
        # single ledger entry and permanently suppressed the rest.
        basis = "|".join(
            [
                (self.source_url or "").strip().lower(),
                normalize_key(self.title),
                self.start_date or "",
                normalize_location(self.location),
            ]
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def match_key(self) -> str:
        """Exact-match key for the obvious duplicate case."""
        return f"{self.start_date or ''}|{normalize_location(self.location)}"

    def is_publishable(self) -> bool:
        """Mirrors the site's own required fields: title, start_date, location."""
        return bool(self.title and self.start_date and self.location)

    def is_future(self, today: Optional[date] = None) -> bool:
        if not self.start_date:
            return False
        today = today or date.today()
        end = self.end_date or self.start_date
        try:
            return datetime.strptime(end, "%Y-%m-%d").date() >= today
        except ValueError:
            return False

    def to_supabase_row(self) -> dict[str, Any]:
        """Exactly the payload the public submission form sends."""
        return {
            "title": self.title,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "location": self.location,
            "tribe": self.tribe,
            "details": self.details,
            "flyer_url": self.flyer_url,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.setdefault("warnings", [])
        return cls(**known)

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return json.dumps(self.to_dict(), indent=2, default=str)
