"""Agent (ReAct loop) tests with a fully mocked LLM — no Ollama call.

These exercise the orchestration logic itself: tool dispatch, scratchpad
feedback, self-correction, and the max-steps guard.
"""

from __future__ import annotations

import pytest

from app.agent.orchestrator import AgentOrchestrator
from app.agent.tools import build_default_tools
from app.core.exceptions import MaxStepsExceededError
from app.config import Settings
from app.schemas.agent import (
    AgentStep,
    FinalReport,
    KeywordGap,
    TechnicalFix,
    ToolCall,
)
from tests.conftest import FakeScraper


class ScriptedLLM:
    """Returns pre-scripted AgentStep objects and records the prompts seen."""

    def __init__(self, steps: list[AgentStep]) -> None:
        self.steps = steps
        self.prompts: list[str] = []
        self._i = 0

    async def generate_json(self, prompt, *, schema, system=None, temperature=None):
        self.prompts.append(prompt)
        step = self.steps[min(self._i, len(self.steps) - 1)]
        self._i += 1
        return step


REPORT = FinalReport(
    keyword_gaps=[KeywordGap(keyword="gluten free vegan cake", rationale="absent")],
    technical_fixes=[
        TechnicalFix(issue="meta too short", recommendation="rewrite", severity="high")
    ],
    rewritten_meta_description="Order fresh vegan cakes & gluten-free treats, delivered daily.",
)


def _orch(llm, settings: Settings) -> AgentOrchestrator:
    scraper = FakeScraper()
    return AgentOrchestrator(
        llm, scraper=scraper, tools=build_default_tools(scraper), settings=settings
    )


async def test_full_loop_scrape_analyze_report(settings: Settings) -> None:
    llm = ScriptedLLM(
        [
            AgentStep(
                thought="scrape",
                action=ToolCall(tool="scrape_url", args={"url": "https://shop.test"}),
            ),
            AgentStep(
                thought="analyze",
                action=ToolCall(
                    tool="analyze_keywords",
                    args={"target_keywords": ["vegan cake"]},
                ),
            ),
            AgentStep(thought="done", final_report=REPORT),
        ]
    )
    orch = _orch(llm, settings)
    result = await orch.run("Optimize my homepage for SEO")

    assert result.steps == 3
    assert result.report.rewritten_meta_description
    assert len(result.transcript) == 2
    # analyze used the scraped artifact and found the keyword present
    assert "Keyword analysis" in result.transcript[1].observation
    # scratchpad from step 1 is fed back into the step-2 prompt
    assert "Scraped https://shop.test/" in llm.prompts[1]


async def test_self_correction_on_bad_tool_order(settings: Settings) -> None:
    llm = ScriptedLLM(
        [
            AgentStep(
                thought="analyze first (mistake)",
                action=ToolCall(tool="analyze_keywords", args={}),
            ),
            AgentStep(
                thought="scrape first",
                action=ToolCall(tool="scrape_url", args={"url": "https://shop.test"}),
            ),
            AgentStep(thought="done", final_report=REPORT),
        ]
    )
    orch = _orch(llm, settings)
    result = await orch.run("Optimize my homepage for SEO")
    assert result.steps == 3
    assert "no text to analyze" in result.transcript[0].observation.lower()


async def test_max_steps_exceeded(settings: Settings) -> None:
    llm = ScriptedLLM(
        [
            AgentStep(
                thought="loop",
                action=ToolCall(tool="scrape_url", args={"url": "https://shop.test"}),
            )
        ]
    )
    settings = settings.model_copy(update={"agent_max_steps": 3})
    orch = _orch(llm, settings)
    with pytest.raises(MaxStepsExceededError):
        await orch.run("Optimize my homepage for SEO")


async def test_unknown_tool_yields_corrective_observation(settings: Settings) -> None:
    # Construct a ToolCall with an unregistered tool, bypassing the Literal
    # validation, to exercise the orchestrator's unknown-tool branch.
    bad = ToolCall.model_construct(tool="does_not_exist", args={})
    llm = ScriptedLLM(
        [
            AgentStep(thought="bad tool", action=bad),
            AgentStep(thought="done", final_report=REPORT),
        ]
    )
    orch = _orch(llm, settings)
    result = await orch.run("Optimize my homepage for SEO")
    assert result.steps == 2
    assert "unknown tool" in result.transcript[0].observation.lower()
