"""Tests for the in-process job runner composition."""

import httpx
import pytest

from app.enrich.pipeline import EnrichmentPipeline
from app.jobs import runner


def test_get_pipeline_http_client_follows_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brand stores (e.g. salomon.com) 301/308 their JSON endpoints — the
    shared resolver/fetch client must follow redirects."""
    captured: dict[str, httpx.Client] = {}

    def fake_build(http_client: httpx.Client) -> EnrichmentPipeline:
        captured["client"] = http_client
        return EnrichmentPipeline(
            read_product=lambda _pid, _account: None, http_client=http_client
        )

    monkeypatch.setattr(runner, "build_pipeline", fake_build)
    monkeypatch.setattr(runner, "_pipeline", None)

    runner.get_pipeline()

    client = captured["client"]
    assert client.follow_redirects is True
    client.close()
