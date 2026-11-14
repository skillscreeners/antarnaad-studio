#!/usr/bin/env python3
"""Keeps the quote supply topped up so reels never repeat (standard library only).

When a pool (Hindi/English x life/work) has fewer than LOW unused quotes, asks Gemini's text model for
new ORIGINAL short motivational lines in the Antarnaad style, credited to "Antarnaad" (never to a real
person), checks them and appends them to data/generated.json through the GitHub API.
Runs from the 10-minute check job at most every 3 hours.
"""
import datetime as dt, hashlib, json, os, re, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_stats, feedback, plan

LOW, BATCH, EVERY_H = 20, 15, 3
MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
BLOCK = ["love", "kiss", "sex", "romance", "girlfriend", "boyfriend", "death", "die ", "dead", "kill", "suicide", "blood",
         "war", "hate", "revenge", "betray", "alcohol", "drunk", "party", "religion", "caste", "modi", "gandhi", "congress",
         "bjp", "प्यार", "इश्क", "मोहब्बत", "मौत", "मरना", "खून", "धोखा", "नफ़रत", "नफरत", "बेवफ़ा", "बदला", "शराब", "जाति",
         "महबूब", "आशिक", "दिल टूट"]
TOPICS = {"life": "self-belief, patience, hope, calm mind, gratitude, kindness, resilience, learning, simple living, starting again",
          "work": "hard work, discipline, punctuality, focus, honesty at work, skill-building, finishing what you start, quality, teamwork"}

def _norm(s):
    return re.sub(r"[\W_]+", "", s.lower())

def prompt(lang, theme, avoid):
    lang_rule = ("Write in simple, natural Hindi (Devanagari), like popular Indian 'suvichar' posts. "
                 "Give an English translation in 'subtitle'. 'hook' is a short Hindi lead-in such as 'आज की बात:'."
                 if lang == "hi" else
                 "Write in simple English. Give a Hindi (Devanagari) translation in 'subtitle'. "
                 "'hook' is a short English lead-in such as 'Remember this:'.")
    return (f"Create {BATCH} ORIGINAL short motivational lines for a family-friendly Indian YouTube Shorts channel. "
            f"Themes: {TOPICS[theme]}. {lang_rule} Each item: 2 to 4 short lines, each line at most 28 characters, "
            "written to be read aloud in about 6 seconds. Positive and uplifting only: no romance, heartbreak, betrayal, "
            "revenge, death, religion, caste, politics or named people. Do NOT reuse famous quotes or sayings by anyone; "
            "write new lines. Do not repeat or closely paraphrase any of these existing lines: "
            + " | ".join(avoid[-80:]) +
            '. Return only JSON: [{"hook": "...", "lines": ["...", "..."], "subtitle": "..."}]')

def ask_gemini(text):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=90))
    return json.loads(r["candidates"][0]["content"]["parts"][0]["text"])

def valid(item, lang, seen):
    try:
        lines = [l.strip() for l in item["lines"]]
        hook, sub = item["hook"].strip(), item["subtitle"].strip()
    except Exception:
        return None
    if not (2 <= len(lines) <= 4) or any(not (2 <= len(l) <= 34) for l in lines) or len(hook) > 40 or len(sub) > 120:
        return None
    text = " ".join(lines + [hook, sub]).lower()
    if any(b in text for b in BLOCK) or '"' in " ".join(lines):
        return None
    deva = all(re.search(r"[ऀ-ॿ]", l) for l in lines)
    if (lang == "hi") != deva or not re.search(r"[ऀ-ॿ]", sub if lang == "en" else hook):
        return None
    key = _norm("".join(lines))
    if key in seen:
        return None
    seen.add(key)
    return lines, hook, sub

def main(force=False, dry=False):
    gen, sha = collect_stats.get_file("data/generated.json")
    gen = gen or []
    meta = next((g for g in gen if isinstance(g, dict) and g.get("_meta")), None)
    now = dt.datetime.now(dt.timezone.utc)
    if meta and not force and (now - dt.datetime.fromisoformat(meta["updated"])).total_seconds() < EVERY_H * 3600:
        print("refill: checked recently"); return
    if not os.environ.get("GEMINI_API_KEY"):
        print("refill: no GEMINI_API_KEY"); return
    quotes = plan._bank() + [g for g in gen if isinstance(g, dict) and not g.get("_meta") and g["id"] not in {q["id"] for q in plan._bank()}]
    used = feedback.used_ids()
    seen = {_norm("".join(q["lines"])) for q in quotes}
    added = 0
    for lang in ("hi", "en"):
        for theme in ("life", "work"):
            pool = [q for q in quotes if (q["lang"], q.get("theme", "life")) == (lang, theme)]
            unused = [q for q in pool if q["id"] not in used]
            if len(unused) >= LOW and not force:
                continue
            try:
                items = ask_gemini(prompt(lang, theme, [" / ".join(q["lines"]) for q in pool]))
            except Exception as e:
                print(f"::warning::refill {lang}/{theme} failed: {e}"); continue
            moods = ["uplifting", "calm", "rising", "gentle"] + (["raga"] if lang == "hi" else [])
            for it in items if isinstance(items, list) else []:
                v = valid(it, lang, seen)
                if not v:
                    continue
                lines, hook, sub = v
                qid = f"ai-{lang}-{theme}-{hashlib.sha1(''.join(lines).encode()).hexdigest()[:8]}"
                gen.append({"id": qid, "lang": lang, "theme": theme, "hook": hook, "lines": lines, "subtitle": sub,
                            "author": "अंतर्नाद" if lang == "hi" else "Antarnaad", "author_en": "Antarnaad",
                            "source": "Antarnaad original", "mood": moods[int(qid[-2:], 16) % len(moods)],
                            "topic_tags": (["#Suvichar", "#HindiQuotes", "#Motivation"] if lang == "hi" else
                                           ["#MotivationalQuotes", "#DailyMotivation", "#Mindset"]) + (["#WorkEthic"] if theme == "work" else []),
                            "added": now.date().isoformat()})
                added += 1
                print(f"  + {lang}/{theme}: {' / '.join(lines)}")
            print(f"refill {lang}/{theme}: had {len(unused)} unused")
    gen = [g for g in gen if not (isinstance(g, dict) and g.get("_meta"))] + [{"_meta": True, "updated": now.isoformat(timespec="seconds")}]
    if dry:
        print(f"refill (dry run): would add {added}"); return
    collect_stats.put_file("data/generated.json", gen, sha, f"refill: +{added} original lines")
    print(f"refill: added {added}")

if __name__ == "__main__":
    main(force="--force" in sys.argv, dry="--dry" in sys.argv)
