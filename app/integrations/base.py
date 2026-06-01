"""Provider interfaces (Protocols) for external SEO data."""

from __future__ import annotations

from typing import Protocol, TypedDict


class KeywordMetrics(TypedDict):
    volume: int
    difficulty: float
    intent: str
    is_stub: bool


class BacklinkSummary(TypedDict):
    referring_domains: int
    total_backlinks: int
    domain_rating: int
    is_stub: bool


class KeywordProvider(Protocol):
    name: str

    def metrics(self, keywords: list[str]) -> dict[str, KeywordMetrics]:
        """Search volume / difficulty / intent per keyword."""
        ...


class SerpProvider(Protocol):
    name: str

    def positions(self, domain: str, keywords: list[str]) -> dict[str, int]:
        """Current SERP position (1-100) of ``domain`` for each keyword."""
        ...


class BacklinkProvider(Protocol):
    name: str

    def summary(self, domain: str) -> BacklinkSummary:
        """Backlink/authority summary for a domain."""
        ...
