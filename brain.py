"""
Disha Vani - interview engine.

Each caller turn = ONE Gemini call that does two jobs:
  1. pulls facts out of the answer into the profile
  2. writes the next short spoken question
Code (not the LLM) decides which topic comes next and when the interview ends.
If Gemini fails (quota, network), a fixed Marathi question bank keeps the call going.
"""

import json
import re
import time

import config
import recommender

# Topics in the order we ask them. Required ones must be filled before we finish.
SLOTS = ["name", "education", "current_work", "family_occupation", "interests", "can_travel", "goal"]
REQUIRED = ["education", "current_work", "interests", "can_travel", "goal"]

SLOT_GUIDE = {
    "name": "first name only",
    "education": "highest schooling in short English, e.g. '8th pass', '12th pass', 'no schooling', '10th + ITI'; "
                 "if studying in college write 'studying graduation (12th pass)'",
    "current_work": "what they do now in short English, e.g. 'farm labour', 'unemployed', 'shop helper'",
    "family_occupation": "what the family does, short English (optional, never pressure)",
    "interests": "LIST of trades they want to learn, short English, e.g. ['mobile repair', 'tailoring']",
    "can_travel": "one of: 'village_only', 'taluka', 'district', 'anywhere'",
    "goal": "one of: 'job', 'self_employment', 'either'",
}

GREETING = {
    "mr": "नमस्कार! मी दिशा वाणी, तुमची कौशल्य मार्गदर्शक. काही सोपे प्रश्न विचारते, "
          "म्हणजे तुमच्यासाठी योग्य कोर्स सुचवता येईल. आधी सांगा, तुमचं नाव काय आहे?",
}

FALLBACK_QUESTIONS = {
    "mr": {
        "name": "तुमचं नाव काय आहे?",
        "education": "तुमचं शिक्षण किती झालं आहे?",
        "current_work": "सध्या तुम्ही काय काम करता?",
        "family_occupation": "तुमच्या घरचे लोक कोणतं काम करतात?",
        "interests": "तुम्हाला कोणतं काम शिकायला आवडेल? उदाहरणार्थ मोबाईल दुरुस्ती, शिवणकाम, सोलर किंवा ड्रायव्हिंग.",
        "can_travel": "प्रशिक्षणासाठी तुम्ही तालुका किंवा जिल्ह्याच्या ठिकाणी जाऊ शकता का?",
        "goal": "तुम्हाला नोकरी करायची आहे की स्वतःचा व्यवसाय सुरू करायचा आहे?",
    },
    "hi": {
        "name": "आपका नाम क्या है?",
        "education": "आपकी पढ़ाई कितनी हुई है?",
        "current_work": "अभी आप क्या काम करते हैं?",
        "family_occupation": "आपके घर के लोग क्या काम करते हैं?",
        "interests": "आपको कौन सा काम सीखना पसंद है? जैसे मोबाइल रिपेयर, सिलाई, सोलर या ड्राइविंग।",
        "can_travel": "ट्रेनिंग के लिए क्या आप तालुका या ज़िले तक जा सकते हैं?",
        "goal": "आप नौकरी करना चाहते हैं या अपना काम शुरू करना चाहते हैं?",
    },
}

# Asked once when an answer is too vague to match a class level or a course.
CLARIFY = {
    "mr": {
        "education": "तुम्ही शाळेत कितवीपर्यंत शिकलात? उदाहरणार्थ आठवी, दहावी, बारावी, ITI किंवा पदवी.",
        "interests": "नक्की कोणतं काम शिकायला आवडेल? उदाहरणार्थ ड्रायव्हिंग, मोबाईल दुरुस्ती, शिवणकाम, सोलर, हॉस्पिटल सहाय्यक किंवा संगणक.",
    },
    "hi": {
        "education": "आपने कितनी कक्षा तक पढ़ाई की है? जैसे आठवीं, दसवीं, बारहवीं, ITI या ग्रेजुएशन।",
        "interests": "आप ठीक से कौन सा काम सीखना चाहेंगे? जैसे ड्राइविंग, मोबाइल रिपेयर, सिलाई, सोलर, हॉस्पिटल सहायक या कंप्यूटर।",
    },
}

CLOSING = {
    "mr": "धन्यवाद! तुमची सगळी माहिती मिळाली. आता मी तुमच्यासाठी योग्य कोर्स शोधते.",
    "hi": "धन्यवाद! आपकी सारी जानकारी मिल गई। अब मैं आपके लिए सही कोर्स ढूंढती हूँ।",
}

SYSTEM_RULES = """You are Disha Vani, a warm, patient phone helpline assistant that guides people in rural
Maharashtra towards government skill-training courses. The caller may have little schooling.

How you speak (your reply is read aloud by a voice engine):
- Simple everyday spoken Marathi, like a kind village didi, not bookish Marathi. Use feminine first person (मी विचारते, सांगते).
- If the caller clearly speaks Hindi, reply in simple Hindi instead.
- Keep everyday English words people actually use: mobile, course, certificate, ITI, driving.
- At most 2 short sentences and exactly ONE question. No lists, emojis, markdown or brackets.
- Briefly acknowledge what they said (one or two words), then ask about the NEXT TOPIC given below.
- If the answer was unclear, gently ask the same topic again in simpler words.
- When you first learn the caller's name, say it once in your reply (e.g. "छान सुरेश!") so they can correct it.
- If the caller corrects something said earlier (for example "नाही, माझं नाव वरद"), update that field and thank them.

Hard rules:
- Never ask about caste, religion, income, phone number, Aadhaar or bank details.
- Never promise a job, money or a specific seat. Never suggest courses yourself; another system does that.
- If the caller goes off-topic, acknowledge kindly in a few words and return to the next topic.

Extraction:
- Put ONLY facts the caller actually said into profile_updates, using these keys and formats:
{slot_guide}
- Leave out anything not said. Never guess.

Reply with JSON only, no other text:
{{"profile_updates": {{...}}, "caller_language": "mr" or "hi", "asked_topic": "the topic key your reply asks about",
 "reply": "your spoken reply"}}"""


def _clean_json(text: str) -> dict:
    """Gemini sometimes wraps JSON in ```json fences; strip them before parsing."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


# Model types that can't do plain text chat, so we never pick them.
_NOT_CHAT = ("tts", "image", "live", "audio", "embedding", "robotics", "omni", "computer", "learnlm")
_model_order = None   # discovered once per run, best first
LAST_MODEL = None     # the model that answered most recently


def _rank_models(names: list) -> list:
    """Newest version first, stable before preview, full Flash before Flash-Lite."""
    def key(name):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        version = float(m.group(1)) if m else 0.0
        preview = "preview" in name or "exp" in name
        if config.GEMINI_PREFER_LITE:  # any stable Flash-Lite first, newest first
            return ("lite" not in name, preview, -version, len(name))
        return (-version, preview, "lite" in name, len(name))
    return sorted(set(names), key=key)


def _discover_models(client) -> list:
    """Ask the key which Flash chat models it may use. Falls back to config's list on failure."""
    global _model_order
    if _model_order is not None:
        return _model_order
    found = []
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            actions = getattr(m, "supported_actions", None) or []
            if ("flash" in name and not any(x in name for x in _NOT_CHAT)
                    and (not actions or "generateContent" in actions)):
                found.append(name)
    except Exception:  # noqa: BLE001
        found = []
    # Old 2.x models are blocked for new keys, so they go last.
    ranked = _rank_models(found)
    ranked = [n for n in ranked if not n.startswith("gemini-2")] + [n for n in ranked if n.startswith("gemini-2")]
    # Your chosen model (GEMINI_MODEL in .env) goes first; everything else stays as backup.
    first = [config.GEMINI_MODEL_FORCED] if config.GEMINI_MODEL_FORCED else []
    _model_order = list(dict.fromkeys(first + ranked + config.GEMINI_MODELS))
    return _model_order


_thinking_ok = True   # set False if this model rejects the low-thinking setting


def _gen_config(types, low_thinking: bool):
    kwargs = {"response_mime_type": "application/json", "temperature": 0.3}
    if low_thinking:
        # A short spoken question needs no deep reasoning; this makes Gemini 3.x reply much faster.
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
    return types.GenerateContentConfig(**kwargs)


def _client(genai, types):
    """Gemini client with a per-request timeout (milliseconds in the SDK)."""
    try:
        return genai.Client(api_key=config.GEMINI_API_KEY,
                            http_options=types.HttpOptions(timeout=int(config.GEMINI_REQUEST_TIMEOUT * 1000)))
    except Exception:  # noqa: BLE001 - older SDKs: fall back to a client without the timeout option
        return genai.Client(api_key=config.GEMINI_API_KEY)


def gemini_call(prompt: str) -> dict:
    """One Gemini call that must return JSON, within GEMINI_TURN_BUDGET seconds or it gives up."""
    global _model_order, LAST_MODEL, _thinking_ok
    from google import genai
    from google.genai import types

    client = _client(genai, types)
    models = _discover_models(client)
    started = time.time()
    errors = []
    for model in list(models):
        for attempt in range(3):
            if time.time() - started > config.GEMINI_TURN_BUDGET:
                raise RuntimeError(f"Gemini too slow (over {config.GEMINI_TURN_BUDGET:.0f}s). "
                                   + " | ".join(errors[-3:]))
            t0 = time.time()
            try:
                resp = client.models.generate_content(
                    model=model, contents=prompt, config=_gen_config(types, _thinking_ok))
                data = _clean_json(resp.text)
                print(f"   gemini {model}: {time.time() - t0:.1f}s ok")
                LAST_MODEL = model
                if models[0] != model:  # remember the one that works so the next turn is fast
                    _model_order = [model] + [m for m in models if m != model]
                return data
            except Exception as e:  # noqa: BLE001 - any failure moves us to retry/fallback
                msg = str(e)
                print(f"   gemini {model}: {time.time() - t0:.1f}s failed ({msg[:80]})")
                if _thinking_ok and "think" in msg.lower():
                    _thinking_ok = False  # this model doesn't accept the setting: retry without it
                    continue
                errors.append(f"{model}: {msg[:90]}")
                if "404" in msg or "NOT_FOUND" in msg:  # model not allowed for this key: drop it
                    _model_order = [m for m in _model_order if m != model]
                break  # rate limit, timeout or other error: move straight to the next model
    raise RuntimeError("All Gemini models failed. " + " | ".join(errors[-3:]))


class Conversation:
    """Holds one call: the profile being built, the transcript, and whether we're done."""

    def __init__(self, llm=gemini_call):
        self.llm = llm
        self.profile = {slot: None for slot in SLOTS}
        self.history = []          # list of {"role": "caller"/"disha", "text": ...}
        self.language = "mr"
        self.turns = 0
        self.done = False
        self.asked = []            # slots asked so far (optional ones are asked once only)
        self.current_question = None  # the slot Disha's last question was about
        self.vague = {}               # slot -> the vague answer we asked about once
        self.clarify_turn = {}        # slot -> turn when we asked the follow-up
        self.events = []           # notes for the officer dashboard (fallbacks, errors)
        self.model_noted = False

    # ---- helpers ------------------------------------------------------------
    def missing(self) -> list:
        return [s for s in REQUIRED if not self.profile.get(s)]

    def next_slot(self):
        for slot in SLOTS:
            if self.profile.get(slot):
                continue
            if slot not in REQUIRED and slot in self.asked:
                continue  # optional topic already asked once; don't push
            return slot
        return None

    def _merge(self, updates: dict) -> None:
        for key, value in (updates or {}).items():
            if key not in self.profile or value in (None, "", []):
                continue
            if key == "interests":
                current = self.profile["interests"] or []
                new = value if isinstance(value, list) else [value]
                self.profile["interests"] = list(dict.fromkeys(current + [str(v).strip() for v in new]))
            else:
                self.profile[key] = str(value).strip()

    def _is_specific(self, slot: str) -> bool:
        value = self.profile.get(slot)
        if slot == "education":
            return recommender.parse_education(value)["known"]
        if slot == "interests":
            return any(recommender._matches(value or [], c["tags"]) for c in recommender.COURSES)
        return True

    def _clarify_if_vague(self):
        """Ask ONE follow-up when education or interests can't be matched; then accept whatever comes."""
        for slot in ("education", "interests"):
            if slot in self.clarify_turn and self.turns > self.clarify_turn[slot] and not self.profile.get(slot):
                self.profile[slot] = self.vague[slot]  # still nothing usable: keep their first answer and move on
            if self.profile.get(slot) and slot not in self.clarify_turn and not self._is_specific(slot):
                self.vague[slot] = self.profile[slot]
                self.clarify_turn[slot] = self.turns
                self.events.append(f"turn {self.turns}: asked to clarify {slot} (heard: {self.vague[slot]})")
                self.profile[slot] = None
                self.current_question = slot
                return CLARIFY[self.language][slot]
        return None

    def _say(self, text: str) -> dict:
        self.history.append({"role": "disha", "text": text})
        return {"reply": text, "language": self.language, "done": self.done, "profile": self.profile}

    # ---- the call -----------------------------------------------------------
    def start(self) -> dict:
        self.asked.append("name")
        self.current_question = "name"
        return self._say(GREETING["mr"])

    def handle(self, caller_text: str) -> dict:
        """Process one caller answer and return Disha's next spoken reply."""
        caller_text = (caller_text or "").strip()
        if self.done:
            return self._say(CLOSING[self.language])
        self.turns += 1
        self.history.append({"role": "caller", "text": caller_text})

        target = self.current_question or self.next_slot()
        asked_topic = None
        try:
            result = self.llm(self._build_prompt(caller_text, target))
            self._merge(result.get("profile_updates"))
            if result.get("caller_language") in ("mr", "hi"):
                self.language = result["caller_language"]
            reply = (result.get("reply") or "").strip()
            asked_topic = result.get("asked_topic")
            if LAST_MODEL and not self.model_noted:
                self.events.append(f"Gemini model in use: {LAST_MODEL}")
                self.model_noted = True
        except Exception as e:  # noqa: BLE001 - keep the call alive no matter what
            self.events.append(f"turn {self.turns}: LLM failed, used fallback ({str(e)[:300]})")
            if target and caller_text:
                self._merge({target: [caller_text] if target == "interests" else caller_text})
            reply = ""

        follow_up = self._clarify_if_vague() if self.turns < config.MAX_TURNS else None
        if follow_up:
            return self._say(follow_up)

        nxt = self.next_slot()
        if not self.missing() or self.turns >= config.MAX_TURNS:
            self.done = True
            if self.missing():
                self.events.append(f"ended at turn limit; missing: {', '.join(self.missing())}")
            return self._say(CLOSING[self.language])

        if reply and asked_topic in SLOTS and not self.profile.get(asked_topic):
            nxt = asked_topic  # trust the topic Gemini actually asked about
        if not reply:
            reply = FALLBACK_QUESTIONS[self.language][nxt]
        if nxt not in self.asked:
            self.asked.append(nxt)
        self.current_question = nxt
        return self._say(reply)

    def _build_prompt(self, caller_text: str, target) -> str:
        slot_guide = "\n".join(f"  {k}: {v}" for k, v in SLOT_GUIDE.items())
        recent = "\n".join(f"{h['role'].upper()}: {h['text']}" for h in self.history[-8:])
        skip_optional = [s for s in SLOTS if s not in REQUIRED and s in self.asked]
        return (
            SYSTEM_RULES.format(slot_guide=slot_guide)
            + f"\n\nProfile so far: {json.dumps(self.profile, ensure_ascii=False)}"
            + f"\nTopic the caller was just answering: {target}"
            + f"\nNEXT TOPIC: after applying your profile_updates, ask about the FIRST topic in this order "
              f"that is still unknown: {', '.join(SLOTS)}."
            + (f" Skip these optional topics, already asked once: {', '.join(skip_optional)}." if skip_optional else "")
            + f"\n\nRecent conversation:\n{recent}"
            + f"\n\nCaller's latest answer: {caller_text}"
        )

    def summary(self) -> dict:
        return {"profile": self.profile, "turns": self.turns, "done": self.done,
                "language": self.language, "history": self.history, "events": self.events}
