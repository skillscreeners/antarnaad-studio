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

def is_posted(date, slot):
    try:
        _api("GET", f"git/ref/tags/{tag_name(date, slot)}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise

def mark_posted(date, slot, sha):
    try:
        _api("POST", "git/refs", {"ref": f"refs/tags/{tag_name(date, slot)}", "sha": sha})
    except urllib.error.HTTPError as e:
        if e.code != 422:  # 422 = already exists
            raise

if __name__ == "__main__":
    now = dt.datetime.now(plan.IST)
    slot = plan.slot_now(now)
    due = slot if slot and not is_posted(now.date().isoformat(), slot) else None
    print(f"{now:%Y-%m-%d %H:%M} IST: slot due = {due or 'none'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"slot={due or ''}\n")
