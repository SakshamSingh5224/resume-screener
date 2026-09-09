import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eligibility.filters import check_eligibility
from models import ResumeData


def make_resume(skills=None, projects=None, experience=None, raw_text=""):
    return ResumeData(
        source_file="test.pdf",
        raw_text=raw_text,
        skills=skills or [],
        projects=projects or [],
        experience=experience or [],
    )


def test_pure_js_candidate_is_rejected():
    resume = make_resume(
        skills=["JavaScript", "React", "Next.js", "Node.js"],
        projects=["Built a React dashboard with Next.js and Tailwind CSS."],
        raw_text="JavaScript React Next.js Node.js dashboard",
    )
    result = check_eligibility(resume)
    assert result.eligible is False
    assert any("Python" in r for r in result.rejection_reasons)


def test_python_only_no_ai_is_rejected():
    resume = make_resume(
        skills=["Python", "Django", "PostgreSQL"],
        projects=["Built a Django e-commerce backend with PostgreSQL."],
        raw_text="Python Django PostgreSQL e-commerce backend",
    )
    result = check_eligibility(resume)
    assert result.eligible is False
    assert any("AI" in r for r in result.rejection_reasons)


def test_python_plus_agentic_project_is_eligible():
    resume = make_resume(
        skills=["Python", "FastAPI", "LangChain"],
        projects=["Built a LangGraph multi-agent RAG pipeline with tool-calling and FastAPI backend."],
        raw_text="Python FastAPI LangChain LangGraph multi-agent RAG pipeline tool-calling",
    )
    result = check_eligibility(resume)
    assert result.eligible is True
    assert result.rejection_reasons == []


def test_ai_keyword_only_in_skills_list_is_rejected():
    """AI keyword dropped only into the skills list, with no supporting
    project/experience evidence, should NOT pass eligibility."""
    resume = make_resume(
        skills=["Python", "LangChain", "RAG"],
        projects=["Built a Flask to-do list app with CRUD operations."],
        raw_text="Python LangChain RAG Flask to-do list CRUD",
    )
    result = check_eligibility(resume)
    assert result.eligible is False


def test_compound_section_header_is_recognized():
    """Regression test: a header like 'Internship / Training' must be
    recognized as a real section boundary, not silently merged into whatever
    section preceded it (which previously caused AI/Python evidence living
    under such a section to be missed by eligibility)."""
    from parsing.field_extractor import extract_fields

    raw_text = (
        "Jane Doe\n"
        "jane@example.com\n"
        "Technical Skills\n"
        "Java, MySQL, HTML\n"
        "Internship / Training\n"
        "AI Research Intern 2025\n"
        "Built a LangChain-based RAG chatbot in Python over internal docs.\n"
        "Education\n"
        "B.E. Computer Science\n"
    )
    resume = extract_fields("test.pdf", raw_text)
    assert any("langchain" in e.lower() or "rag" in e.lower() for e in resume.experience)
    result = check_eligibility(resume)
    assert result.eligible is True


def test_js_and_python_ai_candidate_is_not_rejected_for_having_js():
    """Presence of JS/React should not disqualify a candidate who ALSO
    satisfies Python + AI requirements."""
    resume = make_resume(
        skills=["Python", "React", "LangChain"],
        projects=["Built a full-stack app: React frontend, Python/FastAPI backend running a LangChain RAG agent."],
        raw_text="Python React LangChain RAG agent FastAPI",
    )
    result = check_eligibility(resume)
    assert result.eligible is True
