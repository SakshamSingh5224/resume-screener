"""
Deterministic scoring scaffold (Section 4 of the brief).

This is the scorer used by default — fully offline, testable, explainable.
When USE_LLM=true, scoring/llm_scorer.py layers a bounded adjustment on top
of this baseline (see pipeline.py), specifically to judge project *depth*
(thin API wrapper vs. real system) — something keyword matching alone can't
reliably tell.

Design choice: keyword presence alone earns partial credit; keyword presence
INSIDE a project/experience block (real usage, not just a skills list) earns
the rest. This directly implements "prefer evidence showing how it was used"
and "don't award full points just because a framework name appears in the
skills section."
"""
from __future__ import annotations

import re
from typing import List, Tuple

from config import (
    AI_AGENTIC_KEYWORDS,
    BACKEND_KEYWORDS,
    CLOUD_KEYWORDS,
    ENGINEERING_DEPTH_KEYWORDS,
    FULLSTACK_SUPPORT_KEYWORDS,
    SUBSTANTIVE_DEPTH_KEYWORDS,
    THIN_WRAPPER_HINTS,
    THIN_WRAPPER_PENALTY_MAX,
    THIN_WRAPPER_PENALTY_MIN,
    WEIGHTS,
)
from models import ResumeData


def _contains_any(text: str, keywords: List[str]) -> List[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def score_ai_project_depth(resume: ResumeData) -> Tuple[int, List[str], List[str]]:
    """40 pts. Rewards real agentic/RAG systems; penalizes thin wrappers."""
    cap = WEIGHTS["ai_project_depth"]
    project_and_exp_text = "\n".join(resume.projects + resume.experience)

    ai_hits = _contains_any(project_and_exp_text, AI_AGENTIC_KEYWORDS)
    if not ai_hits:
        return 0, [], ["No AI/agentic evidence in projects or experience"]

    # Base credit for having a genuine AI project at all.
    score = 15
    evidence = [f"AI/agentic technology used in a project: {', '.join(sorted(set(ai_hits))[:5])}"]

    depth_hits = _contains_any(project_and_exp_text, SUBSTANTIVE_DEPTH_KEYWORDS)
    # Up to +25 more for depth signals (retrieval, state, orchestration, eval, etc.)
    depth_bonus = min(25, len(set(depth_hits)) * 5)
    score += depth_bonus
    if depth_hits:
        evidence.append(f"Substantive system depth signals: {', '.join(sorted(set(depth_hits))[:6])}")

    concerns: List[str] = []
    thin_hits = _contains_any(project_and_exp_text, THIN_WRAPPER_HINTS)
    if thin_hits or not depth_hits:
        penalty = THIN_WRAPPER_PENALTY_MIN if depth_hits else THIN_WRAPPER_PENALTY_MAX
        score -= penalty
        concerns.append(
            "AI project reads as a thin LLM/API wrapper with limited workflow, "
            "retrieval, state, or evaluation depth"
        )

    return _clamp(score, 0, cap), evidence, concerns


def score_python_backend(resume: ResumeData) -> Tuple[int, List[str], List[str]]:
    """30 pts. Python + FastAPI/async/Postgres/Redis, weighted toward
    evidence in projects/experience over a bare skills mention."""
    cap = WEIGHTS["python_backend"]
    skills_blob = " ".join(resume.skills)
    project_and_exp_text = "\n".join(resume.projects + resume.experience)

    has_python_skill = "python" in skills_blob.lower() or "python" in resume.raw_text.lower()
    if not has_python_skill:
        return 0, [], ["No Python evidence"]

    score = 10  # base credit for Python itself
    evidence = ["Python listed as a core skill"]

    backend_hits_used = _contains_any(project_and_exp_text, BACKEND_KEYWORDS)
    backend_hits_skills = _contains_any(skills_blob, BACKEND_KEYWORDS)

    # Evidence of actual usage in a project/role is worth much more than a
    # keyword sitting in the skills list.
    score += min(15, len(set(backend_hits_used)) * 4)
    score += min(5, len(set(backend_hits_skills)) * 1)

    if backend_hits_used:
        evidence.append(f"Backend stack used in practice: {', '.join(sorted(set(backend_hits_used))[:6])}")
    concerns = []
    if not backend_hits_used and backend_hits_skills:
        concerns.append("Backend technologies appear only as skill-list keywords, not demonstrated in projects")

    return _clamp(score, 0, cap), evidence, concerns


def score_cloud_fullstack(resume: ResumeData) -> Tuple[int, List[str], List[str]]:
    """15 pts. Cloud/deployment primary; React/Next.js as supporting signal only."""
    cap = WEIGHTS["cloud_fullstack"]
    project_and_exp_text = "\n".join(resume.projects + resume.experience)

    cloud_hits = _contains_any(project_and_exp_text, CLOUD_KEYWORDS)
    fullstack_hits = _contains_any(project_and_exp_text, FULLSTACK_SUPPORT_KEYWORDS)

    score = min(12, len(set(cloud_hits)) * 4)
    # Full-stack tech only counts as a *supporting* signal, and only if some
    # cloud/deployment evidence already exists (per the brief).
    if cloud_hits:
        score += min(3, len(set(fullstack_hits)) * 1)

    evidence = []
    if cloud_hits:
        evidence.append(f"Cloud/deployment evidence: {', '.join(sorted(set(cloud_hits)))}")
    if fullstack_hits and cloud_hits:
        evidence.append(f"Supporting full-stack signal: {', '.join(sorted(set(fullstack_hits)))}")

    concerns = []
    if not cloud_hits:
        concerns.append("No cloud/deployment evidence (Docker, GCP/AWS, etc.)")

    return _clamp(score, 0, cap), evidence, concerns


def score_engineering_depth(resume: ResumeData) -> Tuple[int, List[str], List[str]]:
    """5 pts. Testing, architecture, caching, queues, observability, concurrency."""
    cap = WEIGHTS["engineering_depth"]
    project_and_exp_text = "\n".join(resume.projects + resume.experience)

    hits = _contains_any(project_and_exp_text, ENGINEERING_DEPTH_KEYWORDS)
    score = min(cap, len(set(hits)) * 2)

    evidence = [f"Engineering depth signals: {', '.join(sorted(set(hits))[:5])}"] if hits else []
    concerns = [] if hits else ["No explicit testing/architecture/observability signals found"]

    return _clamp(score, 0, cap), evidence, concerns
