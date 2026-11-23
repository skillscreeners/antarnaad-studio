#!/usr/bin/env python3
"""Daily news hook (standard library only): reads India's top headlines each morning, lets Gemini pick
up to two uplifting events (sport, science, space, awards, festivals, inspiring people) and match each
to an UNUSED verified quote from the bank. Writes data/trending.json[today]; the 14:40 and 17:40
reels then post them with a short line about the event and the news link in the description.
Politics, crime, accidents, deaths, disasters, war and controversy are excluded.
"""
import datetime as dt, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_stats, feedback, plan

FEEDS = ["https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
         "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
         "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-IN&gl=IN&ceid=IN:en",
         "https://news.google.com/rss?hl=hi&gl=IN&ceid=IN:hi"]
BAD = ["election", "poll", "bjp", "congress", "aap", "ncp", "shiv sena", "minister", "modi", "rahul", "protest", "riot",
       "kill", "dead", "death", "dies", "died", "murder", "rape", "attack", "accident", "crash", "flood", "fire", "war",
       "terror", "arrest", "scam", "court", "police", "suicide", "pakistan", "china", "tariff", "stock", "sensex", "nifty",
       "cancer", "tumour", "tumor", "drug", "trial", "patient", "cure", "vaccine", "disease", "virus", "covid", "doctor",
       "hospital", "medicine", "diabetes", "heart attack", "study finds", "health",
       "कैंसर", "दवा", "मरीज", "बीमारी", "इलाज", "अस्पताल",
       "मौत", "हत्या", "हादसा", "चुनाव", "हमला", "गिरफ्तार", "मंत्री", "भाजपा", "कांग्रेस"]

def headlines():
    out, seen = [], set()
    for url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AntarnaadStudio/1.0"})
            root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
        except Exception as e:
            print(f"news: feed failed {url}: {e}"); continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            src = (it.find("source").text if it.find("source") is not None else "") or ""
            key = title.lower()[:60]
            if title and key not in seen and not any(b in title.lower() for b in BAD):
                seen.add(key)
                out.append({"title": title, "source": src.strip(), "link": (it.findtext("link") or "").strip()})
    return out[:70]

def main(force=False, dry=False):
    now = dt.datetime.now(plan.IST)
    today = now.date().isoformat()
    trending, sha = collect_stats.get_file("data/trending.json")
    trending = trending or {}
    if today in trending and not force:
        print("news: already chosen for today"); return
    if not force and not (6 <= now.hour < 13):
        print("news: outside the morning window"); return
    if not os.environ.get("GEMINI_API_KEY"):
        print("news: no GEMINI_API_KEY"); return
    heads = headlines()
    if not heads:
        print("::warning::news: no headlines"); return
    used = {feedback.base_id(u) for u in feedback.used_ids()}
    cands = [q for q in plan._bank() if feedback.base_id(q["id"]) not in used and q["author_en"] != "Antarnaad"]
    cands += [q for q in plan._bank() if feedback.base_id(q["id"]) not in used and q["author_en"] == "Antarnaad"][:40]
    import refill
    ask = ("You help a family-friendly Indian motivational YouTube channel. From today's headlines, pick at most 2 genuinely "
           "uplifting events: sporting wins, science or space milestones, awards, record achievements, festivals, inspiring "
           "ordinary people. Never pick politics, government decisions, elections, crime, accidents, deaths, disasters, war, "
           "conflict, business or markets, celebrity gossip or anything controversial. If nothing qualifies return [].\n"
           "For each event choose the best-fitting quote id from QUOTES (its message must suit the event) and write a short "
           "factual hook (max 45 characters) that names the event using ONLY facts stated in the headline, in the quote's "
           "language (English or Hindi), ending with a colon, e.g. 'Congratulations, Team India!' or 'ISRO ने रचा इतिहास:'.\n"
           'Return only JSON: [{"headline": <number>, "quote": "<id>", "hook": "..."}]\n\nHEADLINES:\n'
           + "\n".join(f"{i}. {h['title']}" for i, h in enumerate(heads))
           + "\n\nQUOTES:\n" + "\n".join(f"{q['id']} ({q['lang']}): {' '.join(q['lines'])[:90]} — {q['author_en']}" for q in cands))
    try:
        picks = refill.ask_gemini(ask)
    except Exception as e:
        print(f"::warning::news: Gemini failed: {e}"); return
    by_id = {q["id"]: q for q in cands}
    entries = []
    for p in picks if isinstance(picks, list) else []:
        try:
            h = heads[int(p["headline"])]; q = dict(by_id[p["quote"]]); hook = str(p["hook"]).strip()
        except Exception:
            continue
        if not (4 <= len(hook) <= 50) or any(b in (hook + h["title"]).lower() for b in BAD) or q["id"] in {e["id"] for e in entries}:
            continue
        if not hook.endswith(":"):
            hook = hook.rstrip("!.। ") + ":"
        # the headline is NOT put on screen or in the title (shortened headlines distort facts);
        # the quote keeps its own lead-in and the exact headline goes in the description only
        q.update(news=h, news_hook=hook, topic_tags=q.get("topic_tags", [])[:2] + ["#InTheNews"])
        entries.append(q)
        print(f"news: {h['title']}  ->  {q['id']}  [{hook}]")
    if not entries:
        print("news: nothing uplifting enough today; regular reels will post")
        entries = []
    trending[today] = entries[:2] if entries else []
    if dry:
        print("news (dry run):", json.dumps(trending[today], ensure_ascii=False)[:600]); return
    collect_stats.put_file("data/trending.json", trending, sha, f"news: {len(entries)} reel(s) for {today}")

if __name__ == "__main__":
    main(force="--force" in sys.argv, dry="--dry" in sys.argv)
