import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_screen_with_missing_directory_returns_400():
    resp = client.post("/screen", json={"input_dir": "/does/not/exist"})
    assert resp.status_code == 400


def test_results_before_any_run_returns_404():
    resp = client.get("/results/some-nonexistent-run-id")
    assert resp.status_code == 404
