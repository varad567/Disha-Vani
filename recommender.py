"""
Disha Vani - course recommender.

Plain Python rules, no LLM, so every suggestion can be explained:
  1. ELIGIBILITY  each course lists its official entry routes from the NQR (for example
                  "10th pass" OR "8th pass + 2 years' experience"). A caller is eligible
                  directly, eligible only with work experience, or not eligible.
  2. SCORE        by interest match and goal match. Direct eligibility ranks above
                  experience-only eligibility.
  3. GUARDRAIL    family occupation is applied only AFTER the ranking is fixed. It may ADD at
                  most one optional course; it can never remove a course or change the order.
  4. HONESTY      if the caller asked for a trade they are not eligible for, Disha says so
                  and explains what is needed, instead of silently hiding it.
"""

import json
import re
from pathlib import Path

DATA = json.loads((Path(__file__).resolve().parent / "courses.json").read_text(encoding="utf-8"))
COURSES = DATA["courses"]
TOP_N = 3
NEEDS_MR = {"iti": "ITI", "diploma": "डिप्लोमा"}
NEEDS_EN = {"iti": "ITI", "diploma": "a diploma"}


# ---- understanding the caller's education ------------------------------------------
def parse_education(text) -> dict:
    """'12th pass' -> 12 years; '10th + ITI' -> 10 years with ITI; 'no schooling' -> 0.
    Unknown education -> 8 years, so nobody is blocked just because the answer was unclear."""
    result = {"years": 8, "iti": False, "diploma": False, "known": False}
    if not text:
        return result
    t = str(text).lower().translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    result["iti"] = "iti" in t or "आयटीआय" in t or "nac" in t or "ntc" in t
    result["diploma"] = "diploma" in t or "डिप्लोमा" in t
    if any(w in t for w in ("graduate", "degree", "b.a", "b.com", "b.sc", "पदवी")):
        result.update(years=15, known=True)
        return result
    if any(w in t for w in ("no school", "none", "illiterate", "शाळा नाही", "अशिक्षित", "शिकलो नाही")):
        result.update(years=0, known=True)
        return result
    if any(w in t for w in ("college", "student", "studying", "b.tech", "btech", "engineering", "bachelor",
                            "computer science", "कॉलेज", "इंजिनिअरिंग")) and not re.search(r"\d", t):
        result.update(years=12, known=True)  # in college means at least 12th pass
        return result
    m = re.search(r"\d+", t)
    if m:
        result.update(years=min(int(m.group()), 15), known=True)
    else:
        words = {"बारावी": 12, "अकरावी": 11, "दहावी": 10, "नववी": 9, "आठवी": 8, "सातवी": 7, "पाचवी": 5, "चौथी": 4}
        for word, years in words.items():
            if word in t:
                result.update(years=years, known=True)
                break
    if (result["iti"] or result["diploma"]) and not m:
        result["years"] = max(result["years"], 10)  # ITI/diploma alone usually follows 10th
    return result


def check_eligibility(course: dict, edu: dict) -> dict:
    """Best matching official entry route: 'direct', 'with_experience' (needs N years' work) or 'no'."""
    best = None
    for route in course["routes"]:
        need = route.get("needs")
        if need == "iti" and not edu["iti"]:
            continue
        if need == "diploma" and not edu["diploma"]:
            continue
        if edu["years"] < route["edu"]:
            continue
        if route["exp"] == 0:
            return {"status": "direct", "exp_years": 0}
        if best is None or route["exp"] < best["exp_years"]:
            best = {"status": "with_experience", "exp_years": route["exp"]}
    return best or {"status": "no", "exp_years": None}


def _easiest_routes(course: dict) -> list:
    """Up to two simplest official entry routes, preferring ones that need no work experience."""
    direct = [r for r in course["routes"] if r["exp"] == 0]
    pool = direct or course["routes"]
    seen, picked = set(), []
    for r in sorted(pool, key=lambda r: (r["exp"], r.get("needs") is not None, r["edu"])):
        key = (r.get("needs"), r["exp"])  # "8th + ITI" makes "10th + ITI" redundant
        if key not in seen:
            seen.add(key)
            picked.append(r)
    return picked[:2]


def why_not_eligible_mr(course: dict) -> str:
    """Plain Marathi explanation of what the caller would need, e.g. '12वी पास, किंवा 10वी पास आणि डिप्लोमा'."""
    options = []
    for r in _easiest_routes(course):
        parts = [f"{r['edu']}वी पास"] if r["edu"] else []
        if r.get("needs"):
            parts.append(NEEDS_MR[r["needs"]])
        if r["exp"]:
            parts.append(f"{r['exp']} वर्षांचा अनुभव")
        options.append(" आणि ".join(parts))
    return ", किंवा ".join(o for o in options if o) or "विशेष पात्रता"


def why_not_eligible_en(course: dict) -> str:
    options = []
    for r in _easiest_routes(course):
        parts = [f"class {r['edu']} pass"] if r["edu"] else []
        if r.get("needs"):
            parts.append(NEEDS_EN[r["needs"]])
        if r["exp"]:
            parts.append(f"{r['exp']} years' experience")
        options.append(" + ".join(parts))
    return ", or ".join(o for o in options if o) or "a specific prior qualification"


# ---- matching and scoring -------------------------------------------------------------
def _matches(words, tags) -> list:
    """Which tags appear in what the caller said (either direction, case-insensitive)."""
    hits = []
    for w in words:
        w = str(w).lower().strip()
        if not w:
            continue
        for tag in tags:
            if tag in w or w in tag:
                hits.append(tag)
    return list(dict.fromkeys(hits))


def _score(course: dict, profile: dict, elig: dict):
    reasons, score = [], 0
    hits = _matches(profile.get("interests") or [], course["tags"])
    if hits:
        score += 50 + (15 if course["tags"][0] in hits else 0)
        reasons.append("matches what you want to learn")
    goal = profile.get("goal") or "either"
    if goal == "either" or course["mode"] == goal:
        score += 20
        reasons.append("leads to a job" if course["mode"] == "job" else "lets you start your own work")
    if elig["status"] == "direct":
        score += 10
        reasons.append("you meet the entry criteria")
    else:
        reasons.append(f"needs {elig['exp_years']} years' work experience to enter")
    return score, reasons, bool(hits)


def recommend(profile: dict) -> dict:
    edu = parse_education(profile.get("education"))
    interests = profile.get("interests") or []

    ranked, blocked = [], []
    for c in COURSES:
        elig = check_eligibility(c, edu)
        if elig["status"] == "no":
            if _matches(interests, c["tags"]):
                blocked.append(c)
            continue
        score, reasons, hit = _score(c, profile, elig)
        ranked.append({"course": c, "score": score, "reasons": reasons, "interest_hit": hit, "elig": elig})
    ranked.sort(key=lambda r: (-r["score"], r["course"]["hours"]))

    # ---- Step 1-2: the ranking never looks at family occupation -----------------------
    top = ranked[:TOP_N]
    base_ids = [r["course"]["id"] for r in top]

    # ---- Step 3: guardrail - family occupation may only ADD one option ----------------
    family = (profile.get("family_occupation") or "").lower()
    added = []
    if family:
        for r in ranked[TOP_N:]:
            if _matches([family], r["course"]["family_links"]):
                r["reasons"] = ["related to your family's work (optional extra)"] + r["reasons"]
                r["family_extra"] = True
                added.append(r)
                break
    final = top + added
    final_ids = [r["course"]["id"] for r in final]
    guardrail = {
        "family_occupation": profile.get("family_occupation"),
        "added": [r["course"]["id"] for r in added],
        "removed": [i for i in base_ids if i not in final_ids],
        "order_unchanged": final_ids[:len(base_ids)] == base_ids,
    }
    guardrail["passed"] = not guardrail["removed"] and guardrail["order_unchanged"]
    if not guardrail["passed"]:  # should never happen; fall back to the safe list
        final = top

    blocked_info = [{"id": c["id"], "name_en": c["name_en"], "name_mr": c["name_mr"],
                     "needs_mr": why_not_eligible_mr(c), "needs_en": why_not_eligible_en(c),
                     "code": c["code"], "source": c["source"]} for c in blocked[:1]]

    note = None
    if blocked_info:
        b = blocked_info[0]
        note = f"Asked for {b['name_en']}, which needs {b['needs_en']}; closest eligible options shown."
    elif not any(r["interest_hit"] for r in top):
        note = "No course in the verified list matches the stated interest; showing eligible options instead."
    if not edu["known"]:
        note = (note + " " if note else "") + "Education was unclear, so the officer should confirm eligibility."

    return {
        "education": edu,
        "recommendations": [_card(r) for r in final],
        "not_eligible": blocked_info,
        "guardrail": guardrail,
        "note": note,
        "eligible_count": len(ranked),
        "data_note": DATA["note"],
    }


def _card(r: dict) -> dict:
    c = r["course"]
    return {
        "id": c["id"], "name_en": c["name_en"], "name_mr": c["name_mr"], "code": c["code"], "body": c["body"],
        "level": c["level"], "hours": c["hours"], "mode": c["mode"],
        "requirements_mr": c["requirements_mr"], "requirements_en": c["requirements_en"],
        "note_mr": c["note_mr"], "note_en": c["note_en"],
        "outcome_en": c["outcome_en"], "outcome_mr": c["outcome_mr"], "source": c["source"],
        "eligibility": r["elig"]["status"], "exp_years": r["elig"]["exp_years"],
        "reasons": r["reasons"], "family_extra": r.get("family_extra", False), "score": r["score"],
    }


def _level_mr(level) -> str:
    return str(level).rstrip("0").rstrip(".") if isinstance(level, float) else str(level)


def speech(result: dict, language: str = "mr") -> str:
    """Short spoken summary of the top options, for Disha to read aloud."""
    recs = [r for r in result["recommendations"] if not r["family_extra"]][:2]
    blocked = result.get("not_eligible") or []
    if language == "hi":
        if not recs:
            return "माफ़ कीजिए, अभी सही कोर्स नहीं मिला। अधिकारी जल्द संपर्क करेंगे।"
        text = f"पहला विकल्प {recs[0]['name_mr']}, लगभग {recs[0]['hours']} घंटे का प्रशिक्षण।"
        if len(recs) > 1:
            text += f" दूसरा विकल्प {recs[1]['name_mr']}।"
        return text + " पूरी जानकारी स्क्रीन पर है, और अधिकारी आपसे आगे बात करेंगे।"

    parts = []
    if blocked:
        parts.append(f"तुम्ही विचारलेल्या {blocked[0]['name_mr']} कोर्ससाठी {blocked[0]['needs_mr']} लागतं.")
    if not recs:
        return " ".join(parts + ["सध्या योग्य कोर्स सापडला नाही. अधिकारी तुम्हाला लवकरच संपर्क करतील."])
    first = recs[0]
    parts.append(f"तुमच्यासाठी पहिला पर्याय, {first['name_mr']}. हे सुमारे {first['hours']} तासांचं प्रशिक्षण आहे. "
                 f"यानंतर {first['outcome_mr']}.")
    if first["requirements_mr"]:
        parts.append(f"यासाठी {first['requirements_mr']} आवश्यक आहे.")
    if first["note_mr"]:
        parts.append(first["note_mr"])
    if first["eligibility"] == "with_experience":
        parts.append(f"या कोर्ससाठी {first['exp_years']} वर्षांचा कामाचा अनुभव लागतो.")
    if len(recs) > 1:
        parts.append(f"दुसरा पर्याय, {recs[1]['name_mr']}.")
    return " ".join(parts) + " अधिकारी तुम्हाला पुढची माहिती देतील."
