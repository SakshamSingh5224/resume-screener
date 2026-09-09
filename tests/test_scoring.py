import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import WEIGHTS
from models import ResumeData
from scoring.rubric import (
    score_ai_project_depth,
    score_cloud_fullstack,
    score_engineering_depth,
    score_python_backend,
)


def make_resume(skills=None, projects=None, experience=None, raw_text=""):
    return ResumeData(
        source_file="test.pdf",
        raw_text=raw_text,
        skills=skills or [],
        projects=projects or [],
        experience=experience or [],
    )


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_thin_wrapper_scores_lower_than_deep_agentic_project():
    thin = make_resume(
        skills=["Python"],
        projects=["Built a chatbot that calls the OpenAI API to answer questions."],
        raw_text="Python OpenAI API chatbot",
    )
    deep = make_resume(
        skills=["Python", "LangGraph"],
        projects=[
            "Built a multi-agent LangGraph system with retrieval, vector embeddings, "
            "persistent state, tool-calling, and an automated evaluation pipeline."
        ],
        raw_text="Python LangGraph multi-agent retrieval embeddings state tool-calling evaluation pipeline",
    )

    thin_score, _, _ = score_ai_project_depth(thin)
    deep_score, _, _ = score_ai_project_depth(deep)

    assert deep_score > thin_score
    assert deep_score <= WEIGHTS["ai_project_depth"]


def test_no_ai_project_scores_zero():
    resume = make_resume(skills=["Python"], projects=["Built a Django CRUD app."], raw_text="Python Django CRUD")
    score, _, concerns = score_ai_project_depth(resume)
    assert score == 0
    assert concerns


def test_python_backend_rewards_demonstrated_usage_over_keyword_list():
    keyword_only = make_resume(
        skills=["Python", "FastAPI", "PostgreSQL", "Redis"],
        projects=["Built a static portfolio website."],
        raw_text="Python FastAPI PostgreSQL Redis portfolio website",
    )
    demonstrated = make_resume(
        skills=["Python"],
        projects=["Built an async FastAPI backend with PostgreSQL and Redis caching for a real-time order system."],
        raw_text="Python async FastAPI PostgreSQL Redis caching real-time order system",
    )

    keyword_score, _, _ = score_python_backend(keyword_only)
    demonstrated_score, _, _ = score_python_backend(demonstrated)

    assert demonstrated_score > keyword_score


def test_cloud_fullstack_caps_at_weight():
    resume = make_resume(
        projects=["Deployed on GCP and AWS with Docker, Kubernetes, Terraform, and a React/Next.js frontend."],
        raw_text="GCP AWS Docker Kubernetes Terraform React Next.js",
    )
    score, _, _ = score_cloud_fullstack(resume)
    assert score <= WEIGHTS["cloud_fullstack"]


def test_engineering_depth_caps_at_weight():
    resume = make_resume(
        projects=[
            "Added unit tests, integration tests, caching, a Kafka message queue, "
            "observability with logging/monitoring, and concurrency handling with retries."
        ],
        raw_text="unit tests integration tests caching kafka observability logging monitoring concurrency retries",
    )
    score, _, _ = score_engineering_depth(resume)
    assert score <= WEIGHTS["engineering_depth"]
