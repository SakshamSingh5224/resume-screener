"""
Optional LLM-backed field extraction (Section 6 of the brief).

Only invoked when USE_LLM=true. Uses a structured Pydantic schema so the
response is predictable and testable, per the brief's explicit instruction
to use structured output for LLM extraction.

Falls back to the deterministic regex extractor (parsing/field_extractor.py)
whenever the LLM call is unavailable or fails — extraction must never
depend entirely on the LLM being up, per the brief's fail-gracefully
requirement ("Your application should still fail gracefully if one model
call fails for one resume").
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from adapters.llm_client import call_llm_json
from models import ResumeData
from parsing.field_extractor import extract_fields as regex_extract_fields

SYSTEM_PROMPT = (
    "You extract structured fields from a candidate's resume text for a "
    "hiring pipeline. Extract only what is explicitly present in the text — "
    "never invent or infer missing details. If a field isn't present, leave "
    "it empty."
)


class LLMExtractedFields(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    github_username: Optional[str] = None
    skills: List[str] = Field(default_factory=list, description="Clean, individual skill/technology names, deduplicated")
    projects: List[str] = Field(default_factory=list, description="One string per distinct project, summarizing what was built and its tech stack")
    experience: List[str] = Field(default_factory=list, description="One string per distinct role/internship, summarizing responsibilities and technologies used")


def extract_fields_with_llm_fallback(source_file: str, raw_text: str) -> ResumeData:
    """Primary entrypoint when USE_LLM=true: try the LLM extraction first,
    fall back to the regex extractor on any failure."""
    regex_result = regex_extract_fields(source_file, raw_text)

    user_prompt = f"Resume text:\n\n{raw_text[:8000]}"  # bound prompt size
    llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt, LLMExtractedFields, max_tokens=1500)

    if llm_result is None:
        return regex_result  # graceful fallback, no exception raised

    # Prefer LLM fields when present, but keep the regex fallback for any
    # field the LLM left empty, so a partially-successful LLM call still
    # improves on regex-only rather than discarding good regex output.
    return ResumeData(
        source_file=source_file,
        raw_text=raw_text,
        name=llm_result.name or regex_result.name,
        email=llm_result.email or regex_result.email,
        phone=regex_result.phone,  # phone regex is reliable enough; not worth an LLM field
        github_url=regex_result.github_url,
        github_username=llm_result.github_username or regex_result.github_username,
        skills=llm_result.skills or regex_result.skills,
        projects=llm_result.projects or regex_result.projects,
        experience=llm_result.experience or regex_result.experience,
    )
