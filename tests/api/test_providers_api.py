"""Provider status endpoint tests (owner-only, secret-free)."""

from __future__ import annotations


def test_providers_requires_auth(app_client):
    response = app_client.get("/api/v1/providers")
    assert response.status_code == 401


def test_providers_status_shape(authed_client, settings):
    response = authed_client.get("/api/v1/providers")
    assert response.status_code == 200
    body = response.json()
    assert [entry["task"] for entry in body["providers"]] == [
        "invoice_extraction", "transcription", "segmentation"]
    for entry in body["providers"]:
        assert set(entry) == {"task", "provider", "model", "availability",
                              "reason"}
    assert "tk" not in response.text
    assert "api_key" not in response.text.lower()


def test_providers_reflects_selection(authed_client, settings):
    settings.reader_provider = "spark"
    settings.model_api_key = None
    response = authed_client.get("/api/v1/providers")
    extraction = [entry for entry in response.json()["providers"]
                  if entry["task"] == "invoice_extraction"][0]
    assert extraction["availability"] == "missing_credential"
    assert extraction["provider"] == "meta"
