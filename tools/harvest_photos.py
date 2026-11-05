#!/usr/bin/env python3
"""Builds a local library of real CC0 / public-domain photographs (Openverse) for reel backgrounds.

Run by the "Harvest background photos" workflow. Saves assets/photos/<pool>/<id>.jpg, cropped to
the 1296x2304 portrait canvas, plus assets/photos/credits.json. No attribution is legally required
for CC0/PDM, but sources are kept anyway. Existing photos are kept; run again to add more.
"""
import io, json, os, sys, time
import requests
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
from render import PHOTO_QUERIES, BW, BH

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "photos")
UA = {"User-Agent": "AntarnaadStudio/1.0 (+https://skillscreeners.github.io/antarnaad-studio/)"}
PER_QUERY = int(os.environ.get("PER_QUERY", "3"))
BAD = ("illustration", "cartoon", "vector", "drawing", "clipart", "clip art", "icon", "logo", "text",
       "poster", "painting", "sketch", "render", "3d", "map", "diagram", "screenshot", "nude", "blood", "war")

def search(query):
    for attempt in range(5):
        try:
            r = requests.get("https://api.openverse.org/v1/images/", headers=UA, timeout=60,
                             params={"q": query, "license": "cc0,pdm", "category": "photograph",
                                     "page_size": 20, "mature": "false"})
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(r.status_code)
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as e:
            print(f"  {query}: attempt {attempt + 1} failed ({e})", flush=True)
            time.sleep(8 * (attempt + 1))
    return []

def main():
    os.makedirs(ROOT, exist_ok=True)
    cpath = os.path.join(ROOT, "credits.json")
    credits = json.load(open(cpath)) if os.path.exists(cpath) else {}
    for pool, queries in PHOTO_QUERIES.items():
        os.makedirs(os.path.join(ROOT, pool), exist_ok=True)
        for query in queries:
            hits = [h for h in search(query)
                    if min(h.get("width") or 0, h.get("height") or 0) >= 1000 and h.get("url")
                    and h.get("source") != "rawpixel"
                    and not any(b in (h.get("title") or "").lower() for b in BAD)]
            hits.sort(key=lambda h: (h["height"] < h["width"], -(h["width"] * h["height"])))
            got = 0
            for h in hits:
                if got >= PER_QUERY:
                    break
                path = os.path.join(ROOT, pool, f"{h['id'][:12]}.jpg")
                if os.path.exists(path):
                    got += 1; continue
                try:
                    r = requests.get(h["url"], headers=UA, timeout=60); r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                except Exception as e:
                    print(f"  skip {h['url']}: {e}", flush=True); continue
                sc = max(BW / im.width, BH / im.height)
                im = im.resize((round(im.width * sc + 0.5), round(im.height * sc + 0.5)), Image.LANCZOS)
                l, t = (im.width - BW) // 2, (im.height - BH) // 2
                im.crop((l, t, l + BW, t + BH)).save(path, quality=80, optimize=True, progressive=True)
                credits[f"{pool}/{os.path.basename(path)}"] = {k: h.get(k) for k in
                    ("title", "creator", "license", "source", "foreign_landing_url", "url")} | {"query": query}
                got += 1
                print(f"  {pool}/{os.path.basename(path)}  '{query}'  {h.get('foreign_landing_url')}", flush=True)
            time.sleep(2)
    json.dump(credits, open(cpath, "w"), indent=1, ensure_ascii=False)
    print({p: len([f for f in os.listdir(os.path.join(ROOT, p)) if f.endswith(".jpg")]) for p in PHOTO_QUERIES})

if __name__ == "__main__":
    main()
