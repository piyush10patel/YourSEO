"""Planner agent (spec §9): runs the team and builds a prioritized roadmap."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult


class PlannerAgent(Agent):
    name = "planner"
    description = "Runs the agent team and assembles a prioritized SEO roadmap."

    async def run(self, ctx: AgentContext) -> AgentResult:
        # Lazy imports avoid an import cycle (registry imports workers).
        from app.agents.evaluator import EvaluatorAgent, _score
        from app.agents.registry import worker_classes

        results: list[AgentResult] = []
        for agent_cls in worker_classes().values():
            results.append(await agent_cls().run(ctx))

        evaluation = EvaluatorAgent().evaluate(results)

        # Roadmap: top recommendations from each agent, ordered by agent score.
        ordered = sorted(results, key=_score, reverse=True)
        roadmap: list[str] = []
        for result in ordered:
            for rec in result.recommendations[:3]:
                roadmap.append(f"[{result.agent}] {rec}")

        return self._result(
            confidence=0.85,
            impact=evaluation.impact,
            rationale=f"Synthesized a roadmap from {len(results)} specialist agents.",
            evidence=[
                f"{r.agent}: conf={r.confidence}, impact={r.impact}" for r in ordered
            ],
            recommendations=roadmap[:15],
        )
