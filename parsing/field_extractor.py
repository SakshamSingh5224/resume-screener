"""
Deterministic extraction of structured fields from raw resume text.

Resumes have wildly inconsistent layouts, so this is intentionally
heuristic/regex-based rather than assuming fixed section headers. This is the
extraction path used by default (no LLM call required, fully offline-testable).

An optional LLM-backed extractor (parsing/llm_field_extractor.py) can replace
or supplement this when USE_LLM=true — see adapters/llm_client.py.
"""
from __future__ import annotations

import re
from typing import List, Optional

from models import ResumeData

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s()]{8,}\d)")
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9\-_]+)", re.IGNORECASE)

# Section header patterns (case-insensitive, allow trailing colon/whitespace)
SECTION_HEADERS = {
    "skills": r"(technical\s+)?skills?|technolog(y|ies)",
    "projects": r"projects?",
    "experience": r"(work\s+)?experience|internships?|employment",
    "education": r"education|academic",
    "certifications": r"certifications?|certificates?",
}


def _split_sections(text: str) -> dict:
    """Split resume text into rough sections keyed by header name.

    Works line-by-line: a short line that STARTS WITH a known header keyword
    starts a new section. This deliberately does not require the header
    keyword to be the ENTIRE line, because real resumes use compound headers
    like "Internship / Training" or "Work Experience & Projects" that a
    strict full-line match would miss entirely — silently merging that whole
    section's content (including AI/agentic evidence) into whatever section
    came before it.

    To avoid false-positives on ordinary bullet sentences that happen to
    start with a header word (e.g. "Experience with Docker..."), a candidate
    header line must also: be short, not end in sentence-ending punctuation,
    and not start with a bullet marker.
    """
    lines = text.split("\n")
    sections: dict = {}
    current_key = "header"
    current_lines: List[str] = []

    header_patterns = {k: re.compile(rf"^\s*({v})\b", re.IGNORECASE) for k, v in SECTION_HEADERS.items()}

    for line in lines:
        stripped = line.strip()
        matched_key = None
        looks_like_bullet = stripped.startswith(("•", "-", "*", "◦"))
        looks_like_sentence = stripped.endswith((".", ",", ";"))
        if 0 < len(stripped) <= 45 and not looks_like_bullet and not looks_like_sentence:
            for key, pattern in header_patterns.items():
                if pattern.match(stripped):
                    matched_key = key
                    break
        if matched_key:
            sections[current_key] = "\n".join(current_lines).strip()
            current_key = matched_key
            current_lines = []
        else:
            current_lines.append(line)

    sections[current_key] = "\n".join(current_lines).strip()
    return sections


def _guess_name(text: str) -> Optional[str]:
    """The name is almost always the first non-empty line that isn't an
    email/phone/URL and looks like a short proper-noun-ish line."""
    for line in text.split("\n")[:6]:
        stripped = line.strip()
        if not stripped:
            continue
        if EMAIL_RE.search(stripped) or "http" in stripped.lower() or PHONE_RE.search(stripped):
            continue
        words = stripped.split()
        if 1 <= len(words) <= 5 and all(w[0].isupper() or not w[0].isalpha() for w in words if w):
            return stripped
    return None


def _extract_bullet_blocks(section_text: str) -> List[str]:
    """Break a section into paragraph-ish blocks (one per project/role),
    splitting on blank lines or lines that look like a new title/date row."""
    if not section_text:
        return []
    blocks = re.split(r"\n\s*\n", section_text)
    blocks = [b.strip() for b in blocks if b.strip()]
    if len(blocks) <= 1:
        # Fall back to splitting on lines that look like a new entry title
        # (short line, possibly followed by a date range).
        lines = [l for l in section_text.split("\n") if l.strip()]
        blocks = []
        current: List[str] = []
        for line in lines:
            is_title_like = len(line.strip()) < 90 and re.search(r"\d{4}|Present", line)
            if is_title_like and current:
                blocks.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))
    return blocks


def extract_fields(source_file: str, raw_text: str) -> ResumeData:
    sections = _split_sections(raw_text)

    email_match = EMAIL_RE.search(raw_text)
    github_match = GITHUB_RE.search(raw_text)

    skills_text = sections.get("skills", "")
    # Skills are often comma/bullet/pipe separated, sometimes with a
    # "Category: item, item" prefix per line — strip that label before
    # splitting so "Languages: TypeScript" yields "TypeScript", not the
    # whole labelled clause.
    skill_lines = re.split(r"[\n]", skills_text)
    raw_items: List[str] = []
    for line in skill_lines:
        line = re.sub(r"^\s*[A-Za-z][A-Za-z /&]{2,30}:\s*", "", line)
        # Split on comma/pipe/bullet, but not on commas INSIDE balanced
        # parentheses (e.g. "AWS (EC2, S3) — Fundamentals" -> one item, not
        # "AWS (EC2" + "S3) — Fundamentals").
        raw_items.extend(re.split(r"[|•]|,(?![^(]*\))", line))

    skills = [
        s.strip(" •-\t()")
        for s in raw_items
        if s.strip(" •-\t()") and len(s.strip()) < 40
    ]

    return ResumeData(
        source_file=source_file,
        raw_text=raw_text,
        name=_guess_name(raw_text),
        email=email_match.group(0) if email_match else None,
        phone=(PHONE_RE.search(raw_text).group(0).strip() if PHONE_RE.search(raw_text) else None),
        github_url=(f"https://github.com/{github_match.group(1)}" if github_match else None),
        github_username=github_match.group(1) if github_match else None,
        skills=skills,
        projects=_extract_bullet_blocks(sections.get("projects", "")),
        experience=_extract_bullet_blocks(sections.get("experience", "")),
    )
