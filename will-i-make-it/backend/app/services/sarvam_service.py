"""
Sarvam AI Speech Integration
============================
Server-side wrapper for Sarvam API speech-to-text (STT) and text-to-speech (TTS).
Only active when SARVAM_ENABLED=true and SARVAM_API_KEY is configured.
Provides strict payload validation, credential sanitization, modern model compatibility,
and graceful fallback.

API Reference: https://docs.sarvam.ai
"""
from __future__ import annotations

import os
import re
import base64
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any
import requests

from app.config import (
    is_sarvam_enabled,
    is_sarvam_configured,
    get_sarvam_api_key,
    get_sarvam_stt_model,
    get_sarvam_tts_model,
    get_sarvam_default_speaker,
    get_sarvam_default_language,
    sanitize_secret,
)

logger = logging.getLogger(__name__)

SARVAM_BASE_URL = "https://api.sarvam.ai"
STT_ENDPOINT = f"{SARVAM_BASE_URL}/speech-to-text"
TTS_ENDPOINT = f"{SARVAM_BASE_URL}/text-to-speech"

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_TEXT_CHARS = 2500  # Up to 2,500 characters supported by Sarvam TTS

DEFAULT_STT_MODEL = "saaras:v4"
DEFAULT_TTS_MODEL = "bulbul:v3"
DEFAULT_SPEAKER = "simran"

ALLOWED_LANGUAGES = {
    "hi-IN", "bn-IN", "ta-IN", "te-IN", "gu-IN",
    "mr-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN", "en-IN",
    "as-IN", "ur-IN", "unknown"
}

ALLOWED_SPEAKERS = {
    "simran", "ritu", "aditya", "shubh", "anushka", "priya", "neha",
    "rahul", "pooja", "rohan", "kavya", "amit", "dev", "ishita",
    "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir",
    "aayan", "ashutosh", "advait", "anand", "tanya", "tarun", "sunny",
    "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha",
    "rehan", "soham", "rupali", "niharika", "manisha", "vidya", "arya",
    "karun", "hitesh", "abhilash",
    # Legacy speaker names mapped automatically:
    "meera", "pavithra", "maitreyi", "arvind", "amol"
}

LEGACY_SPEAKER_MAP = {
    "meera": "simran",
    "pavithra": "priya",
    "maitreyi": "ritu",
    "arvind": "aditya",
    "amol": "shubh"
}

# In-memory operational health tracking
_health_state: Dict[str, Any] = {
    "last_stt_success_at": None,
    "last_tts_success_at": None,
    "stt_call_count": 0,
    "tts_call_count": 0,
    "last_error": None,
    "last_error_at": None,
}


def is_enabled() -> bool:
    """Return True only if SARVAM_ENABLED is explicitly set to true in environment."""
    return is_sarvam_enabled()


def is_configured() -> bool:
    """Return True only if Sarvam is enabled and an API key is present."""
    return is_sarvam_configured()


def get_stt_model() -> str:
    return get_sarvam_stt_model()


def get_tts_model() -> str:
    return get_sarvam_tts_model()


def resolve_speaker(speaker: str) -> str:
    spk = speaker.strip().lower()
    return LEGACY_SPEAKER_MAP.get(spk, spk)


def _sanitize_error(error_msg: str) -> str:
    """Sanitize error messages to ensure API keys and auth headers are never leaked."""
    sanitized = sanitize_secret(error_msg)
    _health_state["last_error"] = sanitized
    _health_state["last_error_at"] = datetime.now(timezone.utc).isoformat()
    return sanitized


def speech_to_text(audio_b64: str, language_code: str = "hi-IN") -> Tuple[bool, str]:
    """
    Convert base64-encoded audio to text via Sarvam STT.
    Returns (success, transcript_or_error_message).
    """
    if not is_enabled():
        return False, "Sarvam integration is disabled by default. Set SARVAM_ENABLED=true in .env to enable."

    api_key = get_sarvam_api_key()
    if not api_key:
        return False, "Sarvam API key not configured. Set SARVAM_API_KEY in .env"

    if language_code not in ALLOWED_LANGUAGES:
        return False, f"Unsupported language code '{language_code}'. Allowed: {sorted(ALLOWED_LANGUAGES)}"

    if not audio_b64 or not isinstance(audio_b64, str):
        return False, "Audio payload must be a non-empty base64 string."

    # Strip data-URI prefix if present (e.g. data:audio/wav;base64,...)
    clean_b64 = audio_b64.strip()
    if "," in clean_b64 and "base64" in clean_b64.split(",", 1)[0].lower():
        clean_b64 = clean_b64.split(",", 1)[1].strip()

    try:
        audio_bytes = base64.b64decode(clean_b64, validate=True)
    except Exception:
        return False, "Invalid base64 encoding in audio payload."

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return False, f"Audio payload exceeds maximum size limit of {MAX_AUDIO_BYTES // (1024*1024)} MB."

    # Inspect audio magic headers for correct mime and extension
    filename = "audio.wav"
    content_type = "audio/wav"
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        filename = "audio.webm"
        content_type = "audio/webm"
    elif audio_bytes.startswith(b"OggS"):
        filename = "audio.ogg"
        content_type = "audio/ogg"
    elif audio_bytes.startswith(b"ID3") or (len(audio_bytes) > 2 and audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3")):
        filename = "audio.mp3"
        content_type = "audio/mp3"
    elif len(audio_bytes) > 8 and (audio_bytes[4:8] == b"ftyp" or audio_bytes.startswith(b"\x00\x00\x00")):
        filename = "audio.mp4"
        content_type = "audio/mp4"

    try:
        headers = {
            "api-subscription-key": api_key,
        }
        files = {"file": (filename, audio_bytes, content_type)}
        stt_model = get_stt_model()
        data = {"language_code": language_code, "model": stt_model}
        resp = requests.post(STT_ENDPOINT, headers=headers, files=files, data=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        transcript = result.get("transcript", "")
        _health_state["last_stt_success_at"] = datetime.now(timezone.utc).isoformat()
        _health_state["stt_call_count"] += 1
        return True, transcript
    except requests.exceptions.Timeout:
        msg = "Sarvam STT service request timed out after 15 seconds."
        _sanitize_error(msg)
        return False, msg
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        text = e.response.text[:200] if e.response is not None else str(e)
        if status in (401, 403):
            err = f"Sarvam STT authentication failed (HTTP {status}): {text}"
        elif status == 429:
            err = f"Sarvam STT rate limit exceeded (HTTP 429): {text}"
        elif status == 400:
            err = f"Sarvam STT bad request (HTTP 400): {text}"
        else:
            err = f"Sarvam STT API HTTP error {status}: {text}"
        return False, _sanitize_error(err)
    except Exception as e:
        return False, _sanitize_error(f"Sarvam STT error: {str(e)}")


def text_to_speech(text: str, language_code: str = "hi-IN",
                   speaker: str = DEFAULT_SPEAKER) -> Tuple[bool, str]:
    """
    Convert text to speech via Sarvam TTS.
    Returns (success, base64_audio_or_error_message).
    Uses the modern official Sarvam 'text' parameter (inputs is deprecated and rejected if combined).
    """
    if not is_enabled():
        return False, "Sarvam integration is disabled by default. Set SARVAM_ENABLED=true in .env to enable."

    api_key = get_sarvam_api_key()
    if not api_key:
        return False, "Sarvam API key not configured. Set SARVAM_API_KEY in .env"

    if language_code not in ALLOWED_LANGUAGES:
        return False, f"Unsupported language code '{language_code}'. Allowed: {sorted(ALLOWED_LANGUAGES)}"

    if speaker not in ALLOWED_SPEAKERS:
        return False, f"Unsupported speaker '{speaker}'. Allowed: {sorted(ALLOWED_SPEAKERS)}"

    if not text or not isinstance(text, str):
        return False, "Text input must be a non-empty string."

    if len(text) > MAX_TEXT_CHARS:
        return False, f"Text input exceeds maximum limit of {MAX_TEXT_CHARS} characters."

    resolved_speaker = resolve_speaker(speaker)
    tts_model = get_tts_model()

    try:
        headers = {
            "api-subscription-key": api_key,
            "Content-Type": "application/json",
        }
        # Official modern Sarvam AI schema uses 'text', 'target_language_code', 'speaker', 'model'
        payload = {
            "text": text[:MAX_TEXT_CHARS],
            "target_language_code": language_code,
            "speaker": resolved_speaker,
            "model": tts_model,
        }
        resp = requests.post(TTS_ENDPOINT, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()
        audios = result.get("audios", [])
        if not audios:
            msg = "No audio data returned by Sarvam TTS."
            _sanitize_error(msg)
            return False, msg
        _health_state["last_tts_success_at"] = datetime.now(timezone.utc).isoformat()
        _health_state["tts_call_count"] += 1
        return True, audios[0]
    except requests.exceptions.Timeout:
        msg = "Sarvam TTS service request timed out after 20 seconds."
        _sanitize_error(msg)
        return False, msg
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        text_resp = e.response.text[:200] if e.response is not None else str(e)
        if status in (401, 403):
            err = f"Sarvam TTS authentication failed (HTTP {status}): {text_resp}"
        elif status == 429:
            err = f"Sarvam TTS rate limit exceeded (HTTP 429): {text_resp}"
        elif status == 400:
            err = f"Sarvam TTS bad request (HTTP 400): {text_resp}"
        else:
            err = f"Sarvam TTS API HTTP error {status}: {text_resp}"
        return False, _sanitize_error(err)
    except Exception as e:
        return False, _sanitize_error(f"Sarvam TTS error: {str(e)}")


def get_sarvam_health() -> Dict[str, Any]:
    """Retrieve operational status, active models, and recent activity for health panel."""
    enabled = is_enabled()
    configured = is_configured()
    return {
        "enabled": enabled,
        "configured": configured,
        "stt_model": get_stt_model(),
        "tts_model": get_tts_model(),
        "default_speaker": DEFAULT_SPEAKER,
        "default_language": "hi-IN",
        "supported_languages": sorted(list(ALLOWED_LANGUAGES)),
        "supported_speakers": sorted([s for s in ALLOWED_SPEAKERS if s not in LEGACY_SPEAKER_MAP]),
        "stt_status": "OPERATIONAL" if configured else ("DISABLED" if not enabled else "NOT_CONFIGURED"),
        "tts_status": "OPERATIONAL" if configured else ("DISABLED" if not enabled else "NOT_CONFIGURED"),
        "last_stt_success_at": _health_state["last_stt_success_at"],
        "last_tts_success_at": _health_state["last_tts_success_at"],
        "stt_call_count": _health_state["stt_call_count"],
        "tts_call_count": _health_state["tts_call_count"],
        "last_error": _health_state["last_error"],
        "last_error_at": _health_state["last_error_at"],
    }


def build_explanation_text(route_result: dict) -> str:
    """
    Build a natural-language explanation of a route result for TTS.
    Works in Hindi/English mix (Hinglish).
    """
    fastest = route_result.get("fastest_route", {})
    energy = fastest.get("energy_result", {})

    p50 = energy.get("total_kwh_p50", 0.0)
    p90 = energy.get("total_kwh_p90", 0.0)
    soc_p90 = energy.get("soc_final_p90_pct", 0.0)
    feasible = fastest.get("feasible", False)
    stops = fastest.get("charging_stops", [])

    if feasible:
        text = (
            f"Aapki trip ke liye estimated energy consumption {p50:.1f} units hai, "
            f"aur conservative estimate {p90:.1f} units hai. "
            f"Arrival par battery {soc_p90:.0f} percent rahegi. "
        )
        if stops:
            text += f"Route mein {len(stops)} charging stop hai. "
        text += "Trip feasible hai! Will I Make It — haan, banegi!"
    else:
        text = (
            f"Warning: Yeh trip apni current settings ke saath feasible nahi hai. "
            f"Estimated energy {p50:.1f} units hai lekin battery {soc_p90:.0f} percent "
            f"tak giregi, jo reserve se kam hai. "
            f"Kripya higher SoC se start karein ya intermediate charging karein."
        )

    return text
