"""
Disha Vani - Day 1 check
Tests every external piece before we build anything:
  1. Gnani Timbre TTS  -> Marathi greeting in 4 candidate voices (v2.5 and v3.0)
  2. Gnani Prisma STT  -> transcribes that audio back (v2.5 vs v3.0), plus your own recordings
  3. Gemini            -> finds a working model and tests profile extraction as JSON

Run:  python day1_check.py
Outputs go to ./outputs/  (listen to the .wav files and pick your favourite voice)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

GNANI_KEY = os.getenv("GNANI_API_KEY", "").strip()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL_ENV = os.getenv("GEMINI_MODEL", "").strip()

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

OUT = Path("outputs")
SAMPLES = Path("samples")
OUT.mkdir(exist_ok=True)
SAMPLES.mkdir(exist_ok=True)

GREETING_MR = "नमस्कार! मी दिशा वाणी आहे. तुमचं शिक्षण किती झालं आहे, हे मला सांगाल का?"

# (label, model, voice, language) - Marathi voices from the Gnani voice catalog
TTS_CANDIDATES = [
    ("v25_zahira", "timbre-v2.5", "Zahira", "mr-IN"),
    ("v25_ishaan", "timbre-v2.5", "Ishaan", "mr-IN"),
    ("v30_shivani", "timbre-v3.0", "Shivani", "mr-IN"),
    ("v30_yashraj", "timbre-v3.0", "Yashraj", "mr-IN"),
]

# (label, form fields) - Prisma settings to compare
STT_CONFIGS = [
    ("prisma_v25_marathi", {"language_code": "mr-IN"}),
    ("prisma_v30_mr_hi_en", {"model": "prisma-v3.0", "language_code": "mr-IN,hi-IN,en-IN"}),
    ("prisma_v30_auto", {"model": "prisma-v3.0", "language_code": "indic-auto"}),
]

AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
               ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac"}

report = {"tts": [], "stt": [], "gemini": {}}


def line(title):
    print("\n" + "=" * 60 + f"\n{title}\n" + "=" * 60)


def post_with_retry(url, **kwargs):
    """Gnani may allow only 1 active request at a time, so retry politely on 429."""
    for attempt in range(4):
        r = requests.post(url, timeout=60, **kwargs)
        if r.status_code != 429:
            return r
        wait = 2 ** (attempt + 1)
        print(f"   rate limited, waiting {wait}s...")
        time.sleep(wait)
    return r


def explain_error(r):
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    if r.status_code == 401:
        return "401: API key missing or invalid. Check GNANI_API_KEY in .env"
    if r.status_code == 402:
        return "402: credits exhausted. Check usage on app.gnani.ai/voice"
    if r.status_code == 403:
        return f"403: key lacks permission for this service. {body}"
    return f"HTTP {r.status_code}: {json.dumps(body, ensure_ascii=False)[:300]}"


def check_keys():
    line("0. Checking keys")
    ok = True
    if not GNANI_KEY or GNANI_KEY.startswith("paste-"):
        print("MISSING: GNANI_API_KEY in .env")
        ok = False
    else:
        print("Gnani key found")
    if not GEMINI_KEY or GEMINI_KEY.startswith("paste-"):
        print("MISSING: GEMINI_API_KEY in .env (Gemini test will be skipped)")
    else:
        print("Gemini key found")
    if not ok:
        sys.exit("Fix .env and run again.")


def test_tts():
    line("1. Timbre TTS - Marathi greeting")
    for label, model, voice, lang in TTS_CANDIDATES:
        payload = {
            "text": GREETING_MR, "voice": voice, "model": model, "language": lang, "speed": 0.95,
            "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "wav"},
        }
        t0 = time.time()
        r = post_with_retry(TTS_URL, headers={"X-API-Key-ID": GNANI_KEY}, json=payload)
        secs = round(time.time() - t0, 2)
        if r.status_code == 200 and r.content:
            path = OUT / f"tts_{label}.wav"
            path.write_bytes(r.content)
            print(f"OK   {label:14} {secs}s  -> {path}")
            report["tts"].append({"label": label, "ok": True, "seconds": secs, "file": str(path)})
        else:
            msg = explain_error(r)
            print(f"FAIL {label:14} {msg}")
            report["tts"].append({"label": label, "ok": False, "error": msg})


def transcribe(path, fields):
    mime = AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    with open(path, "rb") as f:
        t0 = time.time()
        r = post_with_retry(STT_URL, headers={"X-API-Key-ID": GNANI_KEY},
                            files={"audio_file": (path.name, f, mime)}, data=fields)
    secs = round(time.time() - t0, 2)
    if r.status_code == 200:
        body = r.json()
        return True, secs, body.get("transcript", ""), body.get("detected_language_code")
    return False, secs, explain_error(r), None


def test_stt():
    line("2. Prisma STT")
    files = []
    roundtrip = OUT / "tts_v30_shivani.wav"
    if not roundtrip.exists():
        roundtrip = next(OUT.glob("tts_*.wav"), None)
    if roundtrip:
        files.append(roundtrip)
    files += sorted(p for p in SAMPLES.iterdir() if p.suffix.lower() in AUDIO_TYPES)
    if not files:
        print("No audio to test. Put recordings in ./samples and run again.")
        return
    if len(files) == 1:
        print("Tip: record 2-3 answers on your phone (Marathi, Hinglish, noisy room) and")
        print("     drop them in ./samples (wav/m4a/mp3, under 30 seconds each).")
    for path in files:
        print(f"\nFile: {path}")
        for label, fields in STT_CONFIGS:
            ok, secs, text, lang = transcribe(path, fields)
            tag = "OK  " if ok else "FAIL"
            extra = f" [{lang}]" if lang else ""
            print(f"  {tag} {label:20} {secs}s{extra}: {text}")
            report["stt"].append({"file": str(path), "config": label, "ok": ok,
                                  "seconds": secs, "text": text, "lang": lang})


def pick_gemini_model(client):
    if GEMINI_MODEL_ENV:
        return [GEMINI_MODEL_ENV]
    available = []
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            actions = getattr(m, "supported_actions", None) or []
            if "flash" in name and (not actions or "generateContent" in actions):
                available.append(name)
    except Exception as e:
        print(f"Could not list models: {e}")
    preferred = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    ordered = [p for p in preferred if p in available] or preferred
    print("Flash models on your key:", ", ".join(available[:12]) or "(could not list)")
    return ordered


def test_gemini():
    line("3. Gemini - profile extraction")
    if not GEMINI_KEY or GEMINI_KEY.startswith("paste-"):
        print("Skipped (no key)")
        return
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_KEY)
    sample = "मी आठवी पास आहे, शेतात काम करतो, पण mobile repair शिकायला आवडेल. Baramati पर्यंत जाऊ शकतो."
    prompt = (
        "Extract a livelihood profile from this Marathi/Hinglish answer. Return JSON with keys: "
        "education, current_work, interests (list), can_travel_to, notes. Use null if unknown.\n\n"
        f"Answer: {sample}"
    )
    for model in pick_gemini_model(client):
        try:
            t0 = time.time()
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
            )
            secs = round(time.time() - t0, 2)
            data = json.loads(resp.text)
            print(f"OK   {model}  {secs}s")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            report["gemini"] = {"ok": True, "model": model, "seconds": secs, "output": data}
            print(f"\nUse this in .env:  GEMINI_MODEL={model}")
            return
        except Exception as e:
            print(f"FAIL {model}: {str(e)[:200]}")
    report["gemini"] = {"ok": False}


def summary():
    line("Summary")
    tts_ok = sum(t["ok"] for t in report["tts"])
    stt_ok = sum(s["ok"] for s in report["stt"])
    print(f"TTS voices working: {tts_ok}/{len(report['tts'])}")
    print(f"STT calls working:  {stt_ok}/{len(report['stt'])}")
    print(f"Gemini:             {'OK - ' + report['gemini'].get('model', '') if report['gemini'].get('ok') else 'not working'}")
    path = OUT / "day1_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report saved to {path}. Paste the terminal output back to Claude.")


if __name__ == "__main__":
    check_keys()
    test_tts()
    test_stt()
    test_gemini()
    summary()
