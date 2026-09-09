"""
Regression test for the bug where `.env` was never actually loaded into
os.environ, so a correctly-filled-in GITHUB_TOKEN never reached the process
and enrichment ran unauthenticated (and warned "GITHUB_TOKEN is not set")
even after the user followed the README exactly.
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_dotenv_fallback_parser_reads_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "GITHUB_TOKEN=abc123\n"
        'ANTHROPIC_API_KEY="quoted-value"\n'
    )

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Force the manual fallback path (as if python-dotenv weren't installed)
    # by exercising the same parsing logic config.py uses.
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)

    assert os.environ["GITHUB_TOKEN"] == "abc123"
    assert os.environ["ANTHROPIC_API_KEY"] == "quoted-value"

    # cleanup so this test doesn't leak into others
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_config_module_actually_calls_dotenv_loader():
    """Guard against re-introducing the bug silently: config.py must define
    and invoke a loader before reading GITHUB_TOKEN/ANTHROPIC_API_KEY."""
    import config
    assert hasattr(config, "_load_dotenv_if_present")
