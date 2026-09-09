"""
GitHub enrichment (Section 5 of the brief).

Lightweight and defensive: any failure (network, rate limit, private/missing
profile) results in a recorded status, never an exception that aborts the
batch. Results are cached both in-memory (within a run) and on disk (across
runs) to avoid burning API quota re-checking the same usernames every time
the pipeline is re-run over an overlapping candidate pool.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import requests

from config import (
    GITHUB_CACHE_PATH,
    GITHUB_CACHE_TTL_SECONDS,
    GITHUB_MAX_RETRIES,
    GITHUB_MAX_RETRY_WAIT_SECONDS,
    GITHUB_RECENT_ACTIVITY_DAYS,
    GITHUB_RETRY_BASE_DELAY_SECONDS,
    GITHUB_TIMEOUT_SECONDS,
    GITHUB_TOKEN,
)
from models import GitHubEnrichment

logger = logging.getLogger("resume_screener.github")

_CACHE: Dict[str, GitHubEnrichment] = {}  # in-memory, this-process only
_disk_cache_loaded = False
_warned_no_token = False


def _warn_no_token_once() -> None:
    global _warned_no_token
    if not GITHUB_TOKEN and not _warned_no_token:
        _warned_no_token = True
        logger.warning(
            "GITHUB_TOKEN is not set. GitHub enrichment will run against the "
            "unauthenticated limit (~60 requests/hour, shared across a batch "
            "of resumes and any prior runs this hour), so scores may come "
            "back as 0 with a 'rate_limited' status even for real profiles. "
            "Set GITHUB_TOKEN in .env to raise this to 5000/hour."
        )


AI_PYTHON_REPO_HINTS = [
    "python", "langchain", "langgraph", "rag", "agent", "llm", "ml",
    "ai", "fastapi", "django", "flask", "torch", "tensorflow",
]


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


# ---------------------------------------------------------------------------
# On-disk cache: a single JSON file keyed by username, each entry stamped
# with a fetch time so entries older than GITHUB_CACHE_TTL_SECONDS are
# treated as stale and refetched. Kept intentionally simple (no DB) per the
# assignment's "no database required" guardrail.
# ---------------------------------------------------------------------------

def _load_disk_cache() -> dict:
    global _disk_cache_loaded
    if not GITHUB_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(GITHUB_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_to_disk_cache(username: str, result: GitHubEnrichment) -> None:
    try:
        GITHUB_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        disk_cache = _load_disk_cache()
        disk_cache[username] = {
            "fetched_at": time.time(),
            "data": result.model_dump(),
        }
        GITHUB_CACHE_PATH.write_text(json.dumps(disk_cache, indent=2))
    except OSError:
        pass  # caching is a nice-to-have; never fail the run over it


def _get_from_disk_cache(username: str) -> Optional[GitHubEnrichment]:
    disk_cache = _load_disk_cache()
    entry = disk_cache.get(username)
    if not entry:
        return None
    age = time.time() - entry.get("fetched_at", 0)
    if age > GITHUB_CACHE_TTL_SECONDS:
        return None  # stale, refetch
    try:
        return GitHubEnrichment(**entry["data"])
    except (TypeError, ValueError):
        return None


def _get_with_retry(url: str, params: Optional[dict] = None) -> requests.Response:
    """GET with rate-limit-aware retry.

    GitHub returns 403/429 for two different things: the primary quota
    (60/hr unauth, 5000/hr auth) being exhausted, and a *secondary* abuse
    burst limit. Both are transient. Rather than giving up immediately (the
    v3 bug: a single 403 made the whole candidate score github=0), honor
    `Retry-After` / `X-RateLimit-Reset` when present and retry up to
    GITHUB_MAX_RETRIES times, capped so one slow candidate can't stall the
    whole batch for long.
    """
    last_resp: Optional[requests.Response] = None
    for attempt in range(GITHUB_MAX_RETRIES + 1):
        resp = requests.get(url, headers=_headers(), timeout=GITHUB_TIMEOUT_SECONDS, params=params)
        if resp.status_code not in (403, 429):
            return resp
        last_resp = resp
        if attempt >= GITHUB_MAX_RETRIES:
            break

        retry_after = resp.headers.get("Retry-After")
        reset_at = resp.headers.get("X-RateLimit-Reset")
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if retry_after is not None:
            wait = float(retry_after)
        elif remaining == "0" and reset_at is not None:
            wait = max(0.0, float(reset_at) - time.time())
        else:
            # Secondary/abuse-detection limit with no explicit header:
            # short exponential backoff.
            wait = GITHUB_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
        wait = min(wait, GITHUB_MAX_RETRY_WAIT_SECONDS)
        logger.info("GitHub rate-limited (attempt %d/%d), retrying in %.1fs", attempt + 1, GITHUB_MAX_RETRIES, wait)
        time.sleep(wait)
    return last_resp


def enrich_from_username(username: str) -> GitHubEnrichment:
    if not username:
        return GitHubEnrichment(status="missing", summary="No GitHub profile found on resume")

    _warn_no_token_once()

    if username in _CACHE:
        return _CACHE[username]

    cached = _get_from_disk_cache(username)
    if cached is not None:
        _CACHE[username] = cached
        return cached

    result = _fetch(username)
    _CACHE[username] = result
    if result.status in ("ok", "private_or_not_found"):
        # Only cache stable outcomes on disk; don't persist transient
        # failures (rate_limited/error) so the next run retries them fresh.
        _save_to_disk_cache(username, result)
    return result


def _fetch(username: str) -> GitHubEnrichment:
    base = "https://api.github.com"
    try:
        user_resp = _get_with_retry(f"{base}/users/{username}")
    except requests.RequestException as e:
        return GitHubEnrichment(status="error", username=username, summary=f"GitHub request failed: {e}")

    if user_resp.status_code == 404:
        return GitHubEnrichment(status="private_or_not_found", username=username,
                                 summary="GitHub profile not found or private")
    if user_resp.status_code in (403, 429):
        return GitHubEnrichment(status="rate_limited", username=username,
                                 summary="GitHub API rate-limited this request")
    if user_resp.status_code != 200:
        return GitHubEnrichment(status="error", username=username,
                                 summary=f"GitHub API returned {user_resp.status_code}")

    user_data = user_resp.json()
    public_repos = user_data.get("public_repos", 0)

    # --- Recent activity: public events endpoint ---
    activity_points = 0
    recently_active = False
    try:
        events_resp = _get_with_retry(f"{base}/users/{username}/events/public")
        if events_resp.status_code == 200:
            events = events_resp.json()
            if events:
                latest = events[0].get("created_at")
                if latest:
                    latest_dt = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    days_ago = (datetime.now(timezone.utc) - latest_dt).days
                    if days_ago <= GITHUB_RECENT_ACTIVITY_DAYS:
                        recently_active = True
                        activity_points = 5 if days_ago <= 30 else 3
                    else:
                        activity_points = 1
    except requests.RequestException:
        pass  # activity score just stays 0; not a hard failure

    # --- Maintained / relevant repos ---
    repo_points = 0
    relevant_repo_count = 0
    try:
        repos_resp = _get_with_retry(
            f"{base}/users/{username}/repos",
            params={"sort": "updated", "per_page": 30},
        )
        if repos_resp.status_code == 200:
            repos = repos_resp.json()
            for repo in repos:
                blob = f"{repo.get('name', '')} {repo.get('description') or ''} {repo.get('language') or ''}".lower()
                if any(hint in blob for hint in AI_PYTHON_REPO_HINTS):
                    relevant_repo_count += 1
            repo_points = min(5, relevant_repo_count * 2)
    except requests.RequestException:
        pass

    total_points = min(10, activity_points + repo_points)
    summary_parts = []
    summary_parts.append("Recently active" if recently_active else "No recent public activity")
    summary_parts.append(f"{public_repos} public repos")
    if relevant_repo_count:
        summary_parts.append(f"{relevant_repo_count} Python/AI-relevant repos")

    return GitHubEnrichment(
        status="ok",
        username=username,
        points=total_points,
        activity_points=activity_points,
        repo_points=repo_points,
        public_repos=public_repos,
        recently_active=recently_active,
        relevant_repo_count=relevant_repo_count,
        summary="; ".join(summary_parts),
    )
