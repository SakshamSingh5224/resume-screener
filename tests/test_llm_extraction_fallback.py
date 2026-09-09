import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsing.llm_field_extractor import extract_fields_with_llm_fallback


def test_falls_back_to_regex_when_no_api_key(monkeypatch):
    """Without ANTHROPIC_API_KEY set, the LLM call returns None and
    extraction must fall back to the regex extractor rather than raising
    or returning an empty ResumeData."""
    monkeypatch.setattr("adapters.llm_client.ANTHROPIC_API_KEY", "")

    raw_text = "Jane Smith\njane@example.com\nGitHub: github.com/janesmith\n"
    result = extract_fields_with_llm_fallback("test.pdf", raw_text)

    assert result.name == "Jane Smith"
    assert result.email == "jane@example.com"
    assert result.github_username == "janesmith"
