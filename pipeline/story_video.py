#!/usr/bin/env python3
"""Motivational story videos (16:9, about 6-9 minutes), every other day in the evening.

Gemini writes an original, family-friendly story (alternating Hindi and English, rotating kinds:
fables retold, ordinary people overcoming difficulty, guru-and-student parables). The script is
checked, saved to data/stories/DATE.json (reused on retry, editable on github.com) and then:
  narration  - Edge neural voice, one sentence at a time
  pictures   - reviewed, people-free photos from assets/photos, one per scene, slow pan and zoom
  captions   - every sentence on screen (many people watch muted)
  music      - soft background music under the voice
  thumbnail  - photo, big 2-4 word title, gold "story" badge

    python pipeline/story_video.py [--date 2026-11-24] [--dry-run] [--force]
"""
import argparse, datetime as dt, json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan, render, story_due
from render import SR, font, FONT_BOLD, FONT_MED, GOLD, CREAM, HANDLE

W, H, FPS = 1920, 1080, 30
BACKUP_VOICE = {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PHOTO_DIR = os.path.join(ROOT, "assets", "photos")
MOODS = ["calm", "gentle", "uplifting", "rising", "raga", "work"]

KINDS = [
    "an original story about an ordinary Indian person (a farmer, potter, tailor, student, shopkeeper, teacher, "
    "auto driver or grandmother) who overcomes a real difficulty through patience, honesty or hard work",
    "a Panchatantra or Hitopadesha style animal fable, retold freshly in your own words",
    "a parable about a wise guru and a restless student, with a surprising lesson at the end",
    "an original story about a young person who fails (an exam, a first job, a small business or a sport) "
    "and learns to keep going",
    "a Jataka style tale, retold freshly in your own words",
    "an original story about gratitude, family or helping others in an Indian village or small town",
    "a classic fable in the style of Aesop, retold in an Indian setting in your own words",
    "an original story about someone who changes one small daily habit and slowly changes their whole life",
]
BAD = ["suicide", "kill", "murder", "blood", "rape", "sex", "kiss", "drunk", "alcohol", "cigarette", "drug", "gun",
       "bomb", "politic", "election", "minister", "modi", "hindu-muslim", "caste", "cancer", "disease",
       "आत्महत्या", "हत्या", "ख़ून", "खून", "शराब", "बंदूक", "चुनाव", "मंत्री", "जाति"]
TEXT = {
    "hi": {"intro": "नमस्कार, अंतर्नाद में आपका स्वागत है। आज की कहानी है: {title}",
           "lesson": "इस कहानी की सीख", "outro": "अगर कहानी अच्छी लगी हो, तो वीडियो को लाइक करें, शेयर करें, "
                                                "और ऐसी ही कहानियों के लिए अंतर्नाद को सब्सक्राइब करें।",
           "badge": "प्रेरक कहानी", "kind": "Hindi Motivational Story", "cta": "लाइक • शेयर • सब्सक्राइब"},
    "en": {"intro": "Welcome to Antarnaad. Today's story is: {title}",
           "lesson": "The lesson", "outro": "If this story touched you, like it, share it with someone who needs it, "
                                            "and subscribe to Antarnaad for more stories.",
           "badge": "STORY", "kind": "Motivational Story", "cta": "Like • Share • Subscribe"},
}

# ------------------------------------------------------------------ script
def _repo_file(path):
    try:
        import collect_stats
        return collect_stats.get_file(path)
    except Exception as e:
        print(f"::warning::could not read {path}: {e}")
        return None, None

def _save(path, obj, msg):
    try:
        import collect_stats
        _, sha = collect_stats.get_file(path)
        collect_stats.put_file(path, obj, sha, msg)
    except Exception as e:
        print(f"::warning::could not save {path}: {e}")

def words(t):
    return len(t.split())

def validate(s, lang):
    try:
        title, scenes = str(s["title"]).strip(), s["scenes"]
        texts = [str(x["text"]).strip() for x in scenes]
        moral, thumb = str(s["moral"]).strip(), str(s["thumb"]).strip()
    except Exception as e:
        return f"bad shape: {e}"
    total = sum(words(t) for t in texts)
    if not (8 <= len(texts) <= 16):
        return f"{len(texts)} scenes"
    if not (650 <= total <= 1700):
        return f"{total} words"
    if any(not (20 <= words(t) <= 170) for t in texts):
        return "scene length"
    if not (3 <= len(title) <= 70) or not (1 <= len(thumb) <= 30) or not moral:
        return "title/thumb/moral"
    deva = lambda t: bool(re.search(r"[ऀ-ॿ]", t))
    if lang == "hi" and not all(deva(t) for t in texts + [title, moral]):
        return "not Hindi"
    if lang == "en" and any(deva(t) for t in texts + [title, moral]):
        return "not English"
    blob = " ".join(texts + [title, moral]).lower()
    bad = [b for b in BAD if re.search(r"(?<![a-z])" + re.escape(b), blob)]
    return f"blocked words {bad}" if bad else None

def write_story(date):
    k = story_due.story_index(date)
    lang = "hi" if k % 2 == 0 else "en"
    kind = KINDS[(k // 2) % len(KINDS)] if lang == "hi" else KINDS[(k // 2 + 3) % len(KINDS)]
    index, _ = _repo_file("data/stories.json")
    earlier = [e["title"] for e in (index or [])][-60:]
    import refill
    ask = ("Write a motivational story for Antarnaad, a YouTube channel for families in India (all ages).\n"
           "Language: " + ("simple, warm spoken Hindi in Devanagari script (Hindustani words people use every day)"
                           if lang == "hi" else "simple, warm Indian English") + ".\n"
           f"Kind of story: {kind}.\n"
           "Write it to be read aloud by one narrator: 900-1200 words in 10-14 scenes, each scene 60-100 words, "
           "short clear sentences, no dialogue labels, no stage directions, no headings. A clear beginning, a real "
           "struggle, a turning point and a hopeful ending. All characters are fictional with ordinary Indian names. "
           "Do not mention real people, celebrities, politicians, brands, real news, religion-based conflict, "
           "violence, anyone dying, romance, alcohol, medical or money-making claims.\n"
           + ("Do not repeat these earlier stories: " + "; ".join(earlier) + "\n" if earlier else "") +
           'Return only JSON: {"title": "catchy title, at most 60 characters, in the story language", '
           '"title_en": "English title", "thumb": "2-4 word thumbnail text in the story language", '
           '"moral": "the lesson in one sentence, story language", "summary": "2 sentences for the video description, '
           'story language", "tags": ["8 short English tags"], '
           '"scenes": [{"text": "narration", "mood": "one of calm, gentle, uplifting, rising, raga, work"}]}')
    err = None
    for attempt in range(3):
        try:
            s = refill.ask_gemini(ask)
        except Exception as e:
            err = str(e); continue
        err = validate(s, lang)
        if not err:
            s.update(date=str(date), lang=lang, kind=kind)
            for sc in s["scenes"]:
                sc["mood"] = sc.get("mood") if sc.get("mood") in MOODS else "calm"
            return s
        print(f"story attempt {attempt + 1} rejected: {err}")
    raise RuntimeError(f"no usable story: {err}")

def story_for(date, fresh=False):
    """Saved script for the date (from an earlier attempt or edited by hand), else a new one."""
    path = f"data/stories/{date}.json"
    if not fresh:
        s, _ = _repo_file(path)
        if s and not validate(s, s.get("lang", "en")):
            print(f"using saved script {path}")
            return s
    s = write_story(date)
    _save(path, s, f"story script {date}")
    return s

# ------------------------------------------------------------------ pictures
def _rejected():
    p = os.path.join(PHOTO_DIR, "rejected.txt")
    return {l.strip() for l in open(p) if l.strip() and not l.startswith("#")} if os.path.exists(p) else set()

def pick_photos(scenes, recent_story_photos):
    """One distinct photo per scene, matching the scene's mood. Photos the Shorts have already used are
    preferred (oldest first) so never-used photos stay fresh for Shorts; photos in the last few stories
    are avoided."""
    rej = _rejected()
    pools = {p: [f"{p}/{f}" for f in sorted(os.listdir(os.path.join(PHOTO_DIR, p))) if f.endswith(".jpg") and f[:-4] not in rej]
             for p in sorted(os.listdir(PHOTO_DIR)) if os.path.isdir(os.path.join(PHOTO_DIR, p))}
    order = {}
    for i, h in enumerate(render._history()):
        if h.get("photo"):
            order[h["photo"]] = i
    def rank(x):   # used-by-shorts first (oldest use first), then unused; recent stories last
        return (x in recent_story_photos, x not in order, order.get(x, 0))
    taken, out = set(), []
    for sc in scenes:
        mood = sc.get("mood", "calm")
        cands = [x for x in pools.get(mood, []) if x not in taken] or \
                [x for p, xs in pools.items() if p != "work" for x in xs if x not in taken] or \
                [x for xs in pools.values() for x in xs]
        pick = sorted(cands, key=rank)[0]
        taken.add(pick); out.append(pick)
    return out

def prepare_photo(rel, path):
    im = Image.open(os.path.join(PHOTO_DIR, rel)).convert("RGB")
    BW, BH = int(W * 1.5), int(H * 1.5)
    sc = max(BW / im.width, BH / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    l, t = (im.width - BW) // 2, (im.height - BH) // 2
    im = im.crop((l, t, l + BW, t + BH))
    im = ImageEnhance.Brightness(im).enhance(0.78)
    im.save(path, quality=93)

# ------------------------------------------------------------------ captions and cards
def wrap(text, f, maxw, lang):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            out.append(cur); cur = w
    return out + ([cur] if cur else [])

def caption_png(text, lang, path):
    """Bottom caption (up to 2 lines) on a soft dark band; returns the PNG (W x 300)."""
    f = font(FONT_MED if lang == "en" else FONT_BOLD, 52)
    lines = wrap(text, f, 1640, lang)
    im = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
    band = Image.new("RGBA", (W, 300), (0, 0, 0, 0)); bd = ImageDraw.Draw(band)
    for y in range(300):
        bd.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * min(1, y / 120))))
    im.alpha_composite(band)
    d = ImageDraw.Draw(im)
    y = 300 - 40 - len(lines) * 72
    for l in lines:
        bb = d.textbbox((0, 0), l, font=f, language=lang)
        x = (W - (bb[2] - bb[0])) / 2 - bb[0]
        d.text((x, y), l, font=f, fill=CREAM, language=lang, stroke_width=3, stroke_fill=(0, 0, 0))
        y += 72
    im.save(path)

def chunks(sentence, lang):
    """Split a long sentence into caption pieces of at most two lines each."""
    f = font(FONT_MED if lang == "en" else FONT_BOLD, 52)
    lines = wrap(sentence, f, 1640, lang)
    return [" ".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]

def title_card(title, sub, lang, path):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, H), fill=(0, 0, 0, 90))
    size = 96
    while size > 48 and font(FONT_BOLD, size).getlength(title) > 1700:
        size -= 4
    rows = wrap(title, font(FONT_BOLD, size), 1700, lang)
    y = H / 2 - len(rows) * size * 0.7 - 40
    fs = font(FONT_MED, 40)
    bb = d.textbbox((0, 0), sub, font=fs, language=lang)
    d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y - 90), sub, font=fs, fill=GOLD, language=lang)
    for r in rows:
        f = font(FONT_BOLD, size); bb = d.textbbox((0, 0), r, font=f, language=lang)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), r, font=f, fill=CREAM, language=lang, stroke_width=5, stroke_fill=(0, 0, 0))
        y += size * 1.4
    im.save(path)

def thumbnail(photo_jpg, text, badge, lang, path):
    im = Image.open(photo_jpg).convert("RGB").resize((1280, 720))
    im = ImageEnhance.Brightness(im).enhance(0.8); d = ImageDraw.Draw(im)
    size = 150
    rows = wrap(text, font(FONT_BOLD, size), 1180, lang)
    while size > 60 and (len(rows) > 2 or any(font(FONT_BOLD, size).getlength(r) > 1180 for r in rows)):
        size -= 6; rows = wrap(text, font(FONT_BOLD, size), 1180, lang)
    f = font(FONT_BOLD, size)
    y = 360 - len(rows) * size * 0.65
    for r in rows:
        bb = d.textbbox((0, 0), r, font=f, language=lang)
        d.text(((1280 - (bb[2] - bb[0])) / 2 - bb[0], y), r, font=f, fill=(255, 236, 170), language=lang,
               stroke_width=8, stroke_fill=(15, 8, 30))
        y += size * 1.25
    fb = font(FONT_BOLD, 50); bw = fb.getlength(badge)
    d.rounded_rectangle((40, 40, 40 + bw + 60, 125), 22, fill=GOLD)
    d.text((70, 47), badge, font=fb, fill=(25, 15, 5), language=lang)
    d.text((40, 660), "ANTARNAAD • अंतर्नाद", font=font(FONT_MED, 32), fill=GOLD, language="hi")
    im.save(path, quality=92)

# ------------------------------------------------------------------ video
def sentences(text, lang):
    parts = re.split(r"(?<=[.!?।])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]

def scene_clip(photo, dur, overlays, out, k):
    """photo (1.5x frame) with a slow zoom/pan, overlays = [(png, x, y, t0, t1)]."""
    frames = max(1, round(dur * FPS))
    zin = k % 2 == 0
    z = f"1.0+0.12*on/{frames}" if zin else f"1.12-0.12*on/{frames}"
    fx, fy = [(0.5, 0.5), (0.2, 0.4), (0.8, 0.6), (0.4, 0.2), (0.6, 0.8)][k % 5]
    fc = [f"[0:v]zoompan=z='{z}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':d=1:s={W}x{H}:fps={FPS},format=yuv420p[v0]"]
    args = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{frames / FPS:.3f}", "-i", photo]
    for i, (png, x, y, t0, t1) in enumerate(overlays, 1):
        args += ["-i", png]
        fc.append(f"[v{i - 1}][{i}:v]overlay={x}:{y}:enable='between(t,{t0:.2f},{t1:.2f})'[v{i}]")
    args += ["-filter_complex", ";".join(fc), "-map", f"[v{len(overlays)}]", "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", str(FPS), out]
    subprocess.run(args, check=True)
    return frames / FPS

def build(date, story, out_dir="out"):
    lang = story["lang"]; T = TEXT[lang]
    d = os.path.join(out_dir, f"story-{date}"); os.makedirs(d, exist_ok=True)
    voice = render.VOICES[lang]
    index, _ = _repo_file("data/stories.json")
    recent = {p for e in (index or [])[-4:] for p in e.get("photos", [])}
    photos = pick_photos(story["scenes"], recent)
    print("photos:", ", ".join(photos))

    n_tts = [0]
    def say(text):
        """Edge TTS now and then answers 'No audio was received': retry, then try the other voice."""
        import time
        n_tts[0] += 1
        err = None
        for v in (voice, voice, BACKUP_VOICE[lang]):
            try:
                a, _ = render._tts(text, v, f"{d}/t{n_tts[0]:03d}.mp3", False)
                if len(a) > SR * 0.2:
                    return a
                err = "empty audio"
            except Exception as e:
                err = e
            print(f"  voice retry ({v}): {err}", flush=True); time.sleep(4)
        raise RuntimeError(f"narration failed for: {text[:60]}... ({err})")

    # plan: list of scenes, each (photo index, [(text shown, audio)], extra overlay)
    clips, audio_parts, t_video = [], [], 0.0
    def add_scene(photo_i, pieces, card=None, lead=0.6, tail=0.9):
        nonlocal t_video
        src = f"{d}/p{photo_i:02d}.jpg"
        if not os.path.exists(src):
            prepare_photo(photos[photo_i], src)
        overlays, t = [], lead
        if card:
            overlays.append((card, 0, 0, 0, 999))
        for j, (shown, audio) in enumerate(pieces):
            dur = len(audio) / SR
            audio_parts.append((t_video + t, audio))
            caps = chunks(shown, lang) if shown else []
            for c_i, c in enumerate(caps):
                share = dur / len(caps)
                png = f"{d}/c{len(clips):02d}_{j:02d}_{c_i}.png"
                caption_png(c, lang, png)
                overlays.append((png, 0, H - 300, t + c_i * share, t + (c_i + 1) * share + (0.25 if c_i == len(caps) - 1 else 0)))
            t += dur + 0.35
        length = t + tail
        out = f"{d}/clip{len(clips):02d}.mp4"
        length = scene_clip(src, length, overlays, out, len(clips))
        clips.append(out); t_video += length

    title = story["title"]
    tc = f"{d}/title.png"; title_card(title, "ANTARNAAD • अंतर्नाद", lang, tc)
    add_scene(0, [("", say(T["intro"].format(title=title)))], card=tc, lead=0.8, tail=1.2)
    chapters = []
    for i, sc in enumerate(story["scenes"]):
        if i in (0, len(story["scenes"]) // 2, len(story["scenes"]) - 2):
            chapters.append(t_video)
        pieces = [(s, say(s)) for s in sentences(sc["text"], lang)]
        add_scene(i, pieces)
        print(f"  scene {i + 1}/{len(story['scenes'])} done ({t_video / 60:.1f} min)", flush=True)
    chapters.append(t_video)
    lc = f"{d}/lesson.png"; title_card(story["moral"], T["lesson"], lang, lc)
    add_scene(len(photos) - 1, [("", say(f"{T['lesson']}: {story['moral']}"))], card=lc, lead=0.8, tail=1.5)
    oc = f"{d}/outro.png"; title_card(T["cta"], HANDLE, lang, oc)
    add_scene(0, [("", say(T["outro"]))], card=oc, lead=0.5, tail=2.5)

    total = t_video
    vbuf = np.zeros(int((total + 1) * SR))
    for start, a in audio_parts:
        render.place(vbuf, a, start)
    render.music("raga" if lang == "hi" else "calm", f"{d}/music.wav", dur=total + 1)
    render.mix(vbuf, f"{d}/music.wav", f"{d}/audio.wav")
    with open(f"{d}/clips.txt", "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    out = os.path.join(out_dir, f"{date}_story.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{d}/clips.txt",
                    "-i", f"{d}/audio.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", "-movflags", "+faststart", out], check=True)
    thumbnail(f"{d}/p00.jpg", story["thumb"], T["badge"], lang, out[:-4] + "_thumb.jpg")

    names = ["शुरुआत", "मुश्किल घड़ी", "मोड़", "सीख"] if lang == "hi" else ["The beginning", "The struggle", "The turning point", "The lesson"]
    chap = ["0:00 " + ("परिचय" if lang == "hi" else "Intro")] + \
           [f"{int(c // 60)}:{int(c % 60):02d} {n}" for c, n in zip(chapters, names)]
    yt_title = f"{title} | {T['kind']} | Antarnaad"[:100]
    desc = "\n".join([story.get("summary", ""), "", ("सीख: " if lang == "hi" else "Lesson: ") + story["moral"], "",
                      "Chapters:"] + chap + ["",
                      "An original story by Antarnaad. All characters are fictional. Narration uses a synthetic voice.",
                      "Subscribe for stories and one good thought every day: https://www.youtube.com/@antarnaadin", "",
                      "#Antarnaad #अंतर्नाद " + ("#HindiKahani #MotivationalStory #PrernaKahani" if lang == "hi"
                                                  else "#MotivationalStory #MoralStory #Inspiration")])
    tags = [str(t)[:30] for t in story.get("tags", [])][:10] + \
           ["Antarnaad", "motivational story", "moral story"] + (["hindi kahani", "prerak kahani", "hindi story"] if lang == "hi" else ["inspirational story"])
    meta = {"id": f"story-{date}", "youtube": {"title": yt_title, "description": desc[:4900], "tags": tags,
            "categoryId": "24", "defaultLanguage": lang}}
    json.dump(meta, open(out[:-4] + ".json", "w"), ensure_ascii=False, indent=1)
    print(f"story video {date}: {len(story['scenes'])} scenes, {total / 60:.1f} min -> {out}")
    return out, meta, photos

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(plan.IST).date().isoformat())
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--new-script", action="store_true", help="write a fresh script even if one is saved")
    ap.add_argument("--script", help="local script JSON (testing)")
    a = ap.parse_args()
    date = dt.date.fromisoformat(a.date)
    import due
    if not a.dry_run and not a.force and due._tag_exists(f"posted-story-{date}"):
        print("already posted"); sys.exit(0)
    try:
        story = json.load(open(a.script)) if a.script else story_for(date, a.new_script)
        print(f"STORY ({story['lang']}): {story['title']}  [{story.get('title_en', '')}]")
        for i, sc in enumerate(story["scenes"], 1):
            print(f"  {i}. ({sc['mood']}) {sc['text']}")
        print(f"  LESSON: {story['moral']}")
        out, meta, photos = build(date, story)
        if a.dry_run:
            sys.exit(0)
        import publish
        vid = publish.youtube_upload(out, meta)
    except SystemExit:
        raise
    except Exception as e:
        # no failed job (and no email); story_due waits 40 minutes and tries again, at most 3 times a day
        print(f"::warning::story video failed, will retry later: {e}")
        if not a.dry_run and not a.script:
            story_due.mark_failed(date, os.environ.get("GITHUB_SHA", ""))
        sys.exit(0)
    print(f"youtube: https://youtu.be/{vid}")
    try:
        publish.youtube_thumbnail(vid, out[:-4] + "_thumb.jpg"); print("thumbnail set")
    except Exception as e:
        print(f"::warning::thumbnail not set: {e}")
    due._make_tag(f"posted-story-{date}", os.environ.get("GITHUB_SHA", ""))
    index, sha = _repo_file("data/stories.json")
    index = (index or []) + [{"date": str(date), "lang": story["lang"], "title": story["title"],
                              "title_en": story.get("title_en", ""), "video": vid, "photos": photos}]
    _save("data/stories.json", index, f"story posted {date}")
