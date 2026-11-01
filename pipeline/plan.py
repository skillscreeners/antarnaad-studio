"""Decides which quote goes in which slot on any date, with no stored state.

Each language pool is shuffled once per cycle (seeded), and days walk through it in order,
so a quote does not come back until its whole pool has been used.
Slot 3 ("In the News") takes data/trending.json[date] when present.
"""
import datetime as dt
import json, os, random

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EPOCH = dt.date(2026, 11, 1)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

PILLARS = {1: "Subah ka Vichar", 2: "Global Greats", 3: "In the News", 4: "Indian Icons", 5: "Life Lessons"}
MOODS = {1: "uplifting", 2: "calm", 3: "rising", 4: "raga", 5: "gentle"}
SCENES = {1: "sunrise_mountains", 2: "misty_path", 3: "storm_light", 4: "dunes_sunset", 5: "starry_night"}
# IST post times. Off-the-hour minutes avoid the :00 rush.
TIMES = {"weekday": {1: "07:40", 2: "10:50", 3: "12:50", 4: "18:40", 5: "20:50"},
         "weekend": {1: "08:40", 2: "11:10", 3: "13:20", 4: "17:40", 5: "21:10"}}

def slot_langs(day_index):
    """Hindi in the morning and evening slots, English mid-morning and night; slot 3 alternates."""
    return {1: "hi", 2: "en", 3: "hi" if day_index % 2 == 0 else "en", 4: "hi", 5: "en"}

def _bank():
    return json.load(open(os.path.join(ROOT, "data", "quote_bank.json"), encoding="utf-8"))

def _nth(pool, n):
    """n-th quote of an endless sequence of shuffled cycles through pool."""
    cycle, pos = divmod(n, len(pool))
    order = sorted(pool, key=lambda q: q["id"])
    random.Random(f"antarnaad-{pool[0]['lang']}-{cycle}").shuffle(order)
    return order[pos]

def quote_for(date, slot):
    date = dt.date.fromisoformat(date) if isinstance(date, str) else date
    d = (date - EPOCH).days
    trending = json.load(open(os.path.join(ROOT, "data", "trending.json"), encoding="utf-8"))
    if slot == 3 and date.isoformat() in trending:
        q = dict(trending[date.isoformat()])
        q.setdefault("lang", "en")
    else:
        bank = _bank()
        lang = slot_langs(d)[slot]
        pool = [q for q in bank if q["lang"] == lang]
        # how many quotes of this language were used before this slot, counting from EPOCH
        before = sum(list(slot_langs(k).values()).count(lang) for k in range(max(0, d)))
        before += [slot_langs(d)[s] for s in range(1, slot)].count(lang)
        q = dict(_nth(pool, before))
    q.update(slot=slot, pillar=PILLARS[slot], mood=MOODS[slot] if not (MOODS[slot] == "raga" and q["lang"] != "hi") else "gentle",
             scene=q.get("scene", SCENES[slot]), date=date.isoformat())
    return q

def post_time(date, slot):
    date = dt.date.fromisoformat(date) if isinstance(date, str) else date
    return TIMES["weekend" if date.weekday() >= 5 else "weekday"][slot]

def slot_now(now=None, window_min=75):
    """Which slot is due right now (IST), allowing for GitHub's cron delays."""
    now = now or dt.datetime.now(IST)
    for slot in range(1, 6):
        hh, mm = map(int, post_time(now.date(), slot).split(":"))
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt.timedelta(minutes=-10) <= now - start <= dt.timedelta(minutes=window_min):
            return slot
    return None

if __name__ == "__main__":
    import sys
    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(IST).date()
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    for i in range(days):
        day = start + dt.timedelta(days=i)
        print(day, " | ".join(f"{post_time(day, s)} {quote_for(day, s)['id']}" for s in range(1, 6)))
