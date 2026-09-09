# AI Resume Screening & Ranking System

A CLI pipeline that ingests a folder of resumes (PDF, with DOCX/TXT as
bonus), applies a hard Python + AI/agentic eligibility filter, scores
eligible candidates against a 100-point rubric, enriches scores with public
GitHub activity, and outputs a ranked, evidence-backed shortlist.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit if you want LLM scoring or a GitHub token
```

No API keys are required to run the default (fully deterministic) mode.
`.env` is loaded automatically (via `python-dotenv`, with a manual fallback
if that package isn't installed) — you don't need to separately export
environment variables in your shell.

## Run

```bash
python main.py --input ./resumes --output ./output/results.json
```

Add `--verbose` for debug logging. Run tests with:

```bash
pytest tests/ -v
```

### Optional: FastAPI interface

```bash
uvicorn app:app --reload
```

- `POST /screen` with body `{"input_dir": "resumes"}` — runs the pipeline, returns `{"run_id": "...", "batch_summary": {...}}`
- `GET /results/{run_id}` — full report for that run
- `GET /results` — full report for the most recent run
- `GET /health` — liveness check

## Output

`results.json` contains:
- `batch_summary` — total/parsed/eligible/rejected/failed counts.
- `ranked_eligible_candidates` — sorted by `total_score` desc, each with a
  full `score_breakdown`, matched skills, project summary, GitHub summary,
  strengths, and concerns.
- `rejected_candidates` — with explicit `rejection_reasons`.
- `failed_candidates` — resumes that could not be parsed, with the error.

On the provided 50-resume set (deterministic mode): **50 parsed, 30
eligible, 20 rejected, 0 failed.** (Eligible/rejected counts can shift by a
couple of candidates between environments if `USE_LLM=true`, since the LLM
extraction pass sometimes recovers a project/experience block the regex
splitter missed — the underlying rule-based eligibility logic itself doesn't
change.)

> **v3 → v4 fix note:** in the previous run, ~30% of eligible candidates with
> a real GitHub profile still scored `github: 0` with a `"GitHub API
> rate-limited this request"` status. Root cause: (1) no `GITHUB_TOKEN` was
> set, so the batch ran against GitHub's unauthenticated limit (~60
> requests/hour, and each candidate costs up to 3 requests), and (2) a single
> 403/429 was treated as final instead of being retried. See "GitHub
> scoring" below for the fix.

## Design Decisions

**Filtering strategy.** Eligibility is 100% rule-based (`eligibility/filters.py`),
deliberately kept out of the LLM path so a well-written but irrelevant resume
can't talk its way past the filter. Python evidence is accepted from
anywhere (skills, projects, or experience). AI/agentic evidence, however, is
only accepted if it appears inside a **project or experience** block — a
bare mention in the skills list (e.g. "RAG" dropped into a skills line with
no project behind it) is explicitly rejected, per the brief's instruction not
to reward keyword-only profiles. JS/React/Java presence never disqualifies a
candidate who also satisfies the Python + AI requirement.

**Scoring strategy.** Deterministic-first (`scoring/rubric.py`), so the
system is fully explainable and testable without any network or API
dependency. Each of the five weighted categories differentiates between a
keyword merely being *listed* versus being *used in a project/role*: usage
in a project earns most of the points, a bare skill-list mention earns much
less. AI project depth specifically checks for "substantive depth" signals
(retrieval, state, orchestration, evaluation, memory, etc.) and applies a
5–15 point penalty when a project reads like a thin LLM-API wrapper with
none of those signals — directly implementing the brief's penalty rule.

**LLM usage.** An optional layer (`scoring/llm_scorer.py` +
`adapters/llm_client.py`) can blend in an LLM's independent judgment of AI
project depth, using a structured Pydantic schema for the response. It's
gated behind `USE_LLM=true` and an `ANTHROPIC_API_KEY`, and if the call
fails for any reason it silently falls back to the deterministic score — it
never blocks or crashes the batch. The provider call lives entirely behind
one function (`call_llm_json`) so swapping providers touches one file.

**GitHub scoring.** Username is regex-extracted from the resume text. One
bounded-timeout (6s) call each to the public `/users/{u}`, `/events/public`,
and `/repos` endpoints, run with a bounded thread pool (`GITHUB_MAX_WORKERS`,
default 2 — see below) so enrichment doesn't serialize on 50 resumes. Recent
activity (≤30 days: 5pts, ≤180 days: 3pts) plus up to 5pts for repos whose
name/description/language match Python/AI keywords, capped at 10 total. Any
*terminal* failure — 404 (private/missing), network error — is recorded as a
status string and the candidate is still scored and ranked; GitHub never
gates eligibility, per the brief.

*Rate-limit handling (fixed in this version).* GitHub applies two different
403/429s: the primary quota (60/hr unauthenticated, 5000/hr with a token)
and a separate secondary "abuse detection" limit triggered by bursts of
concurrent requests, independent of remaining primary quota. `github/
enrichment.py::_get_with_retry` now retries a 403/429 up to
`GITHUB_MAX_RETRIES` times (default 2), honoring `Retry-After` /
`X-RateLimit-Reset` when GitHub sends them and falling back to short
exponential backoff when it doesn't, capped at `GITHUB_MAX_RETRY_WAIT_SECONDS`
per wait so one throttled candidate can't stall the batch. `GITHUB_MAX_WORKERS`
was also dropped from 4 to 2 by default to reduce how often the secondary
limit triggers in the first place. Only after retries are exhausted does a
candidate get `status="rate_limited"` / `github: 0` — a real, load-bearing
degradation path, not a silent bug. The single highest-leverage fix, though,
is operational: **set `GITHUB_TOKEN`** in `.env` — an unauthenticated 60/hr
budget is easy to exhaust across a 50-resume batch (up to 3 requests each)
plus any prior test runs in the same hour. The pipeline now logs a one-time
warning at startup if no token is configured.

**Reliability.** Every per-resume step (extraction, parsing, eligibility,
scoring, enrichment) is wrapped so a single malformed file can't take down
the batch — it's recorded under `failed_candidates` with the underlying
error message instead.

## If I Had More Time

The items below were originally planned as future improvements and have
since been implemented in this version:

1. **Better section segmentation.** The original regex-based header matcher
   required a header line to match a known keyword exactly (e.g. plain
   "Experience"), which silently merged any section with a compound header
   — "Internship / Training", "Work Experience & Projects" — into whatever
   section preceded it. This was a real correctness bug: it could hide
   genuine AI/Python evidence sitting in an internship block and cause a
   qualified candidate to be wrongly rejected. Fixed to match on the header
   keyword at the start of a short, non-bulleted, non-sentence-like line
   instead of requiring an exact full-line match. On the provided 50-resume
   set this moved 3 previously wrongly-rejected candidates into the
   eligible pool, with zero regressions (see
   `tests/test_eligibility.py::test_compound_section_header_is_recognized`).

2. **Always-on LLM extraction pass.** Implemented in
   `parsing/llm_field_extractor.py`. Gated behind `USE_LLM=true`, uses a
   structured Pydantic schema for the response, and merges LLM output over
   the regex baseline field-by-field — any field the LLM leaves empty or
   the call fails entirely falls back to the regex extractor untouched, so
   extraction quality can only improve, never regress, relative to the
   deterministic path.

3. **Persistent GitHub cache across runs.** Implemented in
   `github/enrichment.py`. A small on-disk JSON cache
   (`.cache/github_cache.json` by default, path/TTL configurable via env
   vars) keyed by username, with a 24-hour TTL. Only stable outcomes (`ok`,
   `private_or_not_found`) are persisted — transient failures
   (`rate_limited`, `error`) are intentionally not cached, so the next run
   retries them fresh rather than baking in a temporary outage.

4. **A lightweight FastAPI wrapper.** Implemented in `app.py`.
   `POST /screen {"input_dir": "..."}` runs the pipeline and returns a
   `run_id`; `GET /results/{run_id}` and `GET /results` (latest) return the
   full report. Kept intentionally thin — all logic still lives in
   `pipeline.run_pipeline()`, this file is routing and serialization only.

5. **Resilient GitHub enrichment.** An earlier run showed roughly 30% of
   eligible candidates with a real GitHub profile scoring `github: 0` with
   a `rate_limited` status — a single 403/429 from GitHub was treated as
   final instead of being retried, and the batch ran unauthenticated with
   no `GITHUB_TOKEN` set. Added a retry helper in `github/enrichment.py`
   that retries a 403/429 up to `GITHUB_MAX_RETRIES` times, honoring
   `Retry-After` / `X-RateLimit-Reset` when GitHub sends them and falling
   back to short exponential backoff otherwise. Also dropped
   `GITHUB_MAX_WORKERS` from 4 to 2 by default, since GitHub's secondary
   abuse-detection limit triggers on request bursts independent of
   remaining quota, and added a one-time startup warning when no
   `GITHUB_TOKEN` is configured, so the fix is visible instead of silently
   producing zeros.

6. **`.env` file loading.** `.env.example` told users to run
   `cp .env.example .env` and fill it in, but nothing in the codebase
   actually loaded that file — every setting was read with
   `os.environ.get(...)`, which only sees real process environment
   variables, not a plain `.env` file on disk. A user could fill in
   `GITHUB_TOKEN` exactly right and still see the "not set" warning,
   because the value never reached the process. `config.py` now loads
   `.env` automatically at startup, via `python-dotenv` with a manual
   `KEY=VALUE` parser as a fallback if that package is unavailable. Covered
   by `tests/test_dotenv_loading.py`.

### Remaining ideas, if there were still more time

- A layout-aware (not just regex) fallback for section segmentation on
  resumes with genuinely unconventional formatting (multi-column layouts,
  no clear headers at all).
- Batch/async LLM calls for the extraction and scoring passes so
  `USE_LLM=true` runs don't serialize one resume at a time.
- Proactively call GitHub's `/rate_limit` endpoint once at batch start and,
  if remaining quota is clearly insufficient for the number of GitHub
  profiles found, surface a batch-level warning up front instead of
  discovering it candidate-by-candidate.
- A `/screen` request option to run against an uploaded zip of resumes
  directly, rather than requiring a server-local directory path.
