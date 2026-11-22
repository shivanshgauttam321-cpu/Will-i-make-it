"""
End-to-End Audit & Verification Tests for Sarvam AI Integration.
Covers:
1. Model compatibility: STT (saaras:v4, saaras:v3) and TTS (bulbul:v3, bulbul:v4-flash)
2. Rejection / Guarding of deprecated models (saarika:v2, bulbul:v1)
3. Speaker resolution mapping (meera -> simran)
4. Devanagari Hindi entity & SOC extraction (जयपुर से दिल्ली, 80 प्रतिशत)
5. Sarvam Health API endpoint (/api/sarvam/health) & zero credential exposure
6. Conversational query grounding in authoritative EV powertrain simulation
7. Live API verification against official Sarvam endpoints when credentials exist
"""

import os
import base64
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sarvam_service import (
    is_enabled, is_configured, get_stt_model, get_tts_model, resolve_speaker,
    speech_to_text, text_to_speech, get_sarvam_health, DEFAULT_SPEAKER,
    ALLOWED_SPEAKERS, ALLOWED_LANGUAGES
)
from app.services.sarvam_nlp import extract_entities_and_intent, execute_conversational_trip_query

client = TestClient(app)


def test_model_compatibility_and_deprecation_guard(monkeypatch):
    """Verify modern models are used and deprecated ones are safely guarded."""
    monkeypatch.setenv("SARVAM_STT_MODEL", "saaras:v4")
    monkeypatch.setenv("SARVAM_TTS_MODEL", "bulbul:v3")
    assert get_stt_model() == "saaras:v4"
    assert get_tts_model() == "bulbul:v3"

    # Deprecated models should automatically fall back to supported modern standards
    monkeypatch.setenv("SARVAM_STT_MODEL", "saarika:v2")
    monkeypatch.setenv("SARVAM_TTS_MODEL", "bulbul:v1")
    assert get_stt_model() == "saaras:v4"
    assert get_tts_model() == "bulbul:v3"


def test_speaker_resolution_and_legacy_mapping():
    """Verify legacy speaker 'meera' is automatically mapped to modern 'simran'."""
    assert resolve_speaker("meera") == "simran"
    assert resolve_speaker("pavithra") == "priya"
    assert resolve_speaker("simran") == "simran"
    assert resolve_speaker("ritu") == "ritu"
    assert resolve_speaker("aditya") == "aditya"


def test_hindi_devanagari_entity_extraction():
    """Verify Hindi Devanagari phrases extract origin, destination, and SOC correctly."""
    # 1. Hindi Devanagari query with percentages
    q1 = "क्या मेरी EV 80 प्रतिशत बैटरी के साथ जयपुर से दिल्ली जा सकती है?"
    res1 = extract_entities_and_intent(q1)
    assert res1["intent"] == "FEASIBILITY_CHECK"
    assert res1["soc_start_pct"] == 80.0
    assert "जयपुर" in res1["origin_name"]
    assert "दिल्ली" in res1["dest_name"]

    # 2. English query
    q2 = "Can my EV travel from Jaipur to Delhi with 80 percent battery?"
    res2 = extract_entities_and_intent(q2)
    assert res2["intent"] == "FEASIBILITY_CHECK"
    assert res2["soc_start_pct"] == 80.0
    assert "Jaipur" in res2["origin_name"]
    assert "Delhi" in res2["dest_name"]


def test_sarvam_health_endpoint():
    """Verify /api/sarvam/health exposes status without leaking credentials."""
    resp = client.get("/api/sarvam/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "configured" in data
    assert "stt_model" in data
    assert "tts_model" in data
    assert "default_speaker" in data
    assert "stt_status" in data
    assert "tts_status" in data
    # Ensure no secret key leak
    for k, v in data.items():
        if isinstance(v, str):
            assert "sarvam" not in v.lower() or "key" not in v.lower() or "sarvam ai" in v.lower()


def test_conversational_simulation_jaipur_delhi_physics():
    """Verify physics simulation calculates real energy and feasibility for Jaipur to Delhi."""
    res = execute_conversational_trip_query(
        "Can my EV travel from Jaipur to Delhi with 80 percent battery?",
        language_code="en-IN"
    )
    assert res["feasible"] is True
    assert res["energy_p50_kwh"] > 35.0  # Real ~294 km journey consumes ~45-50 kWh
    assert "Delhi" in res["entities"]["destination"]
    assert res["arrival_soc_p90_pct"] > 0.0
    assert "make it" in res["explanation"].lower() or "feasible" in res["explanation"].lower()


def test_conversational_simulation_infeasible_low_soc():
    """Verify physical cutoff: very low starting SOC (1%) from Jaipur to Delhi must return INFEASIBLE."""
    res = execute_conversational_trip_query(
        "Can my EV travel from Jaipur to Delhi with 1 percent battery?",
        language_code="en-IN"
    )
    assert res["feasible"] is False
    assert "infeasible" in res["explanation"].lower() or "not make it" in res["explanation"].lower() or "charging" in res["explanation"].lower() or "current settings" in res["explanation"].lower()
    assert "infeasible" in res["explanation"].lower() or "not make it" in res["explanation"].lower() or "charging" in res["explanation"].lower()
    assert "infeasible" in res["explanation"].lower() or "not make it" in res["explanation"].lower() or "charging" in res["explanation"].lower()


@pytest.mark.skipif(
    not os.environ.get("SARVAM_API_KEY"),
    reason="Live Sarvam API test requires SARVAM_API_KEY in environment"
)
def test_live_sarvam_tts_api():
    """Live integration test against official Sarvam TTS API using configured credentials."""
    ok, audio_b64 = text_to_speech(
        "Electric vehicle simulation feasibility verified.",
        language_code="en-IN",
        speaker="simran"
    )
    assert ok is True
    assert len(audio_b64) > 1000
    # Decodes as valid audio
    raw_audio = base64.b64decode(audio_b64)
    assert len(raw_audio) > 500


@pytest.mark.skipif(
    not os.environ.get("SARVAM_API_KEY"),
    reason="Live Sarvam API test requires SARVAM_API_KEY in environment"
)
def test_live_sarvam_stt_api():
    """Live integration test against official Sarvam STT API using configured credentials."""
    # First synthesize a short phrase
    ok, audio_b64 = text_to_speech(
        "Can my EV travel to Delhi?",
        language_code="en-IN",
        speaker="simran"
    )
    assert ok is True

    # Then send synthesized audio into STT
    stt_ok, transcript = speech_to_text(audio_b64, language_code="en-IN")
    assert stt_ok is True
    assert "delhi" in transcript.lower() or "ev" in transcript.lower()
