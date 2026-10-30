"""Sarvam speech endpoints (optional)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.sarvam_service import (
    is_configured, speech_to_text, text_to_speech, build_explanation_text
)

router = APIRouter(prefix="/api/sarvam", tags=["Sarvam (Optional)"])


class STTRequest(BaseModel):
    audio_b64: str
    language_code: str = "hi-IN"


class TTSRequest(BaseModel):
    text: str
    language_code: str = "hi-IN"
    speaker: str = "meera"


class ExplainRequest(BaseModel):
    route_result: dict
    language_code: str = "hi-IN"


@router.get("/status")
def sarvam_status():
    return {
        "configured": is_configured(),
        "message": (
            "Sarvam API is configured and ready."
            if is_configured()
            else "Sarvam API key not set. Add SARVAM_API_KEY to .env to enable voice features."
        ),
    }


@router.post("/stt")
def speech_to_text_endpoint(req: STTRequest):
    """Convert spoken Hindi/English/Hinglish audio to text."""
    ok, result = speech_to_text(req.audio_b64, req.language_code)
    if not ok:
        raise HTTPException(status_code=503, detail=result)
    return {"transcript": result, "language_code": req.language_code}


@router.post("/tts")
def text_to_speech_endpoint(req: TTSRequest):
    """Convert text to speech (Hindi/English/Hinglish)."""
    ok, result = text_to_speech(req.text, req.language_code, req.speaker)
    if not ok:
        raise HTTPException(status_code=503, detail=result)
    return {"audio_b64": result, "language_code": req.language_code}


@router.post("/explain")
def explain_route(req: ExplainRequest):
    """
    Build a natural-language explanation of a route result and convert to speech.
    Explanation is in Hinglish (Hindi + English mix).
    Falls back to text-only if TTS fails.
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
