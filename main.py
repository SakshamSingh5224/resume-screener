"""
CLI entrypoint.

Usage:
    python main.py --input ./resumes --output ./output/results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="AI Resume Screening & Ranking System")
    parser.add_argument("--input", required=True, help="Path to folder containing resumes")
    parser.add_argument("--output", required=True, help="Path to write results JSON")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    report = run_pipeline(args.input)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Flatten to the exact list-of-candidates shape shown in the brief, plus
    # a batch_summary key, so the file is self-describing without needing
    # this script's source to interpret it.
    payload = {
        "batch_summary": report.batch_summary.model_dump(),
        "ranked_eligible_candidates": [c.model_dump() for c in report.ranked_eligible],
        "rejected_candidates": [c.model_dump(exclude={"total_score", "score_breakdown", "rank"}) for c in report.rejected_candidates],
        "failed_candidates": [c.model_dump(include={"candidate_name", "source_file", "parse_error"}) for c in report.failed_candidates],
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\nDone. Results written to {output_path}")
    print(f"Batch summary: {report.batch_summary.model_dump()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
