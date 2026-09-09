"""
Optional FastAPI interface around the existing pipeline (Section 8 of the
brief: "A small FastAPI interface is welcome"). Thin by design — all the
actual logic lives in pipeline.py; this file only handles HTTP routing and
serialization.

Run with:
    uvicorn app:app --reload

Endpoints:
    POST /screen   Body: {"input_dir": "resumes"}   -> runs the pipeline, returns a run_id
    GET  /results/{run_id}                          -> returns that run's report
    GET  /results                                   -> returns the most recent run's report
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from models import ScreeningReport
from pipeline import run_pipeline

app = FastAPI(title="AI Resume Screening & Ranking API")

# In-memory run store, intentionally simple per the "no database required"
# guardrail. A run's report lives only as long as the server process does.
_RUNS: Dict[str, ScreeningReport] = {}
_LATEST_RUN_ID: Optional[str] = None


class ScreenRequest(BaseModel):
    input_dir: str


class ScreenResponse(BaseModel):
    run_id: str
    batch_summary: dict


@app.post("/screen", response_model=ScreenResponse)
def screen(request: ScreenRequest):
    global _LATEST_RUN_ID

    if not Path(request.input_dir).exists():
        raise HTTPException(status_code=400, detail=f"Input directory not found: {request.input_dir}")

    report = run_pipeline(request.input_dir)
    run_id = str(uuid.uuid4())
    _RUNS[run_id] = report
    _LATEST_RUN_ID = run_id

    return ScreenResponse(run_id=run_id, batch_summary=report.batch_summary.model_dump())


@app.get("/results/{run_id}", response_model=ScreeningReport)
def get_results(run_id: str):
    report = _RUNS.get(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No run found with id: {run_id}")
    return report


@app.get("/results", response_model=ScreeningReport)
def get_latest_results():
    if _LATEST_RUN_ID is None:
        raise HTTPException(status_code=404, detail="No screening run has been performed yet. POST to /screen first.")
    return _RUNS[_LATEST_RUN_ID]


@app.get("/health")
def health():
    return {"status": "ok"}
