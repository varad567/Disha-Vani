"""
Disha Vani - Gnani API client.
  transcribe(audio_bytes, filename)  -> what the caller said   (Prisma STT)
  speak(text, language)              -> WAV audio of the reply (Timbre TTS)
"""

import time

import requests

import config

AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
               ".webm": "audio/webm", ".flac": "audio/flac", ".aac": "audio/aac"}


class GnaniError(Exception):
    """Raised with a plain-English message when a Gnani call fails."""


def _explain(r: requests.Response) -> str:
    hints = {401: "API key missing or invalid (check GNANI_API_KEY in .env)",
             402: "credits exhausted (check usage on app.gnani.ai/voice)",
             403: "this key is not allowed to use this service",
             413: "audio file too large"}
    try:
        detail = r.json()
    except ValueError:
        detail = r.text[:200]
    return f"HTTP {r.status_code}: {hints.get(r.status_code, detail)}"


def _post(url: str, **kwargs) -> requests.Response:
    """Gnani may allow one active request at a time, so retry politely on 429."""
    r = None
    for attempt in range(4):
        try:
            r = requests.post(url, timeout=60, **kwargs)
        except requests.RequestException as e:
            raise GnaniError(f"Network problem: {e}") from e
        if r.status_code != 429:
            return r
        time.sleep(2 ** (attempt + 1))
    return r


def transcribe(audio_bytes: bytes, filename: str = "answer.wav") -> dict:
    """Send one answer (under 30 seconds) to Prisma. Returns text, detected language and time taken."""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".wav"
    mime = AUDIO_TYPES.get(suffix, "application/octet-stream")

    if config.STT_MODEL == "prisma-v2.5":
        fields = {"language_code": config.STT_LANGS.split(",")[0]}  # v2.5 takes one language
    else:
        fields = {"model": config.STT_MODEL, "language_code": config.STT_LANGS}

    t0 = time.time()
    r = _post(config.STT_URL, headers={"X-API-Key-ID": config.GNANI_API_KEY},
              files={"audio_file": (filename, audio_bytes, mime)}, data=fields)
    if r.status_code != 200:
        raise GnaniError("Speech-to-text failed. " + _explain(r))
    body = r.json()
    return {"text": (body.get("transcript") or "").strip(),
            "language": body.get("detected_language_code"),
            "seconds": round(time.time() - t0, 2)}


def speak(text: str, language: str = "mr-IN") -> bytes:
    """Turn a reply into WAV audio with Timbre."""
    payload = {
        "text": text, "voice": config.TTS_VOICE, "model": config.TTS_MODEL,
        "language": language, "speed": config.TTS_SPEED,
        "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }
    r = _post(config.TTS_URL, headers={"X-API-Key-ID": config.GNANI_API_KEY}, json=payload)
    if r.status_code != 200 or not r.content:
        raise GnaniError("Text-to-speech failed. " + _explain(r))
    return r.content
