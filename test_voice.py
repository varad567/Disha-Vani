"""
Disha Vani - voice diagnostic.
Run:  python test_voice.py
Calls Gnani text-to-speech once, tells you exactly what came back, saves it and plays it.
"""

import os
import sys

import requests

import config

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

TEXT = "नमस्कार! मी दिशा वाणी आहे."

print("1. Checking Gnani key...")
if not config.GNANI_API_KEY or config.GNANI_API_KEY.startswith("paste-"):
    sys.exit("   PROBLEM: GNANI_API_KEY is missing in .env")
print(f"   key found (starts with {config.GNANI_API_KEY[:4]}..., length {len(config.GNANI_API_KEY)})")

print(f"\n2. Asking Gnani for audio (model {config.TTS_MODEL}, voice {config.TTS_VOICE})...")
payload = {
    "text": TEXT, "voice": config.TTS_VOICE, "model": config.TTS_MODEL, "language": "mr-IN",
    "speed": config.TTS_SPEED,
    "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                     "encoding": "linear_pcm", "container": "wav"},
}
try:
    r = requests.post(config.TTS_URL, headers={"X-API-Key-ID": config.GNANI_API_KEY},
                      json=payload, timeout=60)
except requests.RequestException as e:
    sys.exit(f"   PROBLEM: could not reach Gnani ({e}). Check your internet.")

kind = r.headers.get("Content-Type", "unknown")
print(f"   status {r.status_code}, type {kind}, size {len(r.content)} bytes")

if r.status_code != 200:
    print("   PROBLEM: Gnani returned an error. Its message:")
    print("   " + r.text[:500])
    sys.exit("\nCopy everything above and paste it to Claude.")

if not r.content.startswith(b"RIFF"):
    print("   PROBLEM: the reply is not a WAV file. First part of it:")
    print("   " + r.content[:300].decode("utf-8", errors="replace"))
    sys.exit("\nCopy everything above and paste it to Claude.")

path = config.OUTPUT_DIR / "test_voice.wav"
path.write_bytes(r.content)
print(f"   OK: real audio received and saved to {path}")

print("\n3. Playing it now (turn your volume up)...")
if os.name == "nt":
    import winsound
    try:
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        print("   Finished playing. If you heard nothing, double-click the file above in File Explorer.")
    except RuntimeError as e:
        print(f"   Windows could not play it ({e}). Double-click the file above in File Explorer.")
else:
    print(f"   Open {path} to listen.")
