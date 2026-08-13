"""Source adapter contract.

Adding a new source means writing one class with one method. Everything after
that — OCR, dedup, review, publishing — is shared.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ..fetch import Fetcher
from ..models import Event

log = logging.getLogger(__name__)


class Source:
    #: short identifier, also used in config.yaml
    name: str = "base"
    #: human-readable, shown in the review queue
    label: str = "Base source"
    #: set False for sources that need credentials or explicit opt-in
    enabled_by_default: bool = True

    def __init__(self, fetcher: Fetcher, settings: dict[str, Any] | None = None) -> None:
        self.fetch = fetcher
        self.settings = settings or {}
        self.log = logging.getLogger(f"source.{self.name}")

    def available(self) -> tuple[bool, str]:
        """Can this source run right now? Returns (ok, reason-if-not)."""
        return True, ""

    def collect(self) -> Iterator[Event]:
        """Yield candidate events. Never raise: log and stop instead.

        Adapters should populate whatever they can and leave the rest to the
        enrichment stage. Always set `source` and `source_url`.
        """
        raise NotImplementedError

    # -- helpers available to every adapter ----------------------------
    def _event(self, **kwargs: Any) -> Event:
        kwargs.setdefault("source", self.name)
        return Event(**kwargs)


def safe_collect(source: Source) -> list[Event]:
    """Run one adapter, swallowing failures so one bad site cannot kill a run."""
    ok, reason = source.available()
    if not ok:
        log.info("skipping %s: %s", source.name, reason)
        return []
    out: list[Event] = []
    try:
        for event in source.collect():
            if event and (event.title or event.flyer_url):
                out.append(event.tidy())
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        log.exception("source %s failed: %s", source.name, exc)
    log.info("%s produced %d candidates", source.name, len(out))
    return out
