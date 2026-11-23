#!/usr/bin/env python3
"""Standard-library check: is a story video due now?

Story videos post every other day (from 24 Nov 2026) at a different evening time each time,
between 18:00 and 20:30 IST, when Indian viewers watch longer videos. The time comes from a hash
of the date, so every check in the day agrees on it. Tags: posted-story-DATE when done,
story-fail-DATE-HHMM after a failed attempt (wait 40 minutes, at most 3 attempts a day).
"""
import datetime as dt, hashlib, json, os, sys, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import due, plan

FIRST_DAY = dt.date(2026, 11, 24)
EVENING = (18, 0)          # earliest post time
SPREAD_MIN = 150           # ... up to 20:30 (checks run until 22:00, leaving time to retry)
RETRY_MIN, MAX_TRIES = 40, 3

def is_story_day(date):
    return date >= FIRST_DAY and (date - FIRST_DAY).days % 2 == 0

def story_index(date):
    return (date - FIRST_DAY).days // 2

def story_time(date):
    h = int(hashlib.sha256(f"antarnaad-story-{date}".encode()).hexdigest(), 16)
    m = EVENING[0] * 60 + EVENING[1] + (h % (SPREAD_MIN // 5 + 1)) * 5
    return dt.time(m // 60, m % 60)

def _fails(date):
    try:
        refs = json.load(due._api("GET", f"git/matching-refs/tags/story-fail-{date}-"))
    except urllib.error.HTTPError:
        return []
    out = []
    for r in refs:
        hhmm = r["ref"].rsplit("-", 1)[-1]
        if len(hhmm) == 4 and hhmm.isdigit():
            out.append(dt.time(int(hhmm[:2]), int(hhmm[2:])))
    return out

def due_now(now=None):
    now = now or dt.datetime.now(plan.IST)
    d = now.date()
    if not is_story_day(d):
        return False, "not a story day"
    start = dt.datetime.combine(d, story_time(d), tzinfo=now.tzinfo)
    if now < start:
        return False, f"story at {story_time(d):%H:%M}"
    if due._tag_exists(f"posted-story-{d}"):
        return False, "already posted"
    fails = _fails(d)
    if len(fails) >= MAX_TRIES:
        return False, f"{len(fails)} failed attempts today; giving up"
    for t in fails:
        if dt.timedelta(0) <= now - dt.datetime.combine(d, t, tzinfo=now.tzinfo) < dt.timedelta(minutes=RETRY_MIN):
            return False, "waiting after a failed attempt"
    return True, f"story due (time {story_time(d):%H:%M})"

def mark_failed(date, sha=""):
    due._make_tag(f"story-fail-{date}-{dt.datetime.now(plan.IST):%H%M}", sha)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        d = dt.datetime.now(plan.IST).date()
        for k in range(14):
            x = d + dt.timedelta(days=k)
            if is_story_day(x):
                print(x, x.strftime("%a"), story_time(x).strftime("%H:%M"), "hi" if story_index(x) % 2 == 0 else "en")
        sys.exit(0)
    ok, why = due_now()
    print("story video due:", ok, "-", why)
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(f"long={'yes' if ok else ''}\n")
