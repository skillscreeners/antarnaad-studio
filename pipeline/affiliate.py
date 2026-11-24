"""Amazon.in affiliate line for descriptions (only when the AMAZON_TAG variable is set)."""
import json, os, urllib.parse

_CFG = None

def _cfg():
    global _CFG
    if _CFG is None:
        _CFG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "affiliate.json"),
                              encoding="utf-8"))
    return _CFG

def line(author_en="", lang="en", theme="", kind=""):
    """'📚 <label>: <link>\n<disclosure>' for the first matching rule, or '' when no tag is configured."""
    tag = (os.environ.get("AMAZON_TAG") or _cfg().get("tag") or "").strip()
    if not tag:
        return ""
    for r in _cfg()["rules"]:
        if "author" in r and r["author"].lower() not in (author_en or "").lower():
            continue
        if "kind" in r and r["kind"].lower() not in (kind or "").lower():
            continue
        if "lang" in r and r["lang"] != lang:
            continue
        if "theme" in r and r["theme"] != theme:
            continue
        url = "https://www.amazon.in/s?" + urllib.parse.urlencode({"k": r["query"], "tag": tag})
        return f"📚 {r['label']}: {url}\n{_cfg()['disclosure']}"
    return ""
