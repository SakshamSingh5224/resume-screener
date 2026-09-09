"""
Optional LLM refinement layer (Section 6 of the brief).

Only invoked when USE_LLM=true. Judges whether the AI project is a thin
wrapper or a substantive system, and returns a bounded adjustment plus
evidence — the kind of judgment call keyword-matching can't make reliably.
If the call fails for any reason, the deterministic score from rubric.py is
used unchanged (fail gracefully, never abort the batch).
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from adapters.llm_client import call_llm_json
from config import THIN_WRAPPER_PENALTY_MAX, THIN_WRAPPER_PENALTY_MIN
from models import ResumeData

SYSTEM_PROMPT = (
    "You are a strict technical resume reviewer for an SDE-intern role that "
    "requires real Python engineering and genuine AI/agentic project depth. "
    "You are skeptical of resumes that merely name-drop frameworks (LangChain, "
    "RAG, agents) without evidence of real implementation (retrieval, state, "
    "orchestration, evaluation, meaningful business logic). Judge only from "
    "the text given; do not assume unstated details."
)


class LLMDepthJudgment(BaseModel):
    is_thin_wrapper: bool = Field(description="True if the AI project(s) look like a thin LLM API call with no real workflow")
    depth_score_0_to_40: int = Field(description="Your independent judgment of AI project depth, 0-40")
    evidence: List[str] = Field(default_factory=list, description="Short evidence strings supporting the judgment")
    concerns: List[str] = Field(default_factory=list, description="Short concerns, if any")


def llm_adjust_ai_depth(resume: ResumeData, deterministic_score: int) -> tuple[int, List[str], List[str]]:
    """Returns (final_score, extra_evidence, extra_concerns). Falls back to
    the deterministic score untouched if the LLM call is unavailable/fails."""
    project_text = "\n".join(resume.projects)
    experience_text = "\n".join(resume.experience)
    if not project_text and not experience_text:
        return deterministic_score, [], []

    user_prompt = (
        f"Projects section:\n{project_text}\n\n"
        f"Experience section:\n{experience_text}\n\n"
        "Score the AI/agentic project depth for this candidate from 0-40, "
        "and say whether it reads as a thin API wrapper."
    )

    judgment = call_llm_json(SYSTEM_PROMPT, user_prompt, LLMDepthJudgment, max_tokens=500)
    if judgment is None:
        return deterministic_score, [], []

    # Blend: average the deterministic and LLM scores rather than fully
    # trusting either — keeps the system explainable and bounded.
    blended = round((deterministic_score + judgment.depth_score_0_to_40) / 2)
    if judgment.is_thin_wrapper:
        blended = max(0, blended - THIN_WRAPPER_PENALTY_MIN)

    blended = max(0, min(40, blended))
    return blended, judgment.evidence, judgment.concerns
