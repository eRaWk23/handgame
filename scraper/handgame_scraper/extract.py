"""Pull dates, places and tribes out of free text.

This is what turns a wall of OCR'd flyer text into structured fields. It is
deliberately conservative: when a pattern is ambiguous it records a warning
and lowers confidence rather than guessing, because a wrong date on a
community calendar is worse than a missing one.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable, Optional

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "febuary": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

# Flyers almost always print the weekday next to the date. That redundancy is
# free verification: OCR misreading "Thursday, July 9" as "July 7" produces a
# date that parses perfectly and is silently wrong, but July 7th is a Tuesday,
# and the flyer says Thursday. Monday is 0, matching date.weekday().
WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tues": 1, "tue": 1,
    "wednesday": 2, "weds": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_WEEKDAY_RE = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "AB": "Alberta", "BC": "British Columbia", "SK": "Saskatchewan",
    "MB": "Manitoba",
}
_STATE_ABBR_RE = "|".join(STATES)
_STATE_NAME_RE = "|".join(
    sorted((re.escape(v) for v in STATES.values()), key=len, reverse=True)
)

# Nations and communities where handgame / stickgame / bone game is played.
# Used to fill the `tribe` column and to score topical relevance.
TRIBES = [
    "Colville", "Spokane", "Yakama", "Kalispel", "Coeur d'Alene", "Coeur dAlene",
    "Nez Perce", "Umatilla", "Warm Springs", "Wanapum", "Muckleshoot",
    "Puyallup", "Tulalip", "Lummi", "Swinomish", "Nooksack", "Suquamish",
    "Squaxin", "Nisqually", "Skokomish", "Quinault", "Makah", "Chehalis",
    "Cowlitz", "Shoalwater", "Samish", "Upper Skagit", "Sauk-Suiattle",
    "Stillaguamish", "Snoqualmie", "Jamestown S'Klallam", "Port Gamble",
    "Grand Ronde", "Siletz", "Coquille", "Klamath",
    "Burns Paiute", "Shoshone-Bannock", "Shoshone Bannock", "Shoshone-Paiute",
    "Northwestern Shoshone", "Fort Hall", "Duck Valley", "Paiute",
    "Salish", "Kootenai", "Kootenay", "Flathead", "Blackfeet", "Crow",
    "Northern Cheyenne", "Fort Peck", "Fort Belknap", "Assiniboine", "Sioux",
    "Chippewa Cree", "Rocky Boy", "Little Shell", "Gros Ventre",
    "Shoshone", "Arapaho", "Wind River", "Ute", "Navajo", "Apache",
    "Yakima", "Wasco", "Tenino", "Cayuse", "Walla Walla", "Palus",
    "Okanagan", "Osoyoos", "Penticton", "Westbank", "Shuswap", "Secwepemc",
    "Nlaka'pamux", "Similkameen", "Lower Nicola", "Tk'emlups", "Adams Lake",
    "Neskonlith", "Splatsin", "Enderby", "Cree", "Metis", "Dene",
    "Tsuut'ina", "Siksika", "Piikani", "Kainai", "Stoney Nakoda",
    "Yurok", "Hoopa", "Karuk", "Pit River", "Maidu", "Pomo", "Wintun",
    "Round Valley", "Susanville", "Elem", "Big Valley", "Robinson Rancheria",
]

# Umbrella phrases. Only used when no specific nation is named, otherwise
# "Confederated Tribes of the Colville Reservation" loses the useful half.
GENERIC_GROUPS = [
    "Confederated Tribes", "Confederated Salish and Kootenai Tribes",
    "First Nation", "Indian Band", "Rancheria", "Pueblo",
]

SPECIFIC_TRIBES = TRIBES

# Signals that a piece of text is actually about a handgame event.
TOPIC_STRONG = [
    "handgame", "hand game", "hand-game", "stickgame", "stick game",
    "stick-game", "bone game", "bonegame", "slahal", "lahal", "peon game",
]
TOPIC_SUPPORT = [
    "tournament", "tourney", "double elimination", "round robin",
    "payout", "entry fee", "drummers", "stick game tourney", "sticks",
    "powwow", "pow wow", "pow-wow", "encampment", "celebration",
    "memorial", "give away", "giveaway", "camping", "vendors",
]
# Things that look like a match but are a different world entirely.
TOPIC_NEGATIVE = [
    "esports", "e-sports", "video game", "xbox", "playstation", "nintendo",
    "fortnite", "call of duty", "board game", "d&d", "dungeons",
    "hand-eye", "handball", "video-game",
]

# Towns and communities that host handgame regularly. Flyers and posts very
# often name the town with no state at all ("in Nespelem this weekend"), which
# no generic pattern can resolve, so the common ones are listed outright.
KNOWN_PLACES = {
    "nespelem": "Nespelem, Washington", "wellpinit": "Wellpinit, Washington",
    "omak": "Omak, Washington", "inchelium": "Inchelium, Washington",
    "keller": "Keller, Washington", "usk": "Usk, Washington",
    "cusick": "Cusick, Washington", "toppenish": "Toppenish, Washington",
    "wapato": "Wapato, Washington", "white swan": "White Swan, Washington",
    "airway heights": "Airway Heights, Washington",
    "auburn": "Auburn, Washington", "tulalip": "Tulalip, Washington",
    "la conner": "La Conner, Washington", "taholah": "Taholah, Washington",
    "neah bay": "Neah Bay, Washington", "shelton": "Shelton, Washington",
    "nisqually": "Nisqually, Washington", "suquamish": "Suquamish, Washington",
    "ferndale": "Ferndale, Washington", "darrington": "Darrington, Washington",
    "fort hall": "Fort Hall, Idaho", "lapwai": "Lapwai, Idaho",
    "plummer": "Plummer, Idaho", "worley": "Worley, Idaho",
    "kamiah": "Kamiah, Idaho", "owyhee": "Owyhee, Nevada",
    "pablo": "Pablo, Montana", "arlee": "Arlee, Montana",
    "ronan": "Ronan, Montana", "polson": "Polson, Montana",
    "elmo": "Elmo, Montana", "browning": "Browning, Montana",
    "box elder": "Box Elder, Montana", "poplar": "Poplar, Montana",
    "wolf point": "Wolf Point, Montana", "lame deer": "Lame Deer, Montana",
    "crow agency": "Crow Agency, Montana", "harlem": "Harlem, Montana",
    "st ignatius": "St. Ignatius, Montana", "hays": "Hays, Montana",
    "pendleton": "Pendleton, Oregon", "warm springs": "Warm Springs, Oregon",
    "chiloquin": "Chiloquin, Oregon", "grand ronde": "Grand Ronde, Oregon",
    "siletz": "Siletz, Oregon", "burns": "Burns, Oregon",
    "fort washakie": "Fort Washakie, Wyoming",
    "ethete": "Ethete, Wyoming", "arapahoe": "Arapahoe, Wyoming",
    "kamloops": "Kamloops, British Columbia",
    "merritt": "Merritt, British Columbia",
    "penticton": "Penticton, British Columbia",
    "vernon": "Vernon, British Columbia",
    "chase": "Chase, British Columbia",
    "cranbrook": "Cranbrook, British Columbia",
    "williams lake": "Williams Lake, British Columbia",
}

_ORDINAL = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\b", re.I)
_TIME_RE = re.compile(r"\b\d{1,2}\s*[:.]\s*\d{2}\s*(?:am|pm)?\b|\b\d{1,2}\s*(?:am|pm)\b", re.I)


def _clamp_year(token: str, today: date) -> int:
    """'2026' or "'26" -> 2026."""
    year = int(str(token).lstrip("'"))
    if year < 100:
        year += 2000
    return year


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _infer_year(month: int, day: int, today: date) -> int:
    """A flyer with no year almost always means the next occurrence."""
    candidate = _safe_date(today.year, month, day)
    if candidate and candidate >= today:
        return today.year
    return today.year + 1


_WEEKDAY_DATE = re.compile(
    rf"\b({_WEEKDAY_RE})\b\.?,?\s{{0,3}}"
    rf"(?:({_MONTH_RE})\.?\s+(?<!\d)(\d{{1,2}})(?!\d)"
    rf"|(?<!\d)(\d{{1,2}})(?!\d)\s+({_MONTH_RE})\.?\b)"
    rf"\s*,?\s*(?:(?<!\d)(\d{{4}}|'\d{{2}})(?!\d))?",
    re.I,
)


def _weekday_conflicts(cleaned: str, today: date) -> list[str]:
    """Warn when a printed weekday contradicts the date printed beside it.

    Only compares a weekday to a date directly adjacent to it. A weekday at
    the top of a page and a date at the bottom say nothing about each other,
    and pairing those would fire constantly on listing pages.

    Never changes a date. A contradiction means one of the two was misread,
    and which one is not knowable from here, so it warns and lets a person
    look. This is the check that catches an OCR digit error that would
    otherwise parse cleanly and publish a wrong date.
    """
    out: list[str] = []
    for m in _WEEKDAY_DATE.finditer(cleaned):
        named = WEEKDAYS[m.group(1).lower()]
        if m.group(2):
            month, day = MONTHS[m.group(2).lower()], int(m.group(3))
        else:
            month, day = MONTHS[m.group(5).lower()], int(m.group(4))

        printed = m.group(6)
        if printed:
            base = _clamp_year(printed, today)
            years = [base]
        else:
            # With no printed year the weekday cannot settle which year was
            # meant, so accept any nearby year that fits and complain only
            # when none of them do — that means the day itself is wrong.
            base = _infer_year(month, day, today)
            years = [base - 1, base, base + 1]

        resolved = [d for d in (_safe_date(y, month, day) for y in years) if d]
        if not resolved or any(d.weekday() == named for d in resolved):
            continue
        # Name the year find_dates would settle on, not whichever candidate
        # happened to sort first, so the warning matches the queued date.
        actual = _safe_date(base, month, day) or resolved[0]
        note = (
            f"flyer says {m.group(1).title()} but "
            f"{actual:%B} {actual.day} {actual.year} is a "
            f"{_WEEKDAY_NAMES[actual.weekday()]}"
        )
        if note not in out:
            out.append(note)
    return out


def find_dates(text: str, today: Optional[date] = None) -> tuple[Optional[date], Optional[date], list[str]]:
    """Return (start, end, warnings) for the most likely event date range."""
    today = today or date.today()
    warnings: list[str] = []
    if not text:
        return None, None, warnings

    # Strip times first so "7:00 PM" cannot be read as a numeric date.
    cleaned = _TIME_RE.sub(" ", text)
    cleaned = _ORDINAL.sub(r"\1", cleaned)
    # (start, end, priority, year_was_printed)
    candidates: list[tuple[date, Optional[date], int, bool]] = []

    # 1. "September 12-14, 2025" / "Sept 12 & 13 2025" / "Aug 29 - Sep 1, 2025"
    # (?<!\d) and (?!\d) stop a 4-digit year being chopped into a day plus a
    # 2-digit year, which turned "12 September 2026" into September 20th '26.
    # Only a 4-digit year, or an apostrophe form like '26, counts as a printed
    # year here. Allowing a bare 2-digit number made "AUGUST 29, 30, 31" parse
    # as August 29th of 2030, with no warning and high confidence.
    pat_range = re.compile(
        rf"\b({_MONTH_RE})\.?\s+(?<!\d)(\d{{1,2}})(?!\d)\s*"
        rf"(?:[-–—]|thru|through|to|&|and)\s*"
        rf"(?:({_MONTH_RE})\.?\s+)?(?<!\d)(\d{{1,2}})(?!\d)\s*,?\s*"
        rf"(?:(?<!\d)(\d{{4}}|'\d{{2}})(?!\d))?",
        re.I,
    )
    for m in pat_range.finditer(cleaned):
        m1 = MONTHS[m.group(1).lower()]
        d1 = int(m.group(2))
        m2 = MONTHS[m.group(3).lower()] if m.group(3) else m1
        d2 = int(m.group(4))
        printed = bool(m.group(5))
        year = _clamp_year(m.group(5), today) if printed else _infer_year(m1, d1, today)
        start = _safe_date(year, m1, d1)
        end_year = year + 1 if m2 < m1 else year
        end = _safe_date(end_year, m2, d2)
        if start:
            candidates.append((start, end if end and end >= start else None, 3, printed))

    # 1b. A list of days: "AUGUST 29, 30, 31" or "SEPT 12, 13 & 14".
    # Very common on flyers, and it needs its own pattern because the range
    # pattern only understands two endpoints.
    pat_list = re.compile(
        rf"\b({_MONTH_RE})\.?\s+(?<!\d)(\d{{1,2}})(?!\d)"
        rf"((?:\s*(?:,|&|and)\s*(?<!\d)\d{{1,2}}(?!\d)){{1,5}})"
        rf"\s*,?\s*(?:(?<!\d)(\d{{4}}|'\d{{2}})(?!\d))?",
        re.I,
    )
    for m in pat_list.finditer(cleaned):
        mon = MONTHS[m.group(1).lower()]
        days = [int(m.group(2))] + [
            int(d) for d in re.findall(r"\d{1,2}", m.group(3))
        ]
        # Only treat it as one event's day list if the days really are
        # consecutive-ish; "6, 27 & 28" is two separate things, not a range.
        days = sorted(set(days))
        if len(days) < 2 or (days[-1] - days[0]) > len(days) + 2:
            continue
        printed = bool(m.group(4))
        year = _clamp_year(m.group(4), today) if printed else _infer_year(mon, days[0], today)
        start = _safe_date(year, mon, days[0])
        end = _safe_date(year, mon, days[-1])
        if start and end and end > start:
            candidates.append((start, end, 3, printed))

    # 2. "September 12, 2025" / "Sept 12 2025" / "12 September 2025"
    # "12 September 2026" is handled by pat_dmy below, so skip any match here
    # whose month is directly preceded by a day number.
    pat_single = re.compile(
        rf"(?<!\d\s)\b({_MONTH_RE})\.?\s+(?<!\d)(\d{{1,2}})(?!\d)\s*,?\s*"
        rf"(?:(?<!\d)(\d{{4}}|'\d{{2}})(?!\d))?",
        re.I,
    )
    for m in pat_single.finditer(cleaned):
        mon = MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        printed = bool(m.group(3))
        year = _clamp_year(m.group(3), today) if printed else _infer_year(mon, day, today)
        start = _safe_date(year, mon, day)
        if start:
            candidates.append((start, None, 2, printed))

    pat_dmy = re.compile(
        rf"\b(?<!\d)(\d{{1,2}})(?!\d)\s+({_MONTH_RE})\.?\s*,?\s*(\d{{4}})\b", re.I
    )
    for m in pat_dmy.finditer(cleaned):
        day, mon = int(m.group(1)), MONTHS[m.group(2).lower()]
        start = _safe_date(int(m.group(3)), mon, day)
        if start:
            candidates.append((start, None, 2, True))

    # 3. Numeric "9/12/25" and "9-12-2025". US month-first order assumed.
    pat_numeric = re.compile(
        r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b"
    )
    for m in pat_numeric.finditer(cleaned):
        a, b = int(m.group(1)), int(m.group(2))
        if not (1 <= a <= 12 and 1 <= b <= 31):
            continue
        printed = bool(m.group(3))
        year = _clamp_year(m.group(3), today) if printed else _infer_year(a, b, today)
        start = _safe_date(year, a, b)
        if start:
            if b > 12 or printed:
                candidates.append((start, None, 1, printed))
            else:
                # 9/12 could be Sept 12 or Dec 9. Keep it but flag it.
                candidates.append((start, None, 0, printed))

    # 4. ISO "2025-09-12"
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", cleaned):
        start = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if start:
            candidates.append((start, None, 4, True))

    if not candidates:
        return None, None, warnings

    # Only worth reporting once a date actually parsed — a page with no date
    # at all is dropped as incomplete anyway.
    warnings.extend(_weekday_conflicts(cleaned, today))

    # A printed year is a fact; an inferred one is a guess. Never let a guess
    # outrank a fact just because the guess lands in the future — that is how
    # "May 22-25, 2026" silently became 2027.
    printed_pool = [c for c in candidates if c[3]]
    if printed_pool:
        pool = printed_pool
        future = [c for c in pool if (c[1] or c[0]) >= today]
        if future:
            pool = future
        else:
            warnings.append("every date found is in the past")
    else:
        pool = candidates
        future = [c for c in pool if (c[1] or c[0]) >= today]
        if future:
            pool = future
        else:
            warnings.append("every date found is in the past")

    pool.sort(key=lambda c: (-c[2], c[0]))
    start, end, priority, _printed = pool[0]
    if priority == 0:
        warnings.append("ambiguous numeric date (day/month order unclear)")

    # If several same-priority dates cluster within a week, treat as a range.
    if end is None:
        same = sorted(
            {c[0] for c in pool if c[2] == priority and 0 < (c[0] - start).days <= 10}
        )
        if same:
            end = same[-1]
    return start, end, warnings


def find_location(text: str) -> Optional[str]:
    """Best-effort 'City, ST' extraction."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)

    # "Wellpinit, WA" / "Nespelem, Washington" / "WELLPINIT, WASHINGTON".
    #
    # Two subtleties, both learned from real strings:
    #   * The two-letter code is matched case-sensitively as uppercase. Matching
    #     it case-insensitively turned "Swinomish Casino & Lodge, La Conner, WA"
    #     into "Lodge, Louisiana", because "La" is Louisiana's code.
    #   * The LAST match wins, not the first. In an address the state comes at
    #     the end, so the rightmost "something, ST" is the real one.
    matches = list(
        re.finditer(
            rf"\b([A-Z][A-Za-z'\.\-]+(?:\s+[A-Z][A-Za-z'\.\-]+){{0,3}})\s*,\s*"
            rf"(?:({_STATE_ABBR_RE})|(?i:({_STATE_NAME_RE})))\b",
            flat,
        )
    )
    if matches:
        m = matches[-1]
        city = _title_place(m.group(1).strip())
        state_token = m.group(2) or m.group(3) or ""
        return f"{city}, {canonical_state(state_token) or state_token.strip()}"

    # A known handgame town named on its own: "in Nespelem this weekend".
    # Longest name first so "white swan" is not shadowed by a shorter match.
    for town in sorted(KNOWN_PLACES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(town)}\b", flat, re.I):
            return KNOWN_PLACES[town]

    # A named venue is better than nothing: "at the Spokane Tribal Gym"
    m = re.search(
        r"\b(?:at|@|held at|location:?)\s+((?:the\s+)?[A-Z][\w'\.\-]*"
        r"(?:\s+[A-Z][\w'\.\-]*){0,5}\s+"
        r"(?:Gym|Gymnasium|Arena|Center|Centre|Hall|Casino|Resort|Grounds|"
        r"Fairgrounds|Complex|Pavilion|Longhouse|Park|Field|Community Building))",
        flat,
    )
    if m:
        return m.group(1).strip()

    m = re.search(rf"(?i:\b({_STATE_NAME_RE})\b)", flat)
    return canonical_state(m.group(1)) if m else None


def canonical_state(token: Optional[str]) -> Optional[str]:
    """'WA', 'wa', 'WASHINGTON' -> 'Washington'."""
    if not token:
        return None
    token = token.strip().strip(".")
    if len(token) == 2 and token.upper() in STATES:
        return STATES[token.upper()]
    for full in STATES.values():
        if token.lower() == full.lower():
            return full
    return None


def _title_place(name: str) -> str:
    """Keep normal capitalisation, fix SHOUTED place names."""
    if name.isupper():
        return " ".join(w.capitalize() for w in name.split())
    return name


def find_tribe(text: str) -> Optional[str]:
    """Prefer a specific nation over a generic phrase.

    'Confederated Tribes of the Colville Reservation' should come back as
    Colville, not as the umbrella phrase that happens to be a longer string.
    """
    if not text:
        return None
    for tribe in sorted(SPECIFIC_TRIBES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(tribe)}\b", text, re.I):
            return tribe
    for generic in GENERIC_GROUPS:
        if re.search(rf"\b{re.escape(generic)}\b", text, re.I):
            return generic
    return None


def topic_score(*texts: Optional[str], hint: Optional[str] = None) -> float:
    """0..1 confidence that this text describes a handgame event.

    `hint` is the operator-supplied string from config.yaml. It is scored
    separately and can only ever add support-level credit, never the strong
    keyword itself. Passing it as one of *texts* instead — which is what the
    call sites used to do — let a hint of "stickgame handgame tournament"
    supply the very word being searched for, so every page on a hinted site
    scored 0.8 whether or not it had anything to do with handgame. A casino
    bingo listing came back as a high-confidence handgame event.
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return 0.0
    if any(neg in blob for neg in TOPIC_NEGATIVE) and not any(
        s in blob for s in TOPIC_STRONG
    ):
        return 0.0
    score = 0.0
    if any(s in blob for s in TOPIC_STRONG):
        score += 0.7
    hits = sum(1 for s in TOPIC_SUPPORT if s in blob)
    if hint:
        # Support terms the hint contributes that the text did not already
        # carry. Deliberately no TOPIC_STRONG check: a hint must never be
        # able to push a page over the threshold on its own.
        hint_blob = hint.lower()
        hits += sum(1 for s in TOPIC_SUPPORT if s in hint_blob and s not in blob)
    score += min(0.3, hits * 0.1)
    return round(min(score, 1.0), 2)


def guess_title(text: str, fallback: str = "") -> str:
    """Pick the most title-like line out of OCR text."""
    if not text:
        return fallback
    lines = [ln.strip(" -–—|*•\t") for ln in text.splitlines()]
    lines = [ln for ln in lines if 4 <= len(ln) <= 90]
    if not lines:
        return fallback
    scored = []
    for i, ln in enumerate(lines[:25]):
        s = 0.0
        low = ln.lower()
        if any(t in low for t in TOPIC_STRONG):
            s += 3
        if any(t in low for t in ("tournament", "tourney", "memorial", "annual")):
            s += 2
        if re.search(r"\d{4}", ln):
            s += 0.5
        letters = [c for c in ln if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            s += 1  # flyers put the title in caps
        s -= i * 0.12  # earlier lines are more likely the title
        if re.search(r"@|https?://|\bfacebook\b|\bcall\b|\btext\b", low):
            s -= 2
        scored.append((s, ln))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored and scored[0][0] > 0 else (lines[0] or fallback)


def find_contact(text: str) -> Optional[str]:
    """Phone numbers and names on flyers are the actual useful detail."""
    if not text:
        return None
    bits: list[str] = []
    for m in re.finditer(r"\b(?:\(\d{3}\)\s*|\d{3}[-.\s])\d{3}[-.\s]\d{4}\b", text):
        bits.append(m.group(0).strip())
    for m in re.finditer(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", text):
        bits.append(m.group(0).strip())
    if not bits:
        return None
    seen: list[str] = []
    for b in bits:
        if b not in seen:
            seen.append(b)
    return ", ".join(seen[:4])
