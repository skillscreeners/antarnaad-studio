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

WORK_SLOTS = {2, 3}   # weekdays 08:40 (English) and 10:10 (Hindi): work motivation for the start of the day

def slot_pool(date, slot):
    """(language, theme) pool a slot draws from."""
    lang = slot_langs(0)[slot]
    theme = "work" if (slot in WORK_SLOTS and date.weekday() < 5) else "life"
    return lang, theme

def _bank():
    return json.load(open(os.path.join(ROOT, "data", "quote_bank.json"), encoding="utf-8"))

def _nth(pool, n, key):
    """n-th quote of a fixed shuffled rotation through pool: each quote waits a full lap before repeating.
    New quotes added to the bank slot into the rotation automatically."""
    order = sorted(pool, key=lambda q: q["id"])
    random.Random(f"antarnaad-{key}").shuffle(order)
    return order[n % len(order)]

def _uses_before(date, slot, key):
    """How many times pool `key` was used from EPOCH up to (not including) this slot."""
    n = 0
    for k in range(max(0, (date - EPOCH).days)):
        day = EPOCH + dt.timedelta(days=k)
        n += sum(1 for s in SLOTS if slot_pool(day, s) == key)
    n += sum(1 for s in SLOTS if s < slot and slot_pool(date, s) == key)
    return n

def _special_days():
    path = os.path.join(ROOT, "data", "special_days.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}

def all_quotes():
    """Quote bank plus every festival quote (for stats matching)."""
    qs = list(_bank())
    for day in _special_days().values():
        qs += [q for q in day.get("slots", {}).values() if "ref" not in q]
    return qs

def _special(date):
    """{slot: quote} for a festival / national day (data/special_days.json).
    An entry {"ref": "<quote id>"} reuses a quote from the bank or another festival."""
    slots = _special_days().get(date.isoformat(), {}).get("slots", {})
    if any("ref" in q for q in slots.values()):
        by_id = {q["id"]: q for q in all_quotes()}
        slots = {k: (by_id[q["ref"]] if "ref" in q else q) for k, q in slots.items()}
    return slots

def _special_name(date):
    return _special_days().get(date.isoformat(), {}).get("name")

import functools

@functools.lru_cache(maxsize=512)
def _quote_for(date, slot):
    return quote_for_uncached(date, slot)

def quote_for(date, slot):
    date = dt.date.fromisoformat(date) if isinstance(date, str) else date
    return dict(_quote_for(date, slot))

def quote_for_uncached(date, slot):
    date = dt.date.fromisoformat(date) if isinstance(date, str) else date
    trending = json.load(open(os.path.join(ROOT, "data", "trending.json"), encoding="utf-8"))
    special = _special(date).get(str(slot))
    if special:
        q = dict(special); q.setdefault("theme", "life"); q["special"] = _special_name(date)
    elif slot == NEWS_SLOT and date.isoformat() in trending:
        q = dict(trending[date.isoformat()])
        q.setdefault("lang", "en")
    else:
        key = slot_pool(date, slot)
        pool = [q for q in _bank() if (q["lang"], q.get("theme", "life")) == key]
        pick = None
        if os.environ.get("ANTARNAAD_FEEDBACK", "1") == "1":
            import feedback
            earlier = [quote_for(date, s) for s in SLOTS if s < slot]   # same-day picks, even if history is behind
            today = {h["id"] for h in feedback.history() if h["date"] == date.isoformat()} | {e["id"] for e in earlier}
            pick = feedback.pick(pool, date, slot, used_today=today, authors_today=[e.get("author_en") for e in earlier])
        q = dict(pick or _nth(pool, _uses_before(date, slot, key), f"{key[0]}-{key[1]}"))
    pillar = q["special"] if q.get("special") else "Work Motivation" if q.get("theme") == "work" and slot in WORK_SLOTS else PILLARS[slot]
    mood = q.get("mood") or MOODS[slot] if not (MOODS[slot] == "raga" and q["lang"] != "hi") else "gentle"
    q.update(slot=slot, pillar=pillar, mood=mood, scene=q.get("scene", SCENES[slot]), date=date.isoformat())
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
        if dt.timedelta(minutes=0) <= now - start <= dt.timedelta(minutes=window_min):
            return slot
    return None

if __name__ == "__main__":
    import sys
    start = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else dt.datetime.now(IST).date()
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    for i in range(days):
        day = start + dt.timedelta(days=i)
        print(day, " | ".join(f"{post_time(day, s)} {quote_for(day, s)['id']}" for s in SLOTS))
