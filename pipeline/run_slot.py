#!/usr/bin/env python3
"""Render and post one Antarnaad reel.

  python pipeline/run_slot.py                   # the slot due now (IST), used by the scheduler
  python pipeline/run_slot.py --slot 2          # a specific slot for today
  python pipeline/run_slot.py --slot 2 --date 2026-11-03 --dry-run   # render only, no posting
  python pipeline/run_slot.py --preview 2026-11-03                   # render all 5 slots of a day, no posting

Platforms without credentials are skipped with a note, so the same command works before
Instagram is connected.
"""
import argparse, datetime as dt, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan, render

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")

def build(date, slot):
    q = plan.quote_for(date, slot)
    work = os.path.join(OUT, "_work", f"{date}_s{slot}"); os.makedirs(work, exist_ok=True)
    mp4 = os.path.join(OUT, f"{date}_slot{slot}_{q['id']}.mp4")
    render.render_video(q, work, mp4, use_voice=os.environ.get("ANTARNAAD_NO_VOICE") != "1")
    meta = render.metadata(q, date)
    meta["file"] = os.path.basename(mp4)
    json.dump(meta, open(mp4[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"rendered slot {slot}: {q['id']} ({q['lang']}) -> {meta['file']}", flush=True)
    return mp4, meta

def post(mp4, meta):
    results, failed = {}, False
    if all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        try:
            from publish import youtube_upload
            vid = youtube_upload(mp4, meta); results["youtube"] = f"https://youtube.com/shorts/{vid}"
        except Exception as e:
            results["youtube"] = f"FAILED: {e}"; failed = True
    else:
        results["youtube"] = "skipped (no YouTube secrets)"
    if all(os.environ.get(k) for k in ("IG_USER_ID", "IG_ACCESS_TOKEN")):
        try:
            from publish import instagram_publish
            results["instagram"] = "media " + instagram_publish(mp4, meta["instagram"]["caption"])
        except Exception as e:
            results["instagram"] = f"FAILED: {e}"; failed = True
    else:
        results["instagram"] = "skipped (no Instagram secrets)"
    for k, v in results.items():
        print(f"{k}: {v}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {meta['file']}\n\n**{meta['youtube']['title']}**\n\n" +
                    "".join(f"- {k}: {v}\n" for k, v in results.items()) + "\n")
    return not failed, results

def record_history(date, slot, quote_id, video):
    """Append this post to data/history.json in the repo (used by the feedback loop)."""
    import collect_stats
    for attempt in range(3):
        hist, sha = collect_stats.get_file("data/history.json")
        hist = hist or []
        hist.append({"date": date, "slot": slot, "id": quote_id, "video": video,
                     "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        try:
            collect_stats.put_file("data/history.json", hist, sha, f"history: {date} slot {slot}"); return
        except Exception:
            if attempt == 2:
                raise

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int)
    ap.add_argument("--date")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview")
    ap.add_argument("--force", action="store_true", help="post even if this slot is already marked posted")
    a = ap.parse_args()
    now = dt.datetime.now(plan.IST)
    if a.preview:
        for s in plan.SLOTS:
            build(a.preview, s)
        return
    date = a.date or now.date().isoformat()
    slot = a.slot or plan.slot_now(now)
    if not slot:
        print(f"No slot due at {now:%H:%M} IST; nothing to do."); return
    track = bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")) and not a.dry_run
    if track:
        import due
        if due.is_posted(date, slot) and not a.force:
            print(f"Slot {slot} on {date} is already posted; nothing to do."); return
    mp4, meta = build(date, slot)
    if a.dry_run:
        print("dry run: not posted"); return
    ok, results = post(mp4, meta)
    if track and str(results.get("youtube", "")).startswith("https://"):
        due.mark_posted(date, slot, os.environ.get("GITHUB_SHA", ""))
        try:
            record_history(date, slot, meta["id"], results["youtube"].rsplit("/", 1)[-1])
        except Exception as e:
            print(f"::warning::history not recorded: {e}")
    if "uploadLimitExceeded" in str(results.get("youtube", "")):
        # YouTube's rolling 24-hour upload cap. The slot stays unposted, so the next 10-minute check
        # retries it once the oldest upload is 24 h old (due.py also waits for that before posting).
        print(f"::warning::YouTube upload limit reached; slot {slot} will be retried at the next check.")
        ok = not any(str(v).startswith("FAILED") for k, v in results.items() if k != "youtube")
    if not ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
