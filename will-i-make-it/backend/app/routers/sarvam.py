"""
Sarvam AI Speech & Conversational Routing Endpoints
===================================================
Provides Speech-to-Text (STT), Text-to-Speech (TTS), and Multilingual
Conversational Journey Interaction. Strictly integrates with the authoritative
physics engine to ensure physical truthfulness.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.services.sarvam_service import (
    is_enabled, is_configured, speech_to_text, text_to_speech, build_explanation_text,
    get_sarvam_health, get_stt_model, get_tts_model, DEFAULT_SPEAKER
)
from app.services.sarvam_nlp import execute_conversational_trip_query

router = APIRouter(prefix="/api/sarvam", tags=["Sarvam AI (Speech & Language)"])


class STTRequest(BaseModel):
    audio_b64: str
    language_code: str = "hi-IN"


class TTSRequest(BaseModel):
    text: str
    language_code: str = "hi-IN"
    speaker: str = DEFAULT_SPEAKER


class ExplainRequest(BaseModel):
    route_result: dict
    language_code: str = "hi-IN"


class ConverseRequest(BaseModel):
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    language_code: str = "hi-IN"
    speak_response: bool = False
    speaker: str = DEFAULT_SPEAKER


@router.get("/status")
def sarvam_status():
    enabled = is_enabled()
    configured = is_configured()
    stt_model = get_stt_model()
    tts_model = get_tts_model()
    default_lang = os.environ.get("SARVAM_DEFAULT_LANGUAGE", "hi-IN")

    if not enabled:
        msg = "Sarvam integration is disabled by default. Set SARVAM_ENABLED=true in .env to enable voice features."
    elif not configured:
        msg = "Sarvam enabled but SARVAM_API_KEY not configured. Set SARVAM_API_KEY in .env."
    else:
        msg = f"Sarvam AI is enabled, configured, and operational. STT: {stt_model}, TTS: {tts_model}."

    return {
        "enabled": enabled,
        "configured": configured,
        "stt_model": stt_model,
        "tts_model": tts_model,
        "default_speaker": DEFAULT_SPEAKER,
        "default_language": default_lang,
        "message": msg,
    }


@router.get("/health")
def sarvam_health():
    """Detailed operational health status for frontend Sarvam Health Panel."""
    return get_sarvam_health()


def _raise_error(result: str):
    is_validation = any(k in result for k in [
        "Unsupported language", "Unsupported speaker", "Invalid base64",
        "exceeds maximum", "must be a non-empty"
    ])
    status_code = 400 if is_validation else 503
    raise HTTPException(status_code=status_code, detail=result)


@router.post("/stt")
def speech_to_text_endpoint(req: STTRequest):
    """Convert spoken Hindi/English/Hinglish audio to text."""
    ok, result = speech_to_text(req.audio_b64, req.language_code)
    if not ok:
        _raise_error(result)
    return {"transcript": result, "language_code": req.language_code}


@router.post("/tts")
def text_to_speech_endpoint(req: TTSRequest):
    """Convert text to speech (Hindi/English/Hinglish)."""
    ok, result = text_to_speech(req.text, req.language_code, req.speaker)
    if not ok:
        _raise_error(result)
    return {"audio_b64": result, "language_code": req.language_code}


@router.post("/explain")
def explain_route(req: ExplainRequest):
    """
    Build a natural-language explanation of a route result and convert to speech.
    Explanation is grounded in physical simulation results.
    """
    text = build_explanation_text(req.route_result)
    ok, audio = text_to_speech(text, req.language_code)
    response = {
        "explanation_text": text,
        "language_code": req.language_code,
        "tts_available": ok,
    }
    if ok:
        response["audio_b64"] = audio
    else:
        response["tts_error"] = audio
    return response


@router.post("/converse")
def converse_endpoint(req: ConverseRequest):
    """
    Multilingual conversational journey query:
    Accepts text or audio, extracts intent and destination, runs physical simulation,
    and returns grounded truth with optional speech playback.
    """
    query_text = req.text

    if not query_text and req.audio_b64:
        # Transcribe audio via STT
        ok, transcript = speech_to_text(req.audio_b64, req.language_code)
        if not ok:
            _raise_error(transcript)
        query_text = transcript

    if not query_text:
        raise HTTPException(status_code=400, detail="Either 'text' or 'audio_b64' must be provided.")

    # Process query through physical journey simulator
    result = execute_conversational_trip_query(
        text=query_text,
        language_code=req.language_code,
    )

    # Optional speech synthesis of the explanation
    audio_b64 = None
    if req.speak_response and is_configured():
        tts_ok, tts_data = text_to_speech(result["explanation"], req.language_code, req.speaker)
        if tts_ok:
            audio_b64 = tts_data

    result["audio_b64"] = audio_b64
    return result
