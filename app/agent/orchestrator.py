"""AgentOrchestrator — a minimal ReAct loop for SEO optimization.

Loop:
    1. THINK   -- ask the LLM (structured `AgentStep`) what to do next, given
                  the objective and the running scratchpad.
    2. ACT     -- if it chose a tool, execute it and capture the observation.
    3. OBSERVE -- append (thought, action, observation) to the scratchpad and
                  feed it back on the next THINK.
    4. STOP    -- when the LLM returns a `final_report` instead of an action,
                  or when `agent_max_steps` is hit (raises MaxStepsExceededError).

The LLM dependency is duck-typed: anything exposing
``async generate_json(prompt, *, schema, system, temperature) -> BaseModel``
works (the real one is `app.services.ollama.OllamaClient`), which keeps the
loop trivially testable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.config import Settings, get_settings
from app.core.exceptions import MaxStepsExceededError
from app.schemas.agent import AgentStep, FinalReport, ToolCall
from app.services.scraper import ScraperService

from .tools import RunContext, Tool, build_default_tools

logger = logging.getLogger(__name__)


class SupportsGenerateJSON(Protocol):
    async def generate_json(  # pragma: no cover - structural type
        self,
        prompt: str,
        *,
        schema: type[AgentStep],
        system: str | None = ...,
        temperature: float | None = ...,
    ) -> AgentStep: ...


@dataclass
class Turn:
    thought: str
    action: ToolCall | None
    observation: str


@dataclass
class RunResult:
    objective: str
    report: FinalReport
    steps: int
    transcript: list[Turn] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(
        self,
        llm: SupportsGenerateJSON,
        *,
        scraper: ScraperService | None = None,
        tools: dict[str, Tool] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.scraper = scraper or ScraperService(settings=self.settings)
        self.tools = tools or build_default_tools(self.scraper)

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    async def run(self, objective: str) -> RunResult:
        ctx = RunContext(scraper=self.scraper)
        transcript: list[Turn] = []
        max_steps = self.settings.agent_max_steps
        system_prompt = self._system_prompt()

        for step in range(1, max_steps + 1):
            prompt = self._render_prompt(objective, transcript, step, max_steps)
            decision = await self.llm.generate_json(
                prompt,
                schema=AgentStep,
                system=system_prompt,
                temperature=self.settings.agent_temperature,
            )
            logger.info("Step %d/%d — thought: %s", step, max_steps, decision.thought)

            # STOP: the loop terminates only on a final report.
            if decision.final_report is not None:
                logger.info("Agent produced final report after %d step(s).", step)
                return RunResult(
                    objective=objective,
                    report=decision.final_report,
                    steps=step,
                    transcript=transcript,
                )

            # ACT: run the chosen tool, or feed back a corrective observation.
            if decision.action is not None:
                observation = await self._execute(decision.action, ctx)
            else:
                observation = (
                    "You returned neither an action nor a final_report. Choose "
                    "exactly one: call a tool, or emit final_report when done."
                )

            transcript.append(
                Turn(
                    thought=decision.thought,
                    action=decision.action,
                    observation=observation,
                )
            )

        raise MaxStepsExceededError(
            f"Agent did not produce a final report within {max_steps} steps.",
            detail=f"objective={objective!r}",
        )

    # ------------------------------------------------------------------ #
    # ACT
    # ------------------------------------------------------------------ #
    async def _execute(self, action: ToolCall, ctx: RunContext) -> str:
        tool = self.tools.get(action.tool)
        if tool is None:
            available = ", ".join(self.tools)
            return f"Error: unknown tool {action.tool!r}. Available tools: {available}."

        logger.info("Executing tool %s with args=%s", action.tool, action.args)
        observation = await tool(action.args, ctx)

        # Keep the context window bounded — large tool outputs are truncated
        # before being fed back to the model.
        limit = self.settings.agent_observation_char_limit
        if len(observation) > limit:
            observation = observation[:limit] + "\n...[truncated]"
        return observation

    # ------------------------------------------------------------------ #
    # Prompt construction
    # ------------------------------------------------------------------ #
    def _system_prompt(self) -> str:
        tool_docs = "\n".join(
            f"- {t.name}: {t.description}\n    args: {t.args_hint}"
            for t in self.tools.values()
        )
        report_schema = json.dumps(FinalReport.model_json_schema(), indent=2)
        return (
            "You are an autonomous SEO optimization agent operating in a "
            "ReAct (Reason + Act) loop. At each turn you think, then take ONE "
            "action, until you can deliver a final report.\n\n"
            "AVAILABLE TOOLS:\n"
            f"{tool_docs}\n\n"
            "RULES:\n"
            "1. Each turn, output a 'thought' and EITHER an 'action' (to call a "
            "tool) OR a 'final_report' — never both.\n"
            "2. Begin by scraping the target page, then analyze its keywords "
            "before drawing conclusions. Base findings on real observations, "
            "not assumptions.\n"
            "3. When you have enough evidence, stop and output 'final_report' "
            "with no action. The report MUST contain keyword_gaps, "
            "technical_fixes, and a rewritten_meta_description, conforming to "
            "this schema:\n"
            f"{report_schema}\n"
        )

    def _render_prompt(
        self, objective: str, transcript: list[Turn], step: int, max_steps: int
    ) -> str:
        parts = [
            f"OBJECTIVE: {objective}",
            f"(Step {step} of {max_steps}.)",
        ]
        if not transcript:
            parts.append("\nNo actions taken yet. Decide your first step.")
        else:
            parts.append("\nSCRATCHPAD (your work so far):")
            for i, turn in enumerate(transcript, 1):
                action_str = (
                    f"{turn.action.tool}({json.dumps(turn.action.args)})"
                    if turn.action
                    else "(none)"
                )
                parts.append(
                    f"\n[{i}] Thought: {turn.thought}\n"
                    f"    Action: {action_str}\n"
                    f"    Observation: {turn.observation}"
                )
        parts.append(
            "\nDecide the next step. If you have enough information, output the "
            "final_report now."
        )
        return "\n".join(parts)
