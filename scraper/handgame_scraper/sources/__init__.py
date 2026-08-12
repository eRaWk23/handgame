"""Source registry.

To add a source: write a Source subclass, import it here, add it to REGISTRY,
and give it a block in config.yaml. Nothing else in the pipeline changes.
"""

from __future__ import annotations

from typing import Type

from .base import Source, safe_collect
from .calendars import CalendarFeedSource
from .inbox import InboxSource
from .reddit import RedditSource
from .websearch import WebSearchSource
from .webpages import WebPagesSource

REGISTRY: dict[str, Type[Source]] = {
    cls.name: cls
    for cls in (
        CalendarFeedSource,
        WebPagesSource,
        RedditSource,
        WebSearchSource,
        InboxSource,
    )
}

__all__ = ["REGISTRY", "Source", "safe_collect"]
