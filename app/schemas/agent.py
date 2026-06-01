"""Pydantic models for the ReAct agent.

Two roles:
  * `AgentStep` is the schema the LLM must emit at every turn of the loop —
    a thought plus *either* a tool call *or* the final report.
  * `FinalReport` is the terminal artifact the loop is driving toward.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# The tools the agent is allowed to invoke. Kept as a Literal so the JSON
# schema (and thus Ollama's structured-output constraint) rejects made-up
# tool names.
ToolName = Literal["scrape_url", "analyze_keywords"]


class ToolCall(BaseModel):
    tool: ToolName = Field(..., description="Which tool to invoke.")
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for the tool, e.g. {'url': 'https://...'}.",
    )


class KeywordGap(BaseModel):
    keyword: str = Field(
        ..., description="A keyword/phrase the page should target but under-serves."
    )
    rationale: str = Field(
        ..., description="Why this is an opportunity, grounded in the analysis."
    )


class TechnicalFix(BaseModel):
    issue: str = Field(..., description="The on-page/technical SEO problem observed.")
    recommendation: str = Field(..., description="Concrete action to resolve it.")
    severity: Literal["low", "medium", "high"] = "medium"


class FinalReport(BaseModel):
    """The terminal SEO report the loop stops on."""

    keyword_gaps: list[KeywordGap] = Field(
        ..., description="Keywords/phrases the page is missing or under-using."
    )
    technical_fixes: list[TechnicalFix] = Field(
        ..., description="Prioritised technical/on-page fixes."
    )
    rewritten_meta_description: str = Field(
        ...,
        description="An improved meta description, ideally 150-160 characters.",
    )


class AgentStep(BaseModel):
    """One ReAct turn: reasoning + exactly one of action / final_report."""

    thought: str = Field(
        ..., description="Brief reasoning about the current state and next move."
    )
    action: ToolCall | None = Field(
        default=None,
        description="The tool to call next. Omit (null) when you are done.",
    )
    final_report: FinalReport | None = Field(
        default=None,
        description="The completed report. Provide ONLY when the objective is met; omit otherwise.",
    )
