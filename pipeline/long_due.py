#!/usr/bin/env python3
"""Standard-library check: is this week's long video due? (Sundays 11:00-13:30 IST, not yet posted)"""
import datetime as dt, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import due, plan

LONG_TIME = (11, 0)

def due_now():
    now = dt.datetime.now(plan.IST)
    start = now.replace(hour=LONG_TIME[0], minute=LONG_TIME[1], second=0, microsecond=0)
    return now.weekday() == 6 and dt.timedelta(0) <= now - start <= dt.timedelta(minutes=150) \
        and not due._tag_exists(f"posted-long-{now.date()}")

if __name__ == "__main__":
    ok = due_now()
    print("long video due:", ok)
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(f"long={'yes' if ok else ''}\n")
