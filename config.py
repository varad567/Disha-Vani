"""
Disha Vani - central settings.
Every value can be changed from .env without touching code.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---- Keys -------------------------------------------------------------------
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ---- Gnani endpoints (from docs.gnani.ai) -----------------------------------
STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

# Prisma speech-to-text. "prisma-v3.0" accepts several language hints at once.
# Set STT_MODEL=prisma-v2.5 in .env to use the older model (single language only).
STT_MODEL = os.getenv("STT_MODEL", "prisma-v3.0").strip()
STT_LANGS = os.getenv("STT_LANGS", "mr-IN,hi-IN,en-IN").strip()

# Timbre text-to-speech. Shivani (v3.0) speaks all 10 languages.
# Marathi voices on v2.5 are Zahira (female) and Ishaan (male).
TTS_MODEL = os.getenv("TTS_MODEL", "timbre-v3.0").strip()
TTS_VOICE = os.getenv("TTS_VOICE", "Shivani").strip()
TTS_SPEED = float(os.getenv("TTS_SPEED", "0.95"))

# ---- Gemini -----------------------------------------------------------------
# brain.py asks your key which models it can use and picks the best automatically.
# This list is only a backup in case that lookup fails. Set GEMINI_MODEL in .env to try one first.
GEMINI_MODEL_FORCED = os.getenv("GEMINI_MODEL", "").strip()
GEMINI_MODELS = [m for m in [GEMINI_MODEL_FORCED, "gemini-3.5-flash", "gemini-3.8-flash",
                             "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                             "gemini-flash-latest", "gemini-flash-lite-latest"] if m]
GEMINI_MODELS = list(dict.fromkeys(GEMINI_MODELS))  # remove duplicates, keep order
# Flash-Lite is tried first because it is faster. Set GEMINI_PREFER_LITE=0 in .env to prefer full Flash.
GEMINI_PREFER_LITE = os.getenv("GEMINI_PREFER_LITE", "1").strip() not in ("0", "false", "no")
# Time limits so a slow or rate-limited Gemini can never freeze the call.
GEMINI_REQUEST_TIMEOUT = float(os.getenv("GEMINI_REQUEST_TIMEOUT", "10"))  # seconds per request
GEMINI_TURN_BUDGET = float(os.getenv("GEMINI_TURN_BUDGET", "15"))          # seconds per caller turn

# ---- Public demo protection -----------------------------------------------------
# A hosted demo spends your own Gnani and Gemini credits, so calls are capped per day.
DAILY_CALL_LIMIT = int(os.getenv("DAILY_CALL_LIMIT", "40"))    # all visitors together
PER_VISITOR_LIMIT = int(os.getenv("PER_VISITOR_LIMIT", "6"))   # per IP address
# Load the 15 synthetic sample calls on startup so the officer view is never empty.
AUTO_SAMPLES = os.getenv("AUTO_SAMPLES", "0").strip() in ("1", "true", "yes")

# ---- Interview --------------------------------------------------------------
MAX_TURNS = 10  # hard stop so a demo call never drags on

# ---- Folders ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
SESSIONS_DIR = OUTPUT_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def require_keys(need_gemini: bool = True) -> None:
    """Stop early with a clear message if a key is missing."""
    missing = []
    if not GNANI_API_KEY or GNANI_API_KEY.startswith("paste-"):
        missing.append("GNANI_API_KEY")
    if need_gemini and (not GEMINI_API_KEY or GEMINI_API_KEY.startswith("paste-")):
        missing.append("GEMINI_API_KEY")
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}. See Day 1 step 7.")
