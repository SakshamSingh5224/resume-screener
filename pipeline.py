"""Orchestrates the full screening pipeline end to end."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

from config import GITHUB_MAX_WORKERS, USE_LLM
from eligibility.filters import check_eligibility
from github.enrichment import enrich_from_username
from ingestion.extractors import ExtractionError, extract_text
from ingestion.loader import discover_resume_files
from models import (
    BatchSummary,
    CandidateResult,
    ScoreBreakdown,
    ScreeningReport,
)
from parsing.field_extractor import extract_fields
from scoring.rubric import (
    score_ai_project_depth,
    score_cloud_fullstack,
    score_engineering_depth,
    score_python_backend,
)

logger = logging.getLogger("resume_screener")


def _score_and_build_result(resume, eligibility, github_result) -> CandidateResult:
    ai_score, ai_evidence, ai_concerns = score_ai_project_depth(resume)

    if USE_LLM:
        try:
            from scoring.llm_scorer import llm_adjust_ai_depth
            ai_score, extra_evidence, extra_concerns = llm_adjust_ai_depth(resume, ai_score)
            ai_evidence += extra_evidence
            ai_concerns += extra_concerns
        except Exception as e:  # noqa: BLE001 - LLM path must never break scoring
            logger.warning("LLM scoring adjustment failed for %s: %s", resume.source_file, e)

    py_score, py_evidence, py_concerns = score_python_backend(resume)
    cloud_score, cloud_evidence, cloud_concerns = score_cloud_fullstack(resume)
    eng_score, eng_evidence, eng_concerns = score_engineering_depth(resume)

    breakdown = ScoreBreakdown(
        ai_project_depth=ai_score,
        python_backend=py_score,
        cloud_fullstack=cloud_score,
        github=github_result.points,
        engineering_depth=eng_score,
    )

    strengths = [e for e in (ai_evidence + py_evidence + cloud_evidence + eng_evidence) if e]
    concerns = [c for c in (ai_concerns + py_concerns + cloud_concerns + eng_concerns) if c]

    project_summary = (
        resume.projects[0][:220].replace("\n", " ") if resume.projects else "No project section detected"
    )

    return CandidateResult(
        candidate_name=resume.name or Path(resume.source_file).stem,
        source_file=resume.source_file,
        eligible=True,
        total_score=breakdown.total,
        score_breakdown=breakdown,
        matched_skills=eligibility.matched_skills,
        project_summary=project_summary,
        github_summary=github_result.summary,
        strengths=strengths[:5],
        concerns=concerns[:5],
    )


def run_pipeline(input_dir: str) -> ScreeningReport:
    files = discover_resume_files(input_dir)

    parsed_ok = []
    failed_candidates: List[CandidateResult] = []

    for path in files:
        try:
            raw_text = extract_text(path)
            if USE_LLM:
                try:
                    from parsing.llm_field_extractor import extract_fields_with_llm_fallback
                    resume = extract_fields_with_llm_fallback(str(path), raw_text)
                except Exception as e:  # noqa: BLE001 - LLM path must never break extraction
                    logger.warning("LLM extraction failed for %s, falling back to regex: %s", path, e)
                    resume = extract_fields(str(path), raw_text)
            else:
                resume = extract_fields(str(path), raw_text)
            parsed_ok.append(resume)
        except ExtractionError as e:
            logger.warning("Failed to parse %s: %s", path, e)
            failed_candidates.append(CandidateResult(
                candidate_name=path.stem,
                source_file=str(path),
                eligible=False,
                parse_error=str(e),
            ))
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
            logger.warning("Unexpected error parsing %s: %s", path, e)
            failed_candidates.append(CandidateResult(
                candidate_name=path.stem,
                source_file=str(path),
                eligible=False,
                parse_error=f"Unexpected error: {e}",
            ))

    eligible_resumes = []
    rejected_candidates: List[CandidateResult] = []

    for resume in parsed_ok:
        eligibility = check_eligibility(resume)
        if eligibility.eligible:
            eligible_resumes.append((resume, eligibility))
        else:
            rejected_candidates.append(CandidateResult(
                candidate_name=resume.name or Path(resume.source_file).stem,
                source_file=resume.source_file,
                eligible=False,
                rejection_reasons=eligibility.rejection_reasons,
                matched_skills=eligibility.matched_skills,
            ))

    # GitHub enrichment: bounded concurrency, one lookup per unique username.
    github_results = {}
    with ThreadPoolExecutor(max_workers=GITHUB_MAX_WORKERS) as executor:
        future_to_resume = {
            executor.submit(enrich_from_username, resume.github_username): resume.source_file
            for resume, _ in eligible_resumes
        }
        for future in as_completed(future_to_resume):
            source_file = future_to_resume[future]
            try:
                github_results[source_file] = future.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("GitHub enrichment failed for %s: %s", source_file, e)
                from models import GitHubEnrichment
                github_results[source_file] = GitHubEnrichment(status="error", summary=str(e))

    ranked_eligible: List[CandidateResult] = []
    for resume, eligibility in eligible_resumes:
        github_result = github_results.get(resume.source_file)
        if github_result is None:
            from models import GitHubEnrichment
            github_result = GitHubEnrichment(status="missing", summary="No GitHub profile found on resume")
        result = _score_and_build_result(resume, eligibility, github_result)
        ranked_eligible.append(result)

    ranked_eligible.sort(key=lambda c: c.total_score, reverse=True)
    for i, candidate in enumerate(ranked_eligible, start=1):
        candidate.rank = i

    summary = BatchSummary(
        total_resumes=len(files),
        successfully_parsed=len(parsed_ok),
        eligible=len(ranked_eligible),
        rejected=len(rejected_candidates),
        failed=len(failed_candidates),
    )

    return ScreeningReport(
        batch_summary=summary,
        ranked_eligible=ranked_eligible,
        rejected_candidates=rejected_candidates,
        failed_candidates=failed_candidates,
    )
