"""Minimal in-process event bus (spec §11: "events drive everything").

Lightweight and synchronous-friendly: subscribers are coroutines invoked when
an event is emitted. Good enough for the modular monolith; in Phase 2+ this can
be backed by Redis pub/sub or a real broker without changing call sites.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


# Canonical event names (spec §11).
CRAWL_COMPLETED = "CrawlCompleted"
AUDIT_COMPLETED = "AuditCompleted"
RECOMMENDATION_GENERATED = "RecommendationGenerated"

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Handler) -> None:
        self._handlers[event_name].append(handler)

    async def emit(self, event: Event) -> None:
        handlers = self._handlers.get(event.name, [])
        logger.info(
            "event %s -> %d handler(s) | %s", event.name, len(handlers), event.payload
        )
        if not handlers:
            return
        # Run handlers concurrently; one failing handler must not sink the rest.
        results = await asyncio.gather(
            *(h(event) for h in handlers), return_exceptions=True
        )
        for result in results:
            if isinstance(result, Exception):
                logger.warning("event handler for %s failed: %s", event.name, result)


# Process-wide bus.
bus = EventBus()
