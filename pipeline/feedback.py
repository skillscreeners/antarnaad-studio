"""Learns from what performs and steers the schedule towards it (standard library only).

data/history.json  every reel posted: date, slot, quote id, YouTube video id (written by run_slot)
data/stats.json    views and likes per video from the channel's public RSS feed (collect_stats.py)

Scoring: a post's score is views + 10 x likes, read about a day after posting. Authors get a smoothed
average of their posts' scores, so "similar content" (same author, same theme) is preferred.
Quotes that were never posted get an exploration bonus so new material is still tried, and every
quote waits COOLDOWN_DAYS before it can come back.
"""
import datetime as dt, json, os, random

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COOLDOWN_DAYS = 7
MIN_AGE_H = 18          # ignore posts younger than this: their views are still coming in
LIKE_WEIGHT = 10
PRIOR_N = 2             # smoothing: an author needs a few posts before its average dominates
EXPLORE_BONUS = 1.15    # never-posted quotes score 15% above the channel average
EXPLORE_EVERY = 5       # and roughly 1 slot in 5 always tries a never-posted quote

def _load(name, default):
    path = os.path.join(ROOT, "data", name)
    try:
        return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def history():
    return _load("history.json", [])

def stats():
    return _load("stats.json", {})

def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def post_scores():
    """{quote_id: [score, ...]} for posts old enough to judge."""
    st, out = stats(), {}
    vid_quote = {h["video"]: h["id"] for h in history() if h.get("video")}
    for vid, s in st.items():
        if vid.startswith("_"):
            continue
        qid = vid_quote.get(vid) or s.get("quote")
        if not qid or not s.get("published") or not s.get("seen"):
            continue
        age_h = (_ts(s["seen"]) - _ts(s["published"])).total_seconds() / 3600
        if age_h < MIN_AGE_H:
            continue
        out.setdefault(qid, []).append(s.get("views", 0) + LIKE_WEIGHT * s.get("likes", 0))
    return out

def expected_scores(quotes):
    """Expected score for each quote (by id), from its own and its author's past posts."""
    ps = post_scores()
    all_scores = [x for v in ps.values() for x in v]
    if not all_scores:
        return {}
    mean = sum(all_scores) / len(all_scores)
    by_id = {q["id"]: q for q in quotes}
    author = {}
    for qid, sc in ps.items():
        a = by_id.get(qid, {}).get("author_en")
        if a:
            author.setdefault(a, []).extend(sc)
    def author_avg(a):
        sc = author.get(a, [])
        return (sum(sc) + PRIOR_N * mean) / (len(sc) + PRIOR_N)
    exp = {}
    for q in quotes:
        a = author_avg(q.get("author_en"))
        own = ps.get(q["id"])
        if own:
            exp[q["id"]] = 0.5 * a + 0.5 * sum(own) / len(own)
        else:
            exp[q["id"]] = max(a, mean) * EXPLORE_BONUS
    return exp

MAX_PER_AUTHOR_DAY = 2

def pick(pool, date, slot, used_today=(), authors_today=()):
    """Choose a quote from pool for this slot, or None to fall back to the fixed rotation."""
    exp = expected_scores(pool)
    if not exp:
        return None
    last_used = {}
    for h in history():
        last_used[h["id"]] = max(last_used.get(h["id"], ""), h["date"])
    cutoff = (date - dt.timedelta(days=COOLDOWN_DAYS)).isoformat()
    crowded = {a for a in authors_today if list(authors_today).count(a) >= MAX_PER_AUTHOR_DAY}
    fresh = [q for q in pool if last_used.get(q["id"], "") < cutoff and q["id"] not in used_today
             and q.get("author_en") not in crowded]
    if not fresh:  # whole pool used recently: take the least recently used
        fresh = sorted([q for q in pool if q["id"] not in used_today] or pool, key=lambda q: last_used.get(q["id"], ""))[:3]
    rng = random.Random(f"antarnaad-fb-{date}-{slot}")
    never = [q for q in fresh if q["id"] not in last_used]
    if never and rng.randrange(EXPLORE_EVERY) == 0:
        return rng.choice(never)
    return max(fresh, key=lambda q: exp.get(q["id"], 0) * rng.uniform(0.85, 1.15))

def report(quotes, top=10):
    """Text summary: best authors and quotes so far."""
    ps = post_scores()
    by_id = {q["id"]: q for q in quotes}
    rows = sorted(((sum(v) / len(v), k) for k, v in ps.items()), reverse=True)
    authors = {}
    for s, k in rows:
        authors.setdefault(by_id.get(k, {}).get("author_en", "?"), []).append(s)
    lines = ["Top quotes (views + 10 x likes):"] + [f"  {s:7.0f}  {k}" for s, k in rows[:top]]
    lines += ["Top authors:"] + [f"  {sum(v)/len(v):7.0f}  {a} ({len(v)} posts)" for a, v in
                                  sorted(authors.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))[:top]]
    return "\n".join(lines)
