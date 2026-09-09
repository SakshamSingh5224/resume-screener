"""
Hard eligibility filter (Section 3 of the brief).

Deliberately rule-based and LLM-free: eligibility must not depend on model
creativity, and a well-written but irrelevant resume must not sneak through.

A candidate is eligible only if BOTH hold:
  1. Python evidence: Python appears as a skill / project tech / work tech.
  2. AI evidence: at least one AI/LLM/RAG/agentic keyword appears in a
     PROJECT or EXPERIENCE block (a bare skills-list mention alone is not
     accepted as "meaningful" evidence per the brief).
"""
from __future__ import annotations

import re
from typing import List, Tuple

from config import AI_AGENTIC_KEYWORDS, PYTHON_KEYWORDS
from models import EligibilityResult, ResumeData


def _find_keyword_hits(text: str, keywords: List[str]) -> List[str]:
    text_lower = text.lower()
    hits = []
    for kw in keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b" if kw.isalnum() else re.escape(kw.lower())
        if re.search(pattern, text_lower):
            hits.append(kw)
    return hits


def check_eligibility(resume: ResumeData) -> EligibilityResult:
    skills_blob = " ".join(resume.skills)
    projects_blob = "\n".join(resume.projects)
    experience_blob = "\n".join(resume.experience)
    full_text = resume.raw_text or "\n".join([skills_blob, projects_blob, experience_blob])

    # --- Python evidence: skill, project tech, or work tech all count ---
    python_hits = _find_keyword_hits(
        "\n".join([skills_blob, projects_blob, experience_blob]) or full_text,
        PYTHON_KEYWORDS,
    )
    if not python_hits:
        # fall back to whole-document scan in case section splitting missed it
        python_hits = _find_keyword_hits(full_text, PYTHON_KEYWORDS)

    # --- AI/agentic evidence: must show up in a PROJECT or EXPERIENCE block,
    # not merely as a keyword dropped in the skills list. ---
    ai_hits_project_or_exp = _find_keyword_hits(
        "\n".join([projects_blob, experience_blob]), AI_AGENTIC_KEYWORDS
    )
    ai_hits_skills_only = _find_keyword_hits(skills_blob, AI_AGENTIC_KEYWORDS)

    rejection_reasons: List[str] = []
    if not python_hits:
        rejection_reasons.append("No evidence of Python stack (skills/projects/experience)")
    if not ai_hits_project_or_exp:
        if ai_hits_skills_only:
            rejection_reasons.append(
                "AI/agentic keywords appear only in the skills list, with no "
                "supporting project or work-experience evidence"
            )
        else:
            rejection_reasons.append("No AI/agentic project or implementation evidence")

    eligible = not rejection_reasons

    matched_skills = sorted(set(resume.skills)) if resume.skills else []

    return EligibilityResult(
        eligible=eligible,
        rejection_reasons=rejection_reasons,
        matched_skills=matched_skills,
        python_evidence=sorted(set(python_hits)),
        ai_evidence=sorted(set(ai_hits_project_or_exp)),
    )
