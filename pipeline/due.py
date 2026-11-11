#!/usr/bin/env python3
"""Light check (standard library only) run every 10 minutes by GitHub Actions.

Prints the slot that is due now and not yet posted, or nothing. GitHub's scheduler drops or
delays runs, so the workflow checks often and this script decides; a git tag
posted-YYYY-MM-DD-sN marks a slot as done so it is never posted twice.
"""
import datetime as dt, json, os, sys, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # standard library only

def tag_name(date, slot):
    return f"posted-{date}-s{slot}"

def _api(method, path, body=None):
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=30)

def _tag_exists(name):
    try:
        _api("GET", f"git/ref/tags/{name}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise

def is_posted(date, slot):
    return _tag_exists(tag_name(date, slot))

UPLOAD_LIMIT = int(os.environ.get("YT_UPLOAD_LIMIT_24H", "10"))

def uploads_last_24h(now):
    """YouTube caps this channel at about 10 uploads in any rolling 24 hours. Count ours from
    data/history.json (time of each post) and data/stats.json (publish times from the feed)."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    since = now.astimezone(dt.timezone.utc) - dt.timedelta(hours=24)
    seen = {}
    def load(name):
        try:
            return json.load(open(os.path.join(root, name), encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    for vid, s in load("stats.json").items():
        if not vid.startswith("_") and len(vid) == 11 and s.get("published"):
            seen[vid] = dt.datetime.fromisoformat(s["published"].replace("Z", "+00:00"))
    for h in load("history.json") or []:
        if h.get("at") and h.get("video"):
            seen.setdefault(h["video"], dt.datetime.fromisoformat(h["at"]))
    return sum(1 for t in seen.values() if t > since)

CAP_BACKOFF_MIN = 30

def is_capped(date, now=None):
    """YouTube refused an upload in the last CAP_BACKOFF_MIN minutes (rolling 24-hour upload limit).
    Tags are yt-cap-YYYY-MM-DD-HHMM (IST). Uploads age out of the 24-hour window, so retry after a pause."""
    now = now or dt.datetime.now(plan.IST)
    try:
        refs = json.load(_api("GET", f"git/matching-refs/tags/yt-cap-{date}-"))
    except urllib.error.HTTPError:
        return False
    for r in refs:
        hhmm = r["ref"].rsplit("-", 1)[-1]
        if len(hhmm) == 4 and hhmm.isdigit():
            t = now.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0, microsecond=0)
            if dt.timedelta(0) <= now - t < dt.timedelta(minutes=CAP_BACKOFF_MIN):
                return True
    return False

def mark_capped(date, sha):
    _make_tag(f"yt-cap-{date}-{dt.datetime.now(plan.IST):%H%M}", sha)

def mark_posted(date, slot, sha):
    _make_tag(tag_name(date, slot), sha)

def _make_tag(name, sha):
    try:
        _api("POST", "git/refs", {"ref": f"refs/tags/{name}", "sha": sha})
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422 = already exists
            raise

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--mark":   # --mark 2026-11-05:3,2026-11-05:2
        for item in sys.argv[2].split(","):
            d, s = item.strip().split(":")
            mark_posted(d, int(s), os.environ["GITHUB_SHA"]); print("marked", tag_name(d, s))
        sys.exit(0)
    now = dt.datetime.now(plan.IST)
    slot = plan.slot_now(now)
    today = now.date().isoformat()
    due = slot if slot and not is_posted(today, slot) else None
    if due:
        n = uploads_last_24h(now)
        if n >= UPLOAD_LIMIT:
            print(f"{n} uploads in the last 24 h (YouTube limit {UPLOAD_LIMIT}): slot {due} waits for the next check")
            due = None
    print(f"{now:%Y-%m-%d %H:%M} IST: slot due = {due or 'none'}" + (" (waiting: upload limit)" if slot and not due and is_capped(today, now) else ""))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"slot={due or ''}\n")
