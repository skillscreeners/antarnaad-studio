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

# 10 slots a day, 90 minutes apart. Odd slots Hindi, even slots English.
_TIMES = ["07:10", "08:40", "10:10", "11:40", "13:10", "14:40", "16:10", "17:40", "19:10", "20:40"]
SLOTS = list(range(1, len(_TIMES) + 1))
NEWS_SLOT = 6   # "In the News": uses data/trending.json[date] when present
_P = ["Subah ka Vichar", "Global Greats", "Indian Icons", "Life Lessons"]
PILLARS = {s: ("In the News" if s == NEWS_SLOT else _P[(s - 1) % len(_P)]) for s in SLOTS}
_M = ["uplifting", "calm", "raga", "gentle", "rising"]
_S = ["sunrise_mountains", "misty_path", "dunes_sunset", "starry_night", "storm_light"]
MOODS = {s: _M[(s - 1) % len(_M)] for s in SLOTS}
SCENES = {s: _S[(s - 1) % len(_S)] for s in SLOTS}
# IST post times. Off-the-hour minutes avoid the :00 rush.
TIMES = {"weekday": dict(zip(SLOTS, _TIMES)), "weekend": dict(zip(SLOTS, _TIMES))}

def slot_langs(day_index):
    """Odd slots Hindi, even slots English (5 + 5 a day)."""
    return {s: ("hi" if s % 2 == 1 else "en") for s in SLOTS}

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
    if slot == NEWS_SLOT and date.isoformat() in trending:
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
    for slot in SLOTS:
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
        print(day, " | ".join(f"{post_time(day, s)} {quote_for(day, s)['id']}" for s in SLOTS))
