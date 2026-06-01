"""Topic clustering (spec §15): keyword universe -> topic clusters.

Default is a deterministic *lexical* clustering (no model needed): each keyword
is grouped under its most distinctive shared token ("head term"), which becomes
the cluster's topic. When embeddings are enabled (Ollama), a semantic variant
can replace this — the API and persistence are identical either way.

Re-running is idempotent: existing clusters/topics for the project are cleared
and rebuilt.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db import repositories as repo
from app.db.models import Cluster, Topic

_STOP = frozenset(
    "the a an of for to in on and or with your you how what best top free online "
    "vs near me buy cheap".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 2]


def _head_term(tokens: list[str], doc_freq: Counter) -> str:
    """The token best representing a keyword: most shared, then longest."""
    if not tokens:
        return "misc"
    return max(tokens, key=lambda t: (doc_freq[t], len(t)))


async def cluster_keywords(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> list[Cluster]:
    project = await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")

    keywords = await repo.list_keywords(
        session, project_id=project_id, organization_id=organization_id
    )
    if not keywords:
        return []

    # Document frequency of tokens across the keyword universe.
    doc_freq: Counter = Counter()
    kw_tokens: dict[uuid.UUID, list[str]] = {}
    for kw in keywords:
        toks = list(dict.fromkeys(_tokens(kw.keyword)))
        kw_tokens[kw.id] = toks
        doc_freq.update(set(toks))

    # Idempotent rebuild: clear existing clusters + topics (keyword.cluster_id
    # and cluster.topic_id are SET NULL on delete).
    await session.execute(delete(Cluster).where(Cluster.project_id == project_id))
    await session.execute(delete(Topic).where(Topic.project_id == project_id))
    await session.flush()

    # Group keywords by head term.
    groups: dict[str, list] = {}
    for kw in keywords:
        head = _head_term(kw_tokens[kw.id], doc_freq)
        groups.setdefault(head, []).append(kw)

    clusters: list[Cluster] = []
    for head, members in sorted(groups.items()):
        topic = Topic(project_id=project_id, name=head)
        session.add(topic)
        await session.flush()
        cluster = Cluster(project_id=project_id, topic=head, topic_id=topic.id)
        session.add(cluster)
        await session.flush()
        for kw in members:
            kw.cluster_id = cluster.id
        clusters.append(cluster)

    await session.flush()
    return clusters
