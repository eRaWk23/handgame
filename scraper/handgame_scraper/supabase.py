"""Thin read/write client for the handgame.info Supabase project.

Reading the live `events` table is what lets the pipeline avoid re-adding an
event a human already put on the site by hand.

Credentials never live in this file. Set them in the environment:
    SUPABASE_URL       https://<project>.supabase.co
    SUPABASE_ANON_KEY  the same publishable key the website already uses
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

from .models import Event

log = logging.getLogger(__name__)

TABLE = "events"
FLYER_BUCKET = "event-flyers"

# script.js hides an event once the community has flagged it this many times.
# Keep this in step with REPORT_THRESHOLD there.
REPORT_THRESHOLD = 3


class SupabaseError(RuntimeError):
    pass


class Supabase:
    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self.key = key or os.environ.get("SUPABASE_ANON_KEY") or ""
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key)

    def _headers(self, extra: Optional[dict] = None) -> dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------
    def fetch_events(self, limit: int = 2000) -> list[Event]:
        """Everything currently in the table, as Event objects."""
        if not self.configured:
            log.warning(
                "Supabase not configured (SUPABASE_URL / SUPABASE_ANON_KEY); "
                "cannot check candidates against live events"
            )
            return []
        try:
            resp = requests.get(
                f"{self.url}/rest/v1/{TABLE}",
                headers=self._headers(),
                params={
                    "select": "id,title,start_date,end_date,location,tribe,"
                    "details,flyer_url,report_count",
                    "order": "start_date.desc",
                    "limit": str(limit),
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.error("could not reach Supabase: %s", exc)
            return []
        if resp.status_code >= 400:
            log.error("Supabase read failed %s: %s", resp.status_code, resp.text[:300])
            return []

        # A 200 carrying HTML (a proxy or CDN error page) must not abort a run
        # that has already spent its fetches, OCR and API calls.
        try:
            rows = resp.json()
        except ValueError:
            log.error(
                "Supabase returned a non-JSON body: %s", resp.text[:200]
            )
            return []
        if not isinstance(rows, list):
            log.error("Supabase returned %s, expected a list", type(rows).__name__)
            return []

        events: list[Event] = []
        hidden = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                reports = int(row.get("report_count") or 0)
            except (TypeError, ValueError):
                reports = 0
            flagged = reports >= REPORT_THRESHOLD
            hidden += flagged
            event = Event(
                title=row.get("title") or "",
                start_date=_as_date_str(row.get("start_date")),
                end_date=_as_date_str(row.get("end_date")),
                location=row.get("location"),
                tribe=row.get("tribe"),
                details=row.get("details"),
                flyer_url=row.get("flyer_url"),
                # A flagged-down event is still "on the site" for duplicate
                # purposes. It has to stay in this list, or the collector would
                # cheerfully re-add something the community just voted off.
                source="live-site-flagged" if flagged else "live-site",
                source_url=f"https://www.handgame.info/#event-{row.get('id')}",
            )
            events.append(event)
        log.info(
            "read %d existing events from the site (%d hidden by community flags)",
            len(events),
            hidden,
        )
        return events

    # ------------------------------------------------------------------
    def insert_event(
        self, event: Event, approved: Optional[bool] = True
    ) -> Optional[dict[str, Any]]:
        """Insert one reviewed event, using the same shape as the public form.

        The `events` table carries an `approved` column that admin.html sets,
        so a human-approved event is marked approved here too. If the column
        is missing, or a row-level policy will not let this key write it, the
        insert is retried without it rather than failing — matching exactly
        what the public submission form sends.
        """
        if not self.configured:
            raise SupabaseError("Supabase credentials are not set")
        if not event.is_publishable():
            raise SupabaseError(
                f"refusing to insert {event.title!r}: title, start_date and "
                "location are all required"
            )

        row = event.to_supabase_row()
        attempts: list[dict[str, Any]] = []
        if approved is not None:
            attempts.append({**row, "approved": approved})
        attempts.append(row)

        last_error = ""
        for index, payload in enumerate(attempts):
            try:
                resp = requests.post(
                    f"{self.url}/rest/v1/{TABLE}",
                    headers=self._headers({"Prefer": "return=representation"}),
                    json=[payload],
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                # Surfaced as SupabaseError so one network blip cannot abort a
                # publish run partway through and leave the rest uninserted.
                raise SupabaseError(f"could not reach Supabase: {exc}") from exc

            if resp.status_code < 400:
                try:
                    rows = resp.json()
                except ValueError:
                    return None  # inserted fine, just no body to report
                return rows[0] if isinstance(rows, list) and rows else None

            last_error = f"{resp.status_code}: {resp.text[:300]}"
            if index < len(attempts) - 1:
                log.info(
                    "insert with `approved` was rejected (%s); retrying without it",
                    last_error,
                )

        raise SupabaseError(f"insert failed {last_error}")

    # ------------------------------------------------------------------
    def upload_flyer(
        self, image_bytes: bytes, filename: str, content_type: str = "image/jpeg"
    ) -> Optional[str]:
        """Mirror a remote flyer into the site's own storage bucket.

        Worth doing: flyers hosted on someone else's server disappear, and a
        calendar full of broken images is worse than no images.
        """
        if not self.configured:
            raise SupabaseError("Supabase credentials are not set")
        resp = requests.post(
            f"{self.url}/storage/v1/object/{FLYER_BUCKET}/{filename}",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": content_type,
                "x-upsert": "false",
                "cache-control": "3600",
            },
            data=image_bytes,
            timeout=120,
        )
        if resp.status_code >= 400:
            log.error("flyer upload failed %s: %s", resp.status_code, resp.text[:300])
            return None
        return f"{self.url}/storage/v1/object/public/{FLYER_BUCKET}/{filename}"


def _as_date_str(value: Any) -> Optional[str]:
    if not value:
        return None
    return str(value)[:10]
