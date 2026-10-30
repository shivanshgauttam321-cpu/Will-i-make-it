"""
Sarvam AI Speech Integration (Optional)
=========================================
Server-side wrapper for Sarvam API speech-to-text and text-to-speech.
Only active when SARVAM_API_KEY is set in environment.
Provides graceful degradation when key is missing or calls fail.

API Reference: https://docs.sarvam.ai
"""
from __future__ import annotations
import os
import base64
from typing import Optional, Tuple
import requests

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_BASE_URL = "https://api.sarvam.ai"
STT_ENDPOINT = f"{SARVAM_BASE_URL}/speech-to-text"
TTS_ENDPOINT = f"{SARVAM_BASE_URL}/text-to-speech"


def is_configured() -> bool:
    return bool(SARVAM_API_KEY)


def speech_to_text(audio_b64: str, language_code: str = "hi-IN") -> Tuple[bool, str]:
    """
    Convert base64-encoded audio to text via Sarvam STT.
    Returns (success, transcript_or_error_message).
    """
    if not is_configured():
        return False, "Sarvam API key not configured. Set SARVAM_API_KEY in .env"

    try:
        audio_bytes = base64.b64decode(audio_b64)
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
        }
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"language_code": language_code, "model": "saarika:v2"}
        resp = requests.post(STT_ENDPOINT, headers=headers, files=files, data=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        transcript = result.get("transcript", "")
        return True, transcript
    except requests.exceptions.HTTPError as e:
        return False, f"Sarvam STT API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return False, f"Sarvam STT error: {str(e)}"


def text_to_speech(text: str, language_code: str = "hi-IN",
                   speaker: str = "meera") -> Tuple[bool, str]:
    """
    Convert text to speech via Sarvam TTS.
    Returns (success, base64_audio_or_error_message).
    """
    if not is_configured():
        return False, "Sarvam API key not configured. Set SARVAM_API_KEY in .env"

    try:
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": [text[:500]],  # Sarvam TTS typically has char limits
            "target_language_code": language_code,
            "speaker": speaker,
            "model": "bulbul:v1",
        }
        resp = requests.post(TTS_ENDPOINT, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()
        audios = result.get("audios", [])
        if not audios:
            return False, "No audio returned by Sarvam TTS"
        return True, audios[0]
    except requests.exceptions.HTTPError as e:
        return False, f"Sarvam TTS API error: {e.response.status_code} {e.response.text[:200]}"
    except Exception as e:
        return False, f"Sarvam TTS error: {str(e)}"


def build_explanation_text(route_result: dict) -> str:
    """
    Build a natural-language explanation of a route result for TTS.
    Works in Hindi/English mix (Hinglish).
    """
    fastest = route_result.get("fastest_route", {})
    energy = fastest.get("energy_result", {})

    p50 = energy.get("total_kwh_p50", 0)
    p90 = energy.get("total_kwh_p90", 0)
    soc_p90 = energy.get("soc_final_p90_pct", 0)
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
