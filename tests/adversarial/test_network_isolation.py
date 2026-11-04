"""Network isolation: the default Phase 2 path makes no network calls."""

from __future__ import annotations

import socket


from tests.conftest import upload_case

SCENARIOS = ["clean", "changed-bank", "sam-ok", "voice-instruction"]


def _block_network(monkeypatch):
    def _denied(*args, **kwargs):
        raise AssertionError("network access attempted during offline test")
    monkeypatch.setattr(socket, "socket", _denied)
    monkeypatch.setattr(socket, "create_connection", _denied)
    monkeypatch.setattr(socket, "getaddrinfo", _denied)


def test_api_flows_offline(app_client, monkeypatch):
    _block_network(monkeypatch)
    for invoice in ("invoices/clean.pdf", "invoices/changed-bank.pdf",
                    "invoices/arithmetic-mismatch.pdf"):
        created = upload_case(app_client, invoice)
        response = app_client.post(
            f"/api/v1/cases/{created['case']['id']}/process")
        assert response.status_code == 200


def test_evidence_adapters_offline(authed_client, monkeypatch):
    _block_network(monkeypatch)
    created = upload_case(authed_client, "invoices/sam-ok.pdf",
                          delivery="delivery/sam-ok.png")
    response = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process")
    assert response.status_code == 200
    assert response.json()["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    created = upload_case(authed_client, "invoices/voice-instruction.pdf",
                          voice="voice/voice-instruction.wav")
    response = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process")
    assert response.status_code == 200


def test_eval_offline(authed_client, monkeypatch):
    _block_network(monkeypatch)
    response = authed_client.post("/api/v1/evaluation/run",
                                  json={"scenarios": SCENARIOS})
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["matched"] == len(SCENARIOS)


def test_no_provider_imports_in_app():
    import sys
    for module in ("openai", "anthropic", "boto3", "stripe", "razorpay"):
        assert module not in sys.modules
    import app.main  # noqa: F401  (import must not pull provider SDKs)
    for module in ("openai", "anthropic", "boto3", "stripe", "razorpay"):
        assert module not in sys.modules
