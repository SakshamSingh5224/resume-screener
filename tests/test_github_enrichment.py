"""
Regression tests for the v3 GitHub-enrichment bug: a single 403/429 from
GitHub made `_fetch` give up immediately and record `points=0`, even though
the response carried `Retry-After` / `X-RateLimit-Reset` headers indicating
the limit would lift in a few seconds. These tests mock `requests.get`
directly so they run fully offline (no real network calls, no dependency on
GITHUB_TOKEN being set).
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import github.enrichment as enrichment


class FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json_data


def _reset_caches():
    enrichment._CACHE.clear()
    enrichment._warned_no_token = False


def test_retries_after_retry_after_header_then_succeeds():
    """A 403 with Retry-After should be retried, not treated as a final
    failure -- this is the exact bug reported against v3's results.json."""
    _reset_caches()
    responses = [
        FakeResponse(403, headers={"Retry-After": "0"}),  # user endpoint, 1st try: rate-limited
        FakeResponse(200, {"public_repos": 12}),            # user endpoint, retry: succeeds
        FakeResponse(200, {}),                                # events endpoint (empty is fine)
        FakeResponse(200, {}),                                # repos endpoint
    ]

    with patch("time.sleep", return_value=None), \
         patch("requests.get", side_effect=responses):
        result = enrichment.enrich_from_username("octocat")

    assert result.status == "ok"
    assert result.public_repos == 12


def test_gives_up_gracefully_after_exhausting_retries():
    """If GitHub keeps returning 403 past GITHUB_MAX_RETRIES, the batch must
    still get a clean 'rate_limited' status (0 points) instead of raising."""
    _reset_caches()
    always_403 = FakeResponse(403, headers={"Retry-After": "0"})

    with patch("time.sleep", return_value=None), \
         patch("requests.get", return_value=always_403):
        result = enrichment.enrich_from_username("someuser")

    assert result.status == "rate_limited"
    assert result.points == 0


def test_missing_username_short_circuits_without_network_call():
    _reset_caches()
    with patch("requests.get") as mock_get:
        result = enrichment.enrich_from_username("")
    mock_get.assert_not_called()
    assert result.status == "missing"
    assert result.points == 0
