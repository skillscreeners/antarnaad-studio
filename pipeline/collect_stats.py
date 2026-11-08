#!/usr/bin/env python3
"""Reads views and likes of the channel's latest videos from YouTube's public RSS feed (no key) and
stores them in data/stats.json through the GitHub API. Runs from the 10-minute check job, but only
does work every 3 hours. The feed lists the latest 15 videos, so each reel is read until it is ~1.5
days old, which is when its score is taken."""
import base64, datetime as dt, json, os, sys, urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import due

CHANNEL = os.environ.get("YT_CHANNEL_ID", "UCJzTFJ7NyywHX__UzX8bHxA")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "m": "http://search.yahoo.com/mrss/"}
EVERY_H = 3

def get_file(path):
    try:
        r = json.load(due._api("GET", f"contents/{path}"))
        return json.loads(base64.b64decode(r["content"]).decode("utf-8")), r["sha"]
    except Exception as e:
        if "404" in str(e):
            return None, None
        raise

def put_file(path, obj, sha, msg):
    body = {"message": msg, "content": base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()}
    if sha:
        body["sha"] = sha
    due._api("PUT", f"contents/{path}", body)

def match_quote(title, quotes):
    t = title.lower()
    for q in quotes:
        head = q["lines"][0].strip(" ,.;।").lower()
        if len(head) >= 6 and head in t and q["author_en"].split()[-1].lower() in t:
            return q["id"]
    return None

def main(force=False):
    now = dt.datetime.now(dt.timezone.utc)
    stats, sha = get_file("data/stats.json")
    stats = stats or {}
    last = stats.get("_updated")
    if last and not force and (now - dt.datetime.fromisoformat(last)).total_seconds() < EVERY_H * 3600:
        print("stats: fresh enough"); return
    req = urllib.request.Request(f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}",
                                 headers={"User-Agent": "AntarnaadStudio/1.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    import plan
    quotes = plan.all_quotes()
    n = 0
    for e in root.findall("a:entry", NS):
        vid = e.find("yt:videoId", NS).text
        title = e.find("a:title", NS).text or ""
        comm = e.find("m:group/m:community", NS)
        views = int(comm.find("m:statistics", NS).get("views", 0)) if comm is not None else 0
        likes = int(comm.find("m:starRating", NS).get("count", 0)) if comm is not None else 0
        s = stats.setdefault(vid, {})
        s.update(title=title, published=e.find("a:published", NS).text, views=views, likes=likes,
                 seen=now.isoformat(timespec="seconds"))
        if "quote" not in s:
            s["quote"] = match_quote(title, quotes)
        n += 1
    stats["_updated"] = now.isoformat(timespec="seconds")
    put_file("data/stats.json", stats, sha, f"stats: {n} videos")
    print(f"stats: updated {n} videos")

if __name__ == "__main__":
    main(force="--force" in sys.argv)
