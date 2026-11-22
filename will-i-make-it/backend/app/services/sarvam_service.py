"""
Sarvam AI Speech Integration (Optional Scaffolding)
===================================================
Server-side wrapper for Sarvam API speech-to-text (STT) and text-to-speech (TTS).
Disabled by default (SARVAM_ENABLED=false).
Only active when SARVAM_ENABLED=true and SARVAM_API_KEY is configured.
Provides strict payload validation, credential sanitization, and graceful fallback.

API Reference: https://docs.sarvam.ai
"""
from __future__ import annotations
import os
import re
import base64
from typing import Optional, Tuple
import requests

SARVAM_BASE_URL = "https://api.sarvam.ai"
STT_ENDPOINT = f"{SARVAM_BASE_URL}/speech-to-text"
TTS_ENDPOINT = f"{SARVAM_BASE_URL}/text-to-speech"

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_TEXT_CHARS = 2000  # 2,000 characters

ALLOWED_LANGUAGES = {
    "hi-IN", "bn-IN", "ta-IN", "te-IN", "gu-IN",
    "mr-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN", "en-IN"
}

ALLOWED_SPEAKERS = {
    "meera", "pavithra", "maitreyi", "arvind", "amol"
}


def is_enabled() -> bool:
    """Return True only if SARVAM_ENABLED is explicitly set to true in environment."""
    return os.environ.get("SARVAM_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def is_configured() -> bool:
    """Return True only if Sarvam is enabled and an API key is present."""
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    return is_enabled() and bool(key)


def _sanitize_error(error_msg: str) -> str:
    """Sanitize error messages to ensure API keys and auth headers are never leaked."""
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if key and key in error_msg:
        error_msg = error_msg.replace(key, "[REDACTED_KEY]")
    # Redact potential authorization header patterns
    error_msg = re.sub(r"(?i)api-subscription-key['\":\s]+[\w\-]+", "api-subscription-key: [REDACTED]", error_msg)
    return error_msg


def speech_to_text(audio_b64: str, language_code: str = "hi-IN") -> Tuple[bool, str]:
    """
    Convert base64-encoded audio to text via Sarvam STT.
    Returns (success, transcript_or_error_message).
    """
    if not is_enabled():
        return False, "Sarvam integration is disabled by default. Set SARVAM_ENABLED=true in .env to enable."

    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        return False, "Sarvam API key not configured. Set SARVAM_API_KEY in .env"

    if language_code not in ALLOWED_LANGUAGES:
        return False, f"Unsupported language code '{language_code}'. Allowed: {sorted(ALLOWED_LANGUAGES)}"

    if not audio_b64 or not isinstance(audio_b64, str):
        return False, "Audio payload must be a non-empty base64 string."

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except Exception:
        return False, "Invalid base64 encoding in audio payload."

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return False, f"Audio payload exceeds maximum size limit of {MAX_AUDIO_BYTES // (1024*1024)} MB."

    try:
        headers = {
            "api-subscription-key": api_key,
        }
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"language_code": language_code, "model": "saarika:v2"}
        resp = requests.post(STT_ENDPOINT, headers=headers, files=files, data=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        transcript = result.get("transcript", "")
        return True, transcript
    except requests.exceptions.Timeout:
        return False, "Sarvam STT service request timed out after 15 seconds."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        text = e.response.text[:200] if e.response is not None else str(e)
        return False, _sanitize_error(f"Sarvam STT API HTTP error {status}: {text}")
    except Exception as e:
        return False, _sanitize_error(f"Sarvam STT error: {str(e)}")


def text_to_speech(text: str, language_code: str = "hi-IN",
                   speaker: str = "meera") -> Tuple[bool, str]:
    """
    Convert text to speech via Sarvam TTS.
    Returns (success, base64_audio_or_error_message).
    """
    if not is_enabled():
        return False, "Sarvam integration is disabled by default. Set SARVAM_ENABLED=true in .env to enable."

    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
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

    try:
        headers = {
            "api-subscription-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": [text[:500]],  # Sarvam TTS single-segment char limit
            "target_language_code": language_code,
            "speaker": speaker,
            "model": "bulbul:v1",
        }
        resp = requests.post(TTS_ENDPOINT, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()
        audios = result.get("audios", [])
        if not audios:
            return False, "No audio data returned by Sarvam TTS."
        return True, audios[0]
    except requests.exceptions.Timeout:
        return False, "Sarvam TTS service request timed out after 20 seconds."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        text = e.response.text[:200] if e.response is not None else str(e)
        return False, _sanitize_error(f"Sarvam TTS API HTTP error {status}: {text}")
    except Exception as e:
        return False, _sanitize_error(f"Sarvam TTS error: {str(e)}")


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
