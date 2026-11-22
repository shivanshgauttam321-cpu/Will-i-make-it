"""
Unit and Mocked Integration Tests for Hardened Sarvam AI Speech Integration.
Tests payload limits, language allowlists, base64 validation, error sanitization,
and timeouts without calling live external Sarvam APIs.
"""
import base64
import pytest
from unittest.mock import patch, MagicMock
import requests

from app.services.sarvam_service import (
    is_enabled, is_configured, speech_to_text, text_to_speech,
    ALLOWED_LANGUAGES, ALLOWED_SPEAKERS, MAX_AUDIO_BYTES, MAX_TEXT_CHARS,
    build_explanation_text
)


def test_sarvam_disabled_by_default(monkeypatch):
    """Verify Sarvam is disabled by default."""
    monkeypatch.delenv("SARVAM_ENABLED", raising=False)
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert not is_enabled()
    assert not is_configured()

    ok, msg = speech_to_text("dGVzdA==")
    assert not ok
    assert "disabled by default" in msg

    ok, msg = text_to_speech("test")
    assert not ok
    assert "disabled by default" in msg


def test_sarvam_enabled_missing_key(monkeypatch):
    """Verify when enabled but missing key, returns helpful error."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert is_enabled()
    assert not is_configured()

    ok, msg = speech_to_text("dGVzdA==")
    assert not ok
    assert "SARVAM_API_KEY" in msg


def test_audio_base64_validation(monkeypatch):
    """Verify invalid base64 audio is rejected immediately."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", "test_key_12345")

    # Invalid base64
    ok, msg = speech_to_text("NotAValidBase64!!!")
    assert not ok
    assert "Invalid base64" in msg


def test_audio_payload_size_limit(monkeypatch):
    """Verify audio exceeding 5 MB is rejected."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", "test_key_12345")

    # Create oversized bytes (> 5 MB)
    oversized = b"0" * (MAX_AUDIO_BYTES + 1024)
    oversized_b64 = base64.b64encode(oversized).decode("utf-8")

    ok, msg = speech_to_text(oversized_b64)
    assert not ok
    assert "exceeds maximum size limit" in msg


def test_language_and_speaker_allowlists(monkeypatch):
    """Verify unsupported languages and speakers are rejected."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", "test_key_12345")

    valid_b64 = base64.b64encode(b"RIFF....WAVEfmt ").decode("utf-8")

    # Unsupported language in STT
    ok, msg = speech_to_text(valid_b64, language_code="fr-FR")
    assert not ok
    assert "Unsupported language code" in msg

    # Unsupported language in TTS
    ok, msg = text_to_speech("Namaste", language_code="de-DE")
    assert not ok
    assert "Unsupported language code" in msg

    # Unsupported speaker in TTS
    ok, msg = text_to_speech("Namaste", speaker="unknown_bot")
    assert not ok
    assert "Unsupported speaker" in msg


def test_text_length_limit(monkeypatch):
    """Verify text exceeding 2000 chars is rejected."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", "test_key_12345")

    long_text = "A" * (MAX_TEXT_CHARS + 10)
    ok, msg = text_to_speech(long_text)
    assert not ok
    assert "exceeds maximum limit" in msg


def test_error_sanitization(monkeypatch):
    """Verify secret API keys are never leaked in error messages."""
    secret = "secret_sarvam_api_token_xyz999"
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", secret)

    valid_b64 = base64.b64encode(b"dummy audio").decode("utf-8")

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = f"Unauthorized access with api-subscription-key: {secret}"

    with patch("requests.post", side_effect=requests.exceptions.HTTPError(response=mock_resp)):
        ok, msg = speech_to_text(valid_b64)
        assert not ok
        assert secret not in msg, "Secret API key was leaked in error message!"
        assert "[REDACTED" in msg


def test_timeout_handling(monkeypatch):
    """Verify requests timeouts are caught cleanly."""
    monkeypatch.setenv("SARVAM_ENABLED", "true")
    monkeypatch.setenv("SARVAM_API_KEY", "dummy_key")

    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        ok, msg = speech_to_text(base64.b64encode(b"audio").decode("utf-8"))
        assert not ok
        assert "timed out after 15 seconds" in msg


def test_build_explanation_text():
    """Verify explanation builder works for feasible and infeasible scenarios."""
    res_feasible = {
        "fastest_route": {
            "feasible": True,
            "energy_result": {"total_kwh_p50": 22.5, "total_kwh_p90": 26.8, "soc_final_p90_pct": 25.0},
            "charging_stops": [1]
        }
    }
    text = build_explanation_text(res_feasible)
    assert "feasible" in text.lower() or "banegi" in text.lower()

    res_infeasible = {
        "fastest_route": {
            "feasible": False,
            "energy_result": {"total_kwh_p50": 38.0, "total_kwh_p90": 45.0, "soc_final_p90_pct": 2.0},
            "charging_stops": []
        }
    }
    text2 = build_explanation_text(res_infeasible)
    assert "Warning" in text2 or "nahi hai" in text2


def test_extract_entities_and_intent_multilingual():
    """Verify natural language entity and intent extraction across Hindi and English."""
    from app.services.sarvam_nlp import (
        extract_entities_and_intent, INTENT_FEASIBILITY, INTENT_BATTERY, INTENT_CHARGER, INTENT_EXPLANATION
    )

    # 1. English feasibility check with battery SOC
    res1 = extract_entities_and_intent("Can my EV reach Jaipur with 80% battery?")
    assert res1["intent"] == INTENT_FEASIBILITY
    assert "Jaipur" in res1["dest_name"]
    assert res1["soc_start_pct"] == 80.0

    # 2. Hindi battery query
    res2 = extract_entities_and_intent("Mujhe Jaipur pahunchne ke liye kitni battery chahiye?")
    assert res2["intent"] == INTENT_BATTERY
    assert "Jaipur" in res2["dest_name"]

    # 3. Charger discovery query
    res3 = extract_entities_and_intent("Find charging stops from Mumbai to Pune")
    assert res3["intent"] == INTENT_CHARGER
    assert "Mumbai" in res3["origin_name"]
    assert "Pune" in res3["dest_name"]

    # 4. Explanation query
    res4 = extract_entities_and_intent("Explain why I cannot complete this journey")
    assert res4["intent"] == INTENT_EXPLANATION


def test_conversational_trip_query_grounded_in_physics():
    """Verify conversational trip query executes physics simulation and produces grounded explanation."""
    from app.services.sarvam_nlp import execute_conversational_trip_query

    # Query feasible route
    res = execute_conversational_trip_query("Can I reach Pune from Mumbai with 90% battery?", language_code="en-IN")
    assert res["feasible"] is True
    assert res["energy_p50_kwh"] > 0.0
    assert "Pune" in res["entities"]["destination"]
    assert "make it" in res["explanation"].lower() or "feasible" in res["explanation"].lower()


def test_converse_endpoint_validation():
    """Verify converse endpoint rejects empty requests."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post("/api/sarvam/converse", json={})
    assert resp.status_code == 400
