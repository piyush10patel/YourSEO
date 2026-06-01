"""Specialized worker agents (spec §9).

Each is deliberately narrow and *data-grounded* — it reasons over what's already
persisted (audits, recommendations, keywords, clusters, pages) rather than
free-associating. That keeps output trustworthy (no hallucinated metrics) and
the whole team fast and deterministic.
"""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult
from app.db import repositories as repo
from app.integrations.providers import get_backlink_provider

# Recommendation types grouped by the agent that "owns" them.
_LINKING_TYPES = {"orphan_page", "broken_link"}
_ONPAGE_TYPES = {
    "missing_title",
    "missing_meta",
    "thin_content",
    "missing_h1",
    "multiple_h1",
    "canonical_mismatch",
    "image_alt",
    "duplicate_title",
    "duplicate_meta",
}


def _cap(value: float) -> float:
    return max(0.0, min(1.0, value))


class AuditAgent(Agent):
    name = "audit"
    description = "Analyzes the latest crawl/audit and summarizes site health."

    async def run(self, ctx: AgentContext) -> AgentResult:
        audits = await repo.list_audits(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        recs = await repo.list_recommendations(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        if not audits:
            return self._result(
                confidence=0.2,
                impact=0.2,
                rationale="No audit has run yet — crawl the site first.",
            )
        latest = audits[0]
        top = recs[:5]
        impact = _cap((100 - latest.overall_score) / 100)
        return self._result(
            confidence=0.85,
            impact=impact,
            rationale=f"Latest audit scored {latest.overall_score}/100 "
            f"(grade {latest.grade}) with {len(recs)} open findings.",
            evidence=[f"{r.type}: {r.title}" for r in top],
            recommendations=[r.title for r in top],
        )


class KeywordAgent(Agent):
    name = "keyword"
    description = "Finds keyword/cluster opportunities and gaps."

    async def run(self, ctx: AgentContext) -> AgentResult:
        keywords = await repo.list_keywords(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        clusters = await repo.list_clusters(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        if not keywords:
            return self._result(
                confidence=0.2,
                impact=0.3,
                rationale="No keywords yet — import a keyword universe to analyze.",
                recommendations=["Add target keywords to the project."],
            )
        sizes: dict = {}
        for kw in keywords:
            sizes[kw.cluster_id] = sizes.get(kw.cluster_id, 0) + 1
        thin = [c for c in clusters if sizes.get(c.id, 0) <= 1]
        recs = [
            f"Build out the '{c.topic}' topic cluster (only "
            f"{sizes.get(c.id, 0)} keyword(s))."
            for c in thin
        ]
        return self._result(
            confidence=0.7,
            impact=_cap(len(thin) / max(1, len(clusters))),
            rationale=f"{len(keywords)} keywords across {len(clusters)} clusters; "
            f"{len(thin)} are under-developed.",
            evidence=[f"{c.topic}: {sizes.get(c.id, 0)} kw" for c in clusters[:8]],
            recommendations=recs or ["Keyword coverage looks balanced."],
        )


class InternalLinkingAgent(Agent):
    name = "internal_linking"
    description = "Surfaces orphan pages and broken internal links."

    async def run(self, ctx: AgentContext) -> AgentResult:
        recs = await repo.list_recommendations(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        linking = [r for r in recs if r.type in _LINKING_TYPES]
        pages = await repo.list_pages(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        if not pages:
            return self._result(
                confidence=0.2,
                impact=0.2,
                rationale="No crawl data — run a crawl to map internal links.",
            )
        return self._result(
            confidence=0.8,
            impact=_cap(len(linking) / 10),
            rationale=f"Found {len(linking)} internal-link issues across "
            f"{len(pages)} crawled pages.",
            evidence=[r.title for r in linking[:8]],
            recommendations=[r.title for r in linking]
            or ["Internal linking looks healthy."],
        )


class OptimizationAgent(Agent):
    name = "optimization"
    description = "Recommends on-page fixes (titles, meta, headings, content)."

    async def run(self, ctx: AgentContext) -> AgentResult:
        recs = await repo.list_recommendations(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        onpage = [r for r in recs if r.type in _ONPAGE_TYPES]
        if not onpage:
            return self._result(
                confidence=0.5,
                impact=0.2,
                rationale="No on-page issues recorded (or no audit yet).",
                recommendations=["Run a crawl/audit to surface on-page fixes."],
            )
        onpage.sort(key=lambda r: r.priority, reverse=True)
        return self._result(
            confidence=0.8,
            impact=_cap(len(onpage) / 10),
            rationale=f"{len(onpage)} on-page issues to fix, prioritized.",
            evidence=[f"{r.type}: {r.title}" for r in onpage[:8]],
            recommendations=[r.title for r in onpage[:10]],
        )


class ContentAgent(Agent):
    name = "content"
    description = "Drafts content briefs for the project's topic clusters."

    async def run(self, ctx: AgentContext) -> AgentResult:
        clusters = await repo.list_clusters(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        keywords = await repo.list_keywords(
            ctx.session, project_id=ctx.project_id, organization_id=ctx.organization_id
        )
        if not clusters:
            return self._result(
                confidence=0.2,
                impact=0.3,
                rationale="No topic clusters yet — add keywords and cluster them.",
            )
        by_cluster: dict = {}
        for kw in keywords:
            by_cluster.setdefault(kw.cluster_id, []).append(kw.keyword)
        # Brief for the richest cluster.
        target = max(clusters, key=lambda c: len(by_cluster.get(c.id, [])))
        terms = by_cluster.get(target.id, [])
        brief = [
            f"Title: The Complete Guide to {target.topic.title()}",
            "Suggested sections: " + ", ".join(terms[:6]) if terms else "Outline TBD",
            f"Primary keyword: {target.topic}",
        ]
        return self._result(
            confidence=0.6,
            impact=_cap(len(terms) / 10),
            rationale=f"Drafted a content brief for the '{target.topic}' cluster.",
            evidence=terms[:8],
            recommendations=brief,
        )


class AuthorityAgent(Agent):
    name = "authority"
    description = "Backlink / authority analysis via the configured provider."

    async def run(self, ctx: AgentContext) -> AgentResult:
        project = await repo.get_project(
            ctx.session,
            project_id=ctx.project_id,
            organization_id=ctx.organization_id,
        )
        domain = (project.domain if project else None) or "unknown"
        provider = get_backlink_provider(ctx.settings)
        summary = provider.summary(domain)
        is_stub = summary.get("is_stub", False)
        # Stub data is illustrative only — keep confidence low and say so.
        confidence = 0.3 if is_stub else 0.8
        note = (
            " (STUB data — connect a real provider for accurate numbers)"
            if is_stub
            else ""
        )
        return self._result(
            confidence=confidence,
            impact=_cap(summary["referring_domains"] / 500),
            rationale=f"{domain}: {summary['referring_domains']} referring domains, "
            f"DR {summary['domain_rating']}{note}.",
            evidence=[
                f"referring_domains={summary['referring_domains']}",
                f"total_backlinks={summary['total_backlinks']}",
                f"domain_rating={summary['domain_rating']}",
            ],
            recommendations=[
                "Pursue backlinks from authoritative, topically-relevant sites.",
                "Reclaim lost/broken backlinks and unlinked brand mentions.",
            ],
        )
