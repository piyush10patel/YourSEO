"""Provider factory: pick a real vendor when configured, else the stub."""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.integrations.base import BacklinkProvider, KeywordProvider, SerpProvider
from app.integrations.stubs import (
    StubBacklinkProvider,
    StubKeywordProvider,
    StubSerpProvider,
)

logger = logging.getLogger(__name__)


def get_keyword_provider(settings: Settings | None = None) -> KeywordProvider:
    settings = settings or get_settings()
    if settings.keyword_provider != "stub":
        logger.warning(
            "keyword_provider=%s not implemented; using stub.",
            settings.keyword_provider,
        )
    return StubKeywordProvider()


def get_serp_provider(settings: Settings | None = None) -> SerpProvider:
    settings = settings or get_settings()
    if settings.serp_provider != "stub":
        logger.warning(
            "serp_provider=%s not implemented; using stub.", settings.serp_provider
        )
    return StubSerpProvider()


def get_backlink_provider(settings: Settings | None = None) -> BacklinkProvider:
    settings = settings or get_settings()
    if settings.backlink_provider != "stub":
        logger.warning(
            "backlink_provider=%s not implemented; using stub.",
            settings.backlink_provider,
        )
    return StubBacklinkProvider()
