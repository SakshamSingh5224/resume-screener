"""
Central configuration: scoring weights, thresholds, keyword lexicons, and
environment variable names. Nothing business-logic-y lives here — only knobs.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _load_dotenv_if_present() -> None:
    """Load KEY=VALUE pairs from a .env file (next to this file) into
    os.environ, if one exists.

    v3 bug: `.env.example` told users to `cp .env.example .env` and fill it
    in, but nothing anywhere actually loaded that file — every value below
    was read straight from `os.environ.get(...)`, which only sees real
    process environment variables, never a plain .env file on disk. A user
    could fill in GITHUB_TOKEN correctly and still see the "not set"
    warning, because it genuinely never reached the process.

    Uses python-dotenv when available; falls back to a small manual parser
    if the dependency is missing, so a broken/skipped `pip install` doesn't
    silently disable .env loading again.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv_if_present()


# ---------------------------------------------------------------------------
# Environment / secrets (never hard-code credentials)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
USE_LLM = os.environ.get("USE_LLM", "false").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 100 — enforced by a test)
# ---------------------------------------------------------------------------
WEIGHTS = {
    "ai_project_depth": 40,
    "python_backend": 30,
    "cloud_fullstack": 15,
    "github": 10,
    "engineering_depth": 5,
}

# Penalty range applied when an "AI project" looks like a thin API wrapper
THIN_WRAPPER_PENALTY_MIN = 5
THIN_WRAPPER_PENALTY_MAX = 15

GITHUB_TIMEOUT_SECONDS = 6
# Bounded concurrency for enrichment calls. Kept low (2) by default because
# GitHub applies a *secondary* abuse-detection rate limit to bursts of
# concurrent requests, independent of the primary 60/hr (unauth) or 5000/hr
# (auth) quota — a burst of 4+ simultaneous requests can trip it even when
# plenty of primary quota remains. Override with GITHUB_MAX_WORKERS if you
# have a token and want more throughput.
GITHUB_MAX_WORKERS = int(os.environ.get("GITHUB_MAX_WORKERS", "2"))
GITHUB_RECENT_ACTIVITY_DAYS = 180
GITHUB_CACHE_PATH = Path(os.environ.get("GITHUB_CACHE_PATH", ".cache/github_cache.json"))
GITHUB_CACHE_TTL_SECONDS = int(os.environ.get("GITHUB_CACHE_TTL_SECONDS", str(24 * 3600)))  # 24h default

# Retry behavior for GitHub's primary (403/429 w/ X-RateLimit-Remaining: 0)
# and secondary (403 abuse-detection) rate limits. Bounded so a rate-limited
# run degrades gracefully instead of hanging the batch.
GITHUB_MAX_RETRIES = int(os.environ.get("GITHUB_MAX_RETRIES", "2"))
GITHUB_RETRY_BASE_DELAY_SECONDS = 2.0
GITHUB_MAX_RETRY_WAIT_SECONDS = 20.0

# ---------------------------------------------------------------------------
# Keyword lexicons used by the rule-based eligibility filter and the
# deterministic scoring scaffold. Kept here (not scattered in logic) so a
# reviewer can audit "what counts as evidence" at a glance.
# ---------------------------------------------------------------------------

PYTHON_KEYWORDS: List[str] = [
    "python", "django", "flask", "fastapi", "pandas", "numpy", "pytest",
    "pydantic", "sqlalchemy", "celery", "asyncio", "scikit-learn", "sklearn",
    "pyspark", "jupyter",
]

AI_AGENTIC_KEYWORDS: List[str] = [
    "langchain", "langgraph", "llamaindex", "llama-index", "google adk",
    "adk", "rag", "retrieval augmented", "retrieval-augmented",
    "vector search", "vector database", "vector db", "embeddings",
    "embedding model", "tool-calling", "tool calling", "function calling",
    "multi-agent", "multi agent", "agentic", "autonomous agent",
    "llm", "large language model", "openai api", "gpt-4", "gpt-3",
    "claude api", "anthropic api", "gemini api", "hugging face",
    "huggingface", "transformers", "fine-tun", "prompt engineering",
    "chatbot", "semantic search", "faiss", "pinecone", "chroma", "weaviate",
    "crewai", "autogen", "llamacpp", "ollama",
]

BACKEND_KEYWORDS: List[str] = [
    "fastapi", "django", "flask", "async", "await", "asyncio",
    "postgresql", "postgres", "redis", "celery", "rest api", "graphql",
    "microservice", "sqlalchemy", "orm",
]

CLOUD_KEYWORDS: List[str] = [
    "gcp", "google cloud", "aws", "azure", "docker", "kubernetes", "k8s",
    "ci/cd", "terraform", "cloud run", "lambda", "ec2", "s3", "vertex ai",
]

FULLSTACK_SUPPORT_KEYWORDS: List[str] = ["react", "next.js", "nextjs", "react.js"]

ENGINEERING_DEPTH_KEYWORDS: List[str] = [
    "unit test", "integration test", "pytest", "test coverage",
    "architecture", "caching", "cache", "message queue", "queue",
    "kafka", "rabbitmq", "observability", "logging", "monitoring",
    "concurrency", "concurrent", "thread", "multiprocessing",
    "failure handling", "retry", "circuit breaker", "rate limit",
    "load balanc", "scalab",
]

# Phrases that indicate a project is likely a thin LLM-API wrapper rather
# than a substantive system (used as a *signal*, not an automatic verdict —
# the scorer looks for the ABSENCE of substantive-depth keywords nearby).
THIN_WRAPPER_HINTS: List[str] = [
    "simple chatbot", "basic chatbot", "wrapper around", "calls the openai api",
    "just calls", "single api call", "tutorial", "followed a tutorial",
    "clone of", "todo app", "boilerplate",
]

SUBSTANTIVE_DEPTH_KEYWORDS: List[str] = [
    "retrieval", "vector", "embedding", "state", "orchestrat", "workflow",
    "evaluation", "eval pipeline", "tool-calling", "tool calling",
    "multi-agent", "multi agent", "memory", "planning", "pipeline",
    "database", "postgres", "redis", "caching", "async", "queue",
    "guardrail", "structured output", "function calling",
]
