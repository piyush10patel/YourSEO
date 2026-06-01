"""Deterministic stub providers.

No network, no keys. Values are derived from a hash of the input so they're
stable across runs (good for demos and tests) and clearly flagged ``is_stub``.
Swap these for real vendor clients once API keys are configured.
"""

from __future__ import annotations

import hashlib

from app.integrations.base import BacklinkSummary, KeywordMetrics

_INTENTS = ["informational", "commercial", "transactional", "navigational"]


def _seed(text: str) -> int:
    return int(hashlib.md5(text.lower().encode()).hexdigest(), 16)


class StubKeywordProvider:
    name = "stub"

    def metrics(self, keywords: list[str]) -> dict[str, KeywordMetrics]:
        out: dict[str, KeywordMetrics] = {}
        for kw in keywords:
            s = _seed(kw)
            out[kw] = KeywordMetrics(
                volume=100 + s % 9900,
                difficulty=round(s % 100 / 100, 2),
                intent=_INTENTS[s % len(_INTENTS)],
                is_stub=True,
            )
        return out


class StubSerpProvider:
    name = "stub"

    def positions(self, domain: str, keywords: list[str]) -> dict[str, int]:
        return {kw: 1 + _seed(domain + "|" + kw) % 100 for kw in keywords}


class StubBacklinkProvider:
    name = "stub"

    def summary(self, domain: str) -> BacklinkSummary:
        s = _seed(domain or "unknown")
        referring = s % 500
        return BacklinkSummary(
            referring_domains=referring,
            total_backlinks=referring * (3 + s % 20),
            domain_rating=s % 100,
            is_stub=True,
        )
