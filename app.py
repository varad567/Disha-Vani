"""
Disha Vani - web server.

Run:   uvicorn app:app --reload
Open:  http://localhost:8000          (call screen)
       http://localhost:8000/officer  (officer view)

One caller turn:  browser records audio -> /api/turn -> Gnani Prisma (speech to text)
                  -> brain.py (Gemini) -> recommender.py when done -> Gnani Timbre (text to speech) -> browser
"""

import base64
import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import gnani
import recommender
from brain import Conversation

config.require_keys()
app = FastAPI(title="Disha Vani")
STATIC = config.BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SESSIONS: dict = {}            # session_id -> {"convo": Conversation, "record": {...}}
gnani_lock = threading.Lock()  # Gnani may allow one request at a time per key

# Short sounds Disha makes the moment the caller finishes, so the wait never feels dead.
# Recorded once with Gnani, saved to disk, then reused for every call (no extra credits).
FILLERS = ["हं, बरं.", "ठीक आहे.", "हं."]
FILLER_DIR = config.OUTPUT_DIR / "fillers"
FILLER_DIR.mkdir(parents=True, exist_ok=True)

NOT_HEARD = {"mr": "माफ करा, नीट ऐकू आलं नाही. पुन्हा एकदा सांगाल का?",
             "hi": "माफ़ कीजिए, ठीक से सुनाई नहीं दिया। क्या आप दोबारा बताएँगे?"}


# ---- demo limits (protect your API credits on a public link) ---------------------
LIMITS = {"day": None, "total": 0, "per_visitor": {}}
limit_lock = threading.Lock()


def check_call_limit(request: Request) -> None:
    """Allow a new call only while today's site-wide and per-visitor caps are not reached."""
    forwarded = request.headers.get("x-forwarded-for", "")
    visitor = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    today = datetime.now().date().isoformat()
    with limit_lock:
        if LIMITS["day"] != today:
            LIMITS.update(day=today, total=0, per_visitor={})
        if LIMITS["total"] >= config.DAILY_CALL_LIMIT:
            raise HTTPException(429, "Today's demo limit has been reached. Please try again tomorrow.")
        if LIMITS["per_visitor"].get(visitor, 0) >= config.PER_VISITOR_LIMIT:
            raise HTTPException(429, "You've reached today's demo limit. Thank you for trying Disha Vani!")
        LIMITS["total"] += 1
        LIMITS["per_visitor"][visitor] = LIMITS["per_visitor"].get(visitor, 0) + 1


# ---- helpers ------------------------------------------------------------------
def voice(text: str, language: str) -> Optional[str]:
    """Reply audio as base64 WAV, or None if TTS fails (the screen still shows the text)."""
    try:
        with gnani_lock:
            wav = gnani.speak(text, "hi-IN" if language == "hi" else "mr-IN")
        return base64.b64encode(wav).decode()
    except gnani.GnaniError as e:
        print("TTS failed:", e)
        return None


def filler_audio() -> list:
    clips = []
    for i, text in enumerate(FILLERS):
        path = FILLER_DIR / f"{config.TTS_MODEL}_{config.TTS_VOICE}_{i}.wav"
        if not path.exists():
            try:
                with gnani_lock:
                    path.write_bytes(gnani.speak(text, "mr-IN"))
            except gnani.GnaniError as e:
                print("Filler recording failed:", e)
                continue
        clips.append(base64.b64encode(path.read_bytes()).decode())
    return clips


def log_timing(turn: int, timing: dict) -> None:
    parts = ", ".join(f"{k} {v}s" for k, v in timing.items())
    total = round(sum(timing.values()), 2)
    print(f"[turn {turn}] {parts}  ->  total {total}s")


def save(session_id: str) -> None:
    record = SESSIONS[session_id]["record"]
    path = config.SESSIONS_DIR / f"web_{session_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def load_saved_sessions() -> None:
    """Bring back earlier web calls so the officer view survives a server restart."""
    for path in sorted(config.SESSIONS_DIR.glob("web_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            SESSIONS[record["id"]] = {"convo": None, "record": record}
        except (ValueError, KeyError):
            continue


load_saved_sessions()


def sync_record(session_id: str) -> dict:
    s = SESSIONS[session_id]
    convo: Conversation = s["convo"]
    s["record"].update(convo.summary())
    return s["record"]


# ---- pages --------------------------------------------------------------------
@app.get("/")
def call_page():
    return FileResponse(STATIC / "index.html")


@app.get("/officer")
def officer_page():
    return FileResponse(STATIC / "officer.html")


# ---- call API -----------------------------------------------------------------
@app.post("/api/start")
def start_call(request: Request):
    check_call_limit(request)
    session_id = uuid.uuid4().hex[:8]
    convo = Conversation()
    first = convo.start()
    SESSIONS[session_id] = {"convo": convo, "record": {
        "id": session_id, "started": datetime.now().isoformat(timespec="seconds"),
        "recommendation": None, "checkins": [], "timings": []}}
    sync_record(session_id)
    save(session_id)
    return {"session_id": session_id, "reply": first["reply"], "audio": voice(first["reply"], "mr"),
            "profile": convo.profile, "done": False, "fillers": filler_audio()}


@app.post("/api/turn")
def take_turn(session_id: str = Form(...), text: Optional[str] = Form(None),
              audio: Optional[UploadFile] = File(None)):
    s = SESSIONS.get(session_id)
    if not s or not s["convo"]:
        raise HTTPException(404, "This call has ended. Start a new call.")
    convo: Conversation = s["convo"]
    timing = {}

    heard, heard_lang = (text or "").strip(), None
    if audio is not None:
        data = audio.file.read()
        if len(data) < 2000:
            heard = ""
        else:
            t0 = time.time()
            try:
                with gnani_lock:
                    result = gnani.transcribe(data, audio.filename or "answer.wav")
            except gnani.GnaniError as e:
                raise HTTPException(502, str(e)) from e
            timing["stt"] = round(time.time() - t0, 2)
            heard, heard_lang = result["text"], result["language"]

    if not heard:
        reply = NOT_HEARD[convo.language]
        return {"heard": "", "reply": reply, "audio": voice(reply, convo.language),
                "profile": convo.profile, "done": False}

    t0 = time.time()
    out = convo.handle(heard)
    timing["llm"] = round(time.time() - t0, 2)
    reply = out["reply"]
    recs = None
    if out["done"]:
        recs = recommender.recommend(convo.profile)
        s["record"]["recommendation"] = recs
        reply = reply + " " + recommender.speech(recs, convo.language)

    t0 = time.time()
    audio_b64 = voice(reply, convo.language)
    timing["tts"] = round(time.time() - t0, 2)
    s["record"]["timings"].append(timing)
    log_timing(convo.turns, timing)
    if out["done"]:
        convo.history[-1]["text"] = reply  # keep the full spoken text in the transcript
    sync_record(session_id)
    save(session_id)
    return {"heard": heard, "heard_language": heard_lang, "reply": reply, "audio": audio_b64,
            "profile": convo.profile, "done": out["done"], "recommendation": recs, "timing": timing}


# ---- officer API --------------------------------------------------------------
@app.get("/api/sessions")
def list_sessions():
    rows = []
    for sid, s in SESSIONS.items():
        r = s["record"]
        recs = (r.get("recommendation") or {}).get("recommendations") or []
        rows.append({"id": sid, "started": r.get("started"), "name": (r.get("profile") or {}).get("name"),
                     "synthetic": r.get("synthetic", False),
                     "done": r.get("done"), "top": recs[0]["name_en"] if recs else None,
                     "guardrail_passed": (r.get("recommendation") or {}).get("guardrail", {}).get("passed"),
                     "checkins": len(r.get("checkins") or [])})
    rows.sort(key=lambda x: x["started"] or "", reverse=True)
    return rows


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(404, "No such call")
    return SESSIONS[session_id]["record"]


@app.post("/api/sessions/{session_id}/checkin")
def simulate_checkin(session_id: str):
    """Simulated 30-day follow-up call: Disha asks whether the course has started."""
    if session_id not in SESSIONS:
        raise HTTPException(404, "No such call")
    record = SESSIONS[session_id]["record"]
    name = (record.get("profile") or {}).get("name") or ""
    recs = (record.get("recommendation") or {}).get("recommendations") or []
    course = recs[0]["name_mr"] if recs else "कोर्स"
    text = f"नमस्कार {name}! मी दिशा वाणी. {course} बद्दल विचारायला फोन केला. तुमचा कोर्स सुरू झाला का?"
    started = datetime.fromisoformat(record["started"])
    checkin = {"day": 30, "due": (started + timedelta(days=30)).date().isoformat(),
               "placed": datetime.now().isoformat(timespec="seconds"), "message": text,
               "status": "simulated call placed"}
    record.setdefault("checkins", []).append(checkin)
    save(session_id)
    return {"checkin": checkin, "audio": voice(text, "mr")}


# ---- dashboard stats ------------------------------------------------------------
def _trade_label(interest: str) -> str:
    """Group free-text interests ("driving", "ड्रायव्हिंग शिकायचं आहे") under one course name."""
    best, best_score = None, 0
    for c in recommender.COURSES:
        hits = recommender._matches([interest], c["tags"])
        score = len(hits) + (5 if c["tags"][0] in hits else 0)  # the course's main trade wins
        if score > best_score:
            best, best_score = c["name_en"], score
    return best or "Other (not in course list)"


@app.get("/api/stats")
def stats():
    records = [s["record"] for s in SESSIONS.values()]
    done = [r for r in records if r.get("done")]
    trades, goals = {}, {"job": 0, "self_employment": 0, "either": 0}
    for r in done:
        p = r.get("profile") or {}
        for label in {_trade_label(i) for i in (p.get("interests") or [])}:
            trades[label] = trades.get(label, 0) + 1
        if p.get("goal") in goals:
            goals[p["goal"]] += 1
    with_recs = [r["recommendation"] for r in done if r.get("recommendation")]
    timings = [t for r in records for t in (r.get("timings") or [])]
    avg = lambda k: round(sum(t.get(k, 0) for t in timings) / len(timings), 1) if timings else None  # noqa: E731
    return {
        "started": len(records),
        "completed": len(done),
        "synthetic": sum(1 for r in records if r.get("synthetic")),
        "top_trades": sorted(trades.items(), key=lambda kv: -kv[1])[:6],
        "goals": goals,
        "guardrail_checked": len(with_recs),
        "guardrail_passed": sum(1 for x in with_recs if x["guardrail"]["passed"]),
        "family_removed": sum(len(x["guardrail"]["removed"]) for x in with_recs),
        "family_added": sum(len(x["guardrail"]["added"]) for x in with_recs),
        "avg": {"stt": avg("stt"), "llm": avg("llm"), "tts": avg("tts")},
        "checkins": sum(len(r.get("checkins") or []) for r in records),
    }


# ---- sample calls (synthetic callers, no API credits used) -------------------------
SAMPLE_CALLERS = [
    ("Suresh", "12th pass", "unemployed", "farming", ["driving"], "district", "job"),
    ("Kavita", "10th pass", "housework", "farming", ["tailoring"], "taluka", "self_employment"),
    ("Rahul", "12th pass", "shop helper", None, ["mobile repair"], "district", "either"),
    ("Pooja", "12th pass", "unemployed", "shop", ["beauty parlour"], "taluka", "self_employment"),
    ("Ganesh", "8th pass", "farm labour", "farming", ["drip irrigation"], "taluka", "either"),
    ("Sunita", "10th pass", "farm labour", "farming", ["dairy"], "taluka", "self_employment"),
    ("Amol", "10th + ITI", "unemployed", "electric", ["solar"], "district", "job"),
    ("Priya", "12th pass", "unemployed", None, ["hospital"], "district", "job"),
    ("Sachin", "10th pass", "delivery rider", "transport", ["driving"], "anywhere", "job"),
    ("Rekha", "8th pass", "housework", "tailor", ["tailoring"], "village_only", "self_employment"),
    ("Vikas", "10th pass", "garage helper", None, ["bike mechanic"], "district", "either"),
    ("Anita", "12th pass", "unemployed", "farming", ["computer"], "district", "job"),
    ("Mahesh", "9th pass", "construction labour", "construction", ["electrician"], "district", "job"),
    ("Savita", "10th pass", "farm labour", "farming", ["tailoring"], "taluka", "either"),
    ("Nilesh", "10th pass", "unemployed", None, ["solar"], "taluka", "job"),
]


@app.post("/api/sample-calls")
def add_sample_calls():
    """Create clearly-marked synthetic callers so the dashboard looks like a real day. Safe to click twice."""
    remove_sample_calls()
    now = datetime.now()
    for i, (name, edu, work, family, interests, travel, goal) in enumerate(SAMPLE_CALLERS):
        sid = f"sample{i:02d}"
        profile = {"name": name, "education": edu, "current_work": work, "family_occupation": family,
                   "interests": interests, "can_travel": travel, "goal": goal}
        recs = recommender.recommend(profile)
        record = {
            "id": sid, "synthetic": True,
            "started": (now - timedelta(minutes=25 * (len(SAMPLE_CALLERS) - i))).isoformat(timespec="seconds"),
            "profile": profile, "done": True, "turns": 6, "language": "mr", "recommendation": recs,
            "checkins": [], "events": ["synthetic sample caller (no audio)"],
            "history": [{"role": "disha", "text": "Synthetic sample call: profile only, no transcript."}],
            "timings": [{"stt": round(0.8 + (i % 4) * 0.1, 1), "llm": round(2.6 + (i % 5) * 0.2, 1),
                         "tts": round(2.0 + (i % 3) * 0.2, 1)}],
        }
        SESSIONS[sid] = {"convo": None, "record": record}
        save(sid)
    return {"added": len(SAMPLE_CALLERS)}


@app.delete("/api/sample-calls")
def remove_sample_calls():
    removed = 0
    for sid in [k for k, v in SESSIONS.items() if v["record"].get("synthetic")]:
        SESSIONS.pop(sid)
        path = config.SESSIONS_DIR / f"web_{sid}.json"
        if path.exists():
            path.unlink()
        removed += 1
    return {"removed": removed}


# ---- on startup: sample calls for the public demo -----------------------------------
if config.AUTO_SAMPLES and not any(v["record"].get("synthetic") for v in SESSIONS.values()):
    add_sample_calls()
