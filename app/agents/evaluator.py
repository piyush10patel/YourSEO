"""Evaluator agent (spec §9): scores other agents' outputs."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AgentResult


def _score(result: AgentResult) -> float:
    return round(result.confidence * result.impact, 3)


class EvaluatorAgent(Agent):
    name = "evaluator"
    description = "Scores agent outputs by confidence x impact and ranks them."

    async def run(self, ctx: AgentContext) -> AgentResult:
        results: list[AgentResult] = ctx.inputs.get("results", [])
        return self.evaluate(results)

    def evaluate(self, results: list[AgentResult]) -> AgentResult:
        if not results:
            return self._result(
                confidence=0.3,
                impact=0.0,
                rationale="No agent results to evaluate.",
            )
        ranked = sorted(results, key=_score, reverse=True)
        avg = sum(_score(r) for r in results) / len(results)
        return self._result(
            confidence=0.9,
            impact=round(avg, 3),
            rationale=f"Scored {len(results)} agent outputs (mean score {avg:.2f}).",
            evidence=[f"{r.agent}: score={_score(r)}" for r in ranked],
            recommendations=[
                f"Prioritize the '{r.agent}' agent (score {_score(r)})."
                for r in ranked[:3]
            ],
        )
