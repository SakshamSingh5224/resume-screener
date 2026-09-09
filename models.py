"""Pydantic schemas shared across the pipeline (used both for internal data
passing and as the structured-output contract if/when an LLM is used)."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class ResumeData(BaseModel):
    """Normalized, extracted view of a single resume."""
    source_file: str
    raw_text: str = ""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    github_url: Optional[str] = None
    github_username: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)      # raw project text blocks
    experience: List[str] = Field(default_factory=list)    # raw experience text blocks
    parse_error: Optional[str] = None                      # set if extraction failed


class EligibilityResult(BaseModel):
    eligible: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)
    python_evidence: List[str] = Field(default_factory=list)
    ai_evidence: List[str] = Field(default_factory=list)


class GitHubEnrichment(BaseModel):
    status: str  # "ok" | "missing" | "private_or_not_found" | "rate_limited" | "error"
    username: Optional[str] = None
    points: int = 0
    activity_points: int = 0
    repo_points: int = 0
    public_repos: int = 0
    recently_active: bool = False
    relevant_repo_count: int = 0
    summary: str = ""


class ScoreBreakdown(BaseModel):
    ai_project_depth: int = 0
    python_backend: int = 0
    cloud_fullstack: int = 0
    github: int = 0
    engineering_depth: int = 0

    @property
    def total(self) -> int:
        return (
            self.ai_project_depth
            + self.python_backend
            + self.cloud_fullstack
            + self.github
            + self.engineering_depth
        )


class CandidateResult(BaseModel):
    rank: Optional[int] = None
    candidate_name: str
    source_file: str
    eligible: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    total_score: int = 0
    score_breakdown: Optional[ScoreBreakdown] = None
    matched_skills: List[str] = Field(default_factory=list)
    project_summary: str = ""
    github_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    parse_error: Optional[str] = None


class BatchSummary(BaseModel):
    total_resumes: int = 0
    successfully_parsed: int = 0
    eligible: int = 0
    rejected: int = 0
    failed: int = 0


class ScreeningReport(BaseModel):
    batch_summary: BatchSummary
    ranked_eligible: List[CandidateResult]
    rejected_candidates: List[CandidateResult]
    failed_candidates: List[CandidateResult]
