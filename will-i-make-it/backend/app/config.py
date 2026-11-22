"""
Central Application Configuration & Robust Environment Loader
=============================================================
Deterministically locates and loads backend/.env regardless of process CWD.
Preserves existing system environment variables (e.g., on Render or Docker).
Provides sanitized configuration access with zero credential leakage.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# 1. Authoritative .env file resolution
_APP_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _APP_DIR.parent

ENV_CANDIDATES = [
    _BACKEND_DIR / ".env",
    Path.cwd() / ".env",
    Path.cwd() / "backend" / ".env",
    Path.cwd() / "will-i-make-it" / "backend" / ".env",
]

_loaded_env_path: Optional[Path] = None

for candidate in ENV_CANDIDATES:
    if candidate.exists() and candidate.is_file():
        load_dotenv(dotenv_path=candidate, override=False)
        _loaded_env_path = candidate
        break

if _loaded_env_path is None:
    # Fallback to standard dotenv discovery
    load_dotenv(override=False)


# 2. Configuration Accessors

def is_sarvam_enabled() -> bool:
    """Return True only if SARVAM_ENABLED is explicitly enabled."""
    return os.environ.get("SARVAM_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def get_sarvam_api_key() -> str:
    """Return sanitized, stripped SARVAM_API_KEY from environment."""
    raw = os.environ.get("SARVAM_API_KEY", "")
    return raw.strip(' "\'\r\n')


def is_sarvam_configured() -> bool:
    """Return True only if Sarvam is enabled and a non-empty API key is present."""
    return is_sarvam_enabled() and bool(get_sarvam_api_key())


def get_sarvam_stt_model() -> str:
    """Return configured STT model, guarding against deprecated legacy identifiers."""
    m = os.environ.get("SARVAM_STT_MODEL", "saaras:v4").strip(' "\'\r\n')
    if not m or m.lower() in ("saarika:v2", "saarika:v1", "saaras:v1", "saaras:v2"):
        return "saaras:v4"
    return m


def get_sarvam_tts_model() -> str:
    """Return configured TTS model, guarding against deprecated legacy identifiers."""
    m = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3").strip(' "\'\r\n')
    if not m or m.lower() in ("bulbul:v1", "bulbul:v2"):
        return "bulbul:v3"
    return m


def get_sarvam_default_speaker() -> str:
    return os.environ.get("SARVAM_DEFAULT_SPEAKER", "simran").strip(' "\'\r\n') or "simran"


def get_sarvam_default_language() -> str:
    return os.environ.get("SARVAM_DEFAULT_LANGUAGE", "hi-IN").strip(' "\'\r\n') or "hi-IN"


def sanitize_secret(text: str) -> str:
    """Ensure any API keys or credential patterns are redacted from error messages or logs."""
    key = get_sarvam_api_key()
    if key and key in text:
        text = text.replace(key, "[REDACTED_KEY]")
    # Redact common auth header patterns
    text = re.sub(r"(?i)api-subscription-key['\":\s]+[\w\-]+", "api-subscription-key: [REDACTED]", text)
    text = re.sub(r"(?i)bearer\s+[\w\.\-]+", "Bearer [REDACTED]", text)
    return text


def get_sarvam_diagnostics() -> Dict[str, Any]:
    """Safe, masked diagnostic summary for health and audit checks."""
    key = get_sarvam_api_key()
    return {
        "python_executable": os.sys.executable,
        "backend_dir": str(_BACKEND_DIR),
        "env_file_loaded": str(_loaded_env_path) if _loaded_env_path else None,
        "sarvam_enabled": is_sarvam_enabled(),
        "sarvam_api_key_configured": bool(key),
        "sarvam_api_key_masked": f"{key[:6]}...{key[-4:]}" if len(key) >= 12 else ("[CONFIGURED]" if key else "[NOT_SET]"),
        "stt_model": get_sarvam_stt_model(),
        "tts_model": get_sarvam_tts_model(),
        "default_speaker": get_sarvam_default_speaker(),
        "default_language": get_sarvam_default_language(),
    }
