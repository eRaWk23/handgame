"""The manual inbox — how Facebook and Instagram flyers actually get in.

Neither platform can be scraped reliably or within their terms: both block
datacenter traffic, require a logged-in session, and forbid automated
collection. Pretending otherwise would produce a scraper that silently returns
nothing every run.

So this adapter takes the two-minute human step and automates everything after
it. Drop either of these into scraper/inbox/ and the full pipeline — OCR, date
extraction, dedup, review queue — runs on them exactly like a scraped source:

  * flyer images  (.jpg .png .webp .gif) saved from a post
  * links.txt     one URL per line; anything ending in an image extension is
                  fetched, anything else is recorded for the reviewer

An optional sidecar note gives the pipeline a head start: put `myflyer.txt`
next to `myflyer.jpg` with any context you already know, one `key: value` per
line (title, location, tribe, date, url).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Iterator, Optional

from ..extract import find_dates, find_location, find_tribe, guess_title
from ..models import Event
from .base import Source

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


class InboxSource(Source):
    name = "inbox"
    label = "Manual inbox (Facebook / Instagram flyers)"

    def _dir(self) -> Path:
        return Path(self.settings.get("path", "inbox")).expanduser()

    def available(self) -> tuple[bool, str]:
        path = self._dir()
        if not path.exists():
            return False, f"no inbox directory at {path}"
        return True, ""

    def collect(self) -> Iterator[Event]:
        inbox = self._dir()
        processed = inbox / "processed"

        for path in sorted(inbox.iterdir()):
            if path.is_dir() or path.name.startswith("."):
                continue
            if path.suffix.lower() in IMAGE_EXT:
                event = self._from_image(path)
                if event:
                    yield event
            elif path.name.lower() in ("links.txt", "urls.txt"):
                yield from self._from_links(path)

        if self.settings.get("archive_after_run", True) and processed.exists():
            self.log.info("inbox items already archived under %s", processed)

    # ------------------------------------------------------------------
    def _from_image(self, path: Path) -> Optional[Event]:
        try:
            data = path.read_bytes()
        except OSError as exc:
            self.log.warning("could not read %s: %s", path, exc)
            return None

        note = self._read_note(path)
        # local:// tells the enrichment stage to read bytes from disk rather
        # than fetch over the network, and the reviewer sees the filename.
        titled = bool(note.get("title"))
        event = self._event(
            title=note.get("title", "") or path.stem.replace("_", " ").replace("-", " "),
            title_provisional=not titled,  # a filename loses to the flyer itself
            start_date=note.get("date"),
            location=note.get("location"),
            tribe=note.get("tribe"),
            details=note.get("details"),
            flyer_url=note.get("flyer_url") or f"local://{path.resolve()}",
            source_url=note.get("url") or f"local://{path.name}",
            extraction="manual",
            confidence=0.4,
        )
        event._local_bytes = data  # type: ignore[attr-defined]
        return event

    def _read_note(self, image_path: Path) -> dict[str, str]:
        note_path = image_path.with_suffix(".txt")
        if not note_path.exists():
            return {}
        note: dict[str, str] = {}
        try:
            for line in note_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip().lower()
                    value = value.strip()
                    if key and value:
                        note[key] = value
        except OSError:
            return {}
        if "date" in note:
            start, _, _ = find_dates(note["date"])
            note["date"] = start.strftime("%Y-%m-%d") if start else ""
        return {k: v for k, v in note.items() if v}

    # ------------------------------------------------------------------
    def _from_links(self, path: Path) -> Iterator[Event]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return

        for line in lines:
            url = line.strip()
            if not url or url.startswith("#"):
                continue

            note = ""
            if " " in url:
                url, _, note = url.partition(" ")

            is_image = Path(url.split("?")[0]).suffix.lower() in IMAGE_EXT
            if is_image:
                yield self._event(
                    title=note or "Flyer from pasted link",
                    flyer_url=url,
                    source_url=url,
                    details=note or None,
                    extraction="manual",
                    confidence=0.4,
                )
                continue

            # A non-image link: fetch the page and let the generic extractors
            # take a pass, so a pasted event URL still produces something.
            html = self.fetch.get_text(url)
            if not html:
                yield self._event(
                    title=note or url,
                    source_url=url,
                    details="Pasted link; page could not be read automatically.",
                    extraction="manual",
                    confidence=0.15,
                    warnings=["page could not be fetched - fill in by hand"],
                )
                continue

            import re

            text = re.sub(r"<[^>]+>", "\n", html)
            text = re.sub(r"\n{2,}", "\n", text)
            start, end, warnings = find_dates(text)
            yield self._event(
                title=note or guess_title(text, url),
                start_date=start,
                end_date=end,
                location=find_location(text),
                tribe=find_tribe(text),
                source_url=url,
                extraction="manual",
                confidence=0.35,
                raw_text=text[:3000],
                warnings=list(warnings),
            )
