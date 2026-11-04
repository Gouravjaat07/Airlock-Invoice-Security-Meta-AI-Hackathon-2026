"""Security response headers: MIME-sniffing guard on every response."""

from __future__ import annotations


def test_health_carries_nosniff(app_client):
    response = app_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_authed_json_carries_nosniff(authed_client):
    response = authed_client.get("/api/v1/providers")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"


def test_error_envelope_carries_nosniff(app_client):
    response = app_client.get("/api/v1/providers")
    assert response.status_code == 401
    assert response.headers.get("x-content-type-options") == "nosniff"
