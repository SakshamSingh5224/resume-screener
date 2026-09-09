# AI Resume Screening & Ranking System

A CLI pipeline that ingests a folder of resumes (PDF, with DOCX/TXT as
bonus), applies a hard Python + AI/agentic eligibility filter, scores
eligible candidates against a 100-point rubric, enriches scores with public
GitHub activity, and outputs a ranked, evidence-backed shortlist.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in values if you want optional features:
- `GITHUB_TOKEN` — raises the GitHub API limit from 60 to 5000 requests/hour.
  Not required, but strongly recommended for a full 50-resume batch.
- `ANTHROPIC_API_KEY` and `USE_LLM=true` — enables an optional LLM-based
  scoring adjustment on top of the deterministic rubric.

No API keys are required to run the default (fully deterministic) mode.
`.env` is loaded automatically at startup — no need to export environment
variables manually.

## Run

```bash
python main.py --input ./resumes --output ./output/results.json
```

Add `--verbose` for debug logging.

## Run Tests

```bash
pytest tests/ -v
```

## Optional: FastAPI Interface

```bash
uvicorn app:app --reload
```

- `POST /screen` with body `{"input_dir": "resumes"}` — runs the pipeline, returns `{"run_id": "...", "batch_summary": {...}}`
- `GET /results/{run_id}` — full report for that run
- `GET /results` — full report for the most recent run
- `GET /health` — liveness check

## Output

`results.json` contains:
- `batch_summary` — total / parsed / eligible / rejected / failed counts.
- `ranked_eligible_candidates` — sorted by `total_score` descending, each
  with a full `score_breakdown`, matched skills, project summary, GitHub
  summary, strengths, and concerns.
- `rejected_candidates` — with explicit `rejection_reasons`.
- `failed_candidates` — resumes that could not be parsed, with the error.

On the provided 50-resume set: **50 parsed, 30 eligible, 20 rejected, 0
failed.**

## Design Decisions

**Filtering strategy.** Eligibility is fully rule-based
(`eligibility/filters.py`), deliberately kept outside the LLM path so a
well-written but irrelevant resume can't talk its way past the filter.
Python evidence is accepted from anywhere — skills, projects, or work
experience. AI/agentic evidence, however, is only accepted if it appears
inside a project or experience block; a bare mention in the skills list
(e.g. "RAG" dropped into a skills line with no project behind it) is
explicitly rejected, per the requirement not to reward keyword-only
profiles. JavaScript/React/Java presence never disqualifies a candidate who
also satisfies the Python + AI requirement.

**Scoring strategy.** Scoring is deterministic-first (`scoring/rubric.py`),
so the system is fully explainable and testable without any network or API
dependency. Each of the five weighted categories differentiates between a
keyword merely being listed versus being demonstrably used in a
project/role: usage in a project earns most of the points, a bare
skill-list mention earns much less. AI project depth specifically checks
for substantive-depth signals (retrieval, state, orchestration, evaluation,
memory, etc.) and applies a 5–15 point penalty when a project reads like a
thin LLM/API wrapper with none of those signals present.

**LLM usage.** An optional layer (`scoring/llm_scorer.py` +
`adapters/llm_client.py`) can blend in an LLM's independent judgment of AI
project depth, using a structured Pydantic schema for the response. It is
gated behind `USE_LLM=true` and an `ANTHROPIC_API_KEY`; if the call fails
for any reason it silently falls back to the deterministic score and never
blocks or crashes the batch. The provider call lives entirely behind one
function (`call_llm_json`), so swapping providers touches a single file.

**GitHub scoring.** The GitHub username is regex-extracted from the resume
text. One bounded-timeout call each is made to the public `/users/{u}`,
`/events/public`, and `/repos` endpoints, run through a small bounded
thread pool so enrichment doesn't serialize across 50 resumes. Recent
activity is worth up to 5 points and maintained/relevant repositories are
worth up to 5 points, capped at 10 total. A 403/429 response is retried
with backoff (honoring GitHub's `Retry-After` header when present) before
being recorded as a terminal rate-limit status. Any failure — missing
profile, private profile, exhausted retries, network error — is recorded
as a clear status string and the candidate is still scored and ranked;
GitHub availability never gates eligibility.

**Reliability.** Every per-resume step (extraction, parsing, eligibility,
scoring, enrichment) is wrapped so a single malformed or unreadable file
cannot take down the batch — it is recorded under `failed_candidates` with
the underlying error message instead.

## If I Had More Time

1. **Layout-aware section parsing.** The current section splitter is
   regex/heuristic-based and works well on standard resumes, but a
   layout-aware fallback (using PDF positional data rather than just line
   text) would handle multi-column layouts and resumes with no clear
   section headers more reliably.

2. **Async/batched LLM calls.** When `USE_LLM=true`, extraction and scoring
   calls currently run one resume at a time. Batching or running them
   concurrently (with bounded concurrency, matching the GitHub enrichment
   approach) would meaningfully speed up large batches.

3. **Proactive GitHub rate-limit awareness.** Call GitHub's `/rate_limit`
   endpoint once at the start of a batch and, if remaining quota is clearly
   insufficient for the number of GitHub profiles found, surface a single
   batch-level warning up front rather than discovering it candidate by
   candidate.

4. **Direct zip upload support.** Add a `/screen` request option that
   accepts an uploaded zip of resumes directly, rather than requiring a
   server-local directory path — useful for the FastAPI interface in
   particular.
