"""
Disha Vani - terminal test of the interview (Checkpoint 2).

  python cli_chat.py            type your answers
  python cli_chat.py --speak    also hear Disha's replies (Gnani Timbre voice)

While chatting:
  type an answer             in Marathi, Hindi, Hinglish, or Marathi in English letters ("mi 8vi pass aahe")
  @samples\\answer.m4a       send a recording instead; Gnani Prisma transcribes it
  profile                    show what Disha has understood so far
  quit                       stop
The full call is saved to outputs\\sessions\\ at the end.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import config
import gnani
from brain import Conversation

try:
    sys.stdout.reconfigure(encoding="utf-8")  # show Marathi properly where the console allows it
except Exception:  # noqa: BLE001
    pass


def play(wav_bytes: bytes, path: Path) -> None:
    path.write_bytes(wav_bytes)
    if os.name == "nt":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    else:
        print(f"   (audio saved: {path})")


def say(result: dict, speak: bool, audio_dir: Path, n: int) -> None:
    print(f"\nDISHA: {result['reply']}")
    if not speak:
        return
    lang = "hi-IN" if result["language"] == "hi" else "mr-IN"
    try:
        play(gnani.speak(result["reply"], lang), audio_dir / f"disha_{n:02d}.wav")
    except gnani.GnaniError as e:
        print(f"   [voice failed: {e}]")


def read_answer() -> str:
    raw = input("\nYOU: ").strip()
    if not raw.startswith("@"):
        return raw
    path = Path(raw[1:].strip().strip('"'))
    if not path.exists():
        print(f"   [file not found: {path}]")
        return ""
    try:
        result = gnani.transcribe(path.read_bytes(), path.name)
    except gnani.GnaniError as e:
        print(f"   [{e}]")
        return ""
    print(f"   Prisma heard ({result['language'] or '?'}, {result['seconds']}s): {result['text']}")
    return result["text"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the Disha Vani interview in the terminal")
    parser.add_argument("--speak", action="store_true", help="speak Disha's replies with Gnani TTS")
    args = parser.parse_args()
    config.require_keys()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    audio_dir = config.SESSIONS_DIR / f"audio_{stamp}"
    if args.speak:
        audio_dir.mkdir(parents=True, exist_ok=True)

    convo = Conversation()
    print("Disha Vani test call. Type 'quit' to stop, 'profile' to see what Disha understood.")
    n = 0
    say(convo.start(), args.speak, audio_dir, n)

    while not convo.done:
        answer = read_answer()
        if answer.lower() == "quit":
            break
        if answer.lower() == "profile":
            print(json.dumps(convo.profile, ensure_ascii=False, indent=2))
            continue
        if not answer:
            continue
        n += 1
        say(convo.handle(answer), args.speak, audio_dir, n)

    out = config.SESSIONS_DIR / f"session_{stamp}.json"
    out.write_text(json.dumps(convo.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n--- Final profile ---")
    print(json.dumps(convo.profile, ensure_ascii=False, indent=2))
    if convo.events:
        print("Notes:", *convo.events, sep="\n  ")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
