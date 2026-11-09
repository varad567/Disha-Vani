"""
Disha Vani - Gemini speed test.
Run:  python test_gemini.py
Times one small JSON request on each Flash model your key can use, so we can pick the fastest.
"""

import json
import sys
import time

import config
from brain import _clean_json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from google import genai
from google.genai import types

PROMPT = ('Extract JSON with keys education, interests (list) from this Marathi answer and add a short '
          'Marathi question as "reply": "मी बारावी पास आहे, मला ड्रायव्हिंग शिकायचं आहे"')
NOT_CHAT = ("tts", "image", "live", "audio", "embedding", "robotics", "omni", "computer", "learnlm")

client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=20000))
names = []
for m in client.models.list():
    name = m.name.replace("models/", "")
    if "flash" in name and not any(x in name for x in NOT_CHAT) and not name.startswith("gemini-2"):
        names.append(name)
print("Flash models on your key:", ", ".join(names) or "none found")

for name in names[:6]:
    for label, extra in (("normal", {}), ("low thinking", {"thinking_config": types.ThinkingConfig(thinking_level="low")})):
        t0 = time.time()
        try:
            cfg = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3, **extra)
            data = _clean_json(client.models.generate_content(model=name, contents=PROMPT, config=cfg).text)
            print(f"OK   {name:28} {label:13} {time.time() - t0:5.1f}s  {json.dumps(data, ensure_ascii=False)[:70]}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name:28} {label:13} {time.time() - t0:5.1f}s  {str(e)[:90]}")
print("\nCopy everything above and paste it to Claude.")
