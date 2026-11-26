#!/usr/bin/env python3
"""Story teaser Short: a vertical 30-55 s trailer for the latest story video.

Shorts get the views, stories get the subscribers: the teaser shows the story's gripping hook and its
opening narration with captions, then stops on "what happened next?" and points to the full story
(link at the top of the description). Posted in TEASER_SLOT (plan.py) once per story; when there is
no new story to tease, that slot posts a normal reel.
"""
import datetime as dt, json, os, re, subprocess, sys, time
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
from render import SR, font, FONT_BOLD, FONT_MED, GOLD, CREAM, HANDLE

VW, VH, FPS = 1080, 1920, 30
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MAX_S = 55
TEXT = {"hi": {"next": "आगे क्या हुआ? पूरी कहानी चैनल पर देखिए।", "card": "पूरी कहानी देखें", "badge": "कहानी",
               "title": "आगे क्या हुआ?", "link": "▶ पूरी कहानी देखें"},
        "en": {"next": "What happened next? Watch the full story on the channel.", "card": "Watch the full story",
               "badge": "STORY", "title": "what happened next?", "link": "▶ Watch the full story"}}

def _load(rel, default):
    try:
        return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
    except Exception:
        return default

def pick():
    """Newest posted story (last 3) without a teaser yet: (index entry, script) or (None, None)."""
    teased = {h["id"] for h in _load("data/history.json", []) if str(h.get("id", "")).startswith("teaser-")}
    for e in reversed(_load("data/stories.json", [])[-3:]):
        if not e.get("video") or f"teaser-{e['date']}" in teased:
            continue
        script = _load(f"data/stories/{e['date']}.json", None)
        if script:
            return e, script
    return None, None

def _sentences(text):
    return [p.strip() for p in re.split(r"(?<=[.!?।])\s+", text.strip()) if p.strip()]

def _tts(text, lang, path):
    voices = [render.VOICES[lang], render.VOICES[lang], {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"}[lang]]
    err = None
    for k, v in enumerate(voices):
        try:
            a, _ = render._tts(text, v, path, False)
            if len(a) > SR * 0.2:
                return a
        except Exception as e:
            err = e
        time.sleep(4 * (k + 1))
    raise RuntimeError(f"teaser narration failed: {err}")

def _wrap(text, f, maxw):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            out.append(cur); cur = w
    return out + ([cur] if cur else [])

def _text_png(text, lang, path, size=66, color=CREAM, box=None, maxw=940):
    f = font(FONT_BOLD, size)
    lines = _wrap(text, f, maxw)
    lh = int(size * 1.45)
    h = lh * len(lines) + 60
    im = Image.new("RGBA", (VW, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if box:
        wmax = max(f.getlength(l) for l in lines)
        d.rounded_rectangle(((VW - wmax) / 2 - 40, 0, (VW + wmax) / 2 + 40, h), 36, fill=box)
    y = 30
    for l in lines:
        bb = d.textbbox((0, 0), l, font=f, language=lang)
        d.text(((VW - (bb[2] - bb[0])) / 2 - bb[0], y), l, font=f, fill=color, language=lang,
               stroke_width=0 if box else 5, stroke_fill=(0, 0, 0))
        y += lh
    im.save(path)
    return h

def build(date, out_dir):
    """Render the teaser for the newest un-teased story. Returns (mp4, meta) or None."""
    e, s = pick()
    if not e:
        return None
    lang = s["lang"]; T = TEXT[lang]
    render.VOICE_RATE = os.environ.get("ANTARNAAD_STORY_RATE", "+5%"); render.VOICE_PITCH = "+0Hz"
    d = os.path.join(out_dir, "_work", f"teaser-{e['date']}"); os.makedirs(d, exist_ok=True)
    # narration: hook, then the opening sentences, then the cliffhanger line
    lines = ([s["hook"]] if s.get("hook") else []) + _sentences(s["scenes"][0]["text"])
    parts, t = [], 0.4
    for i, l in enumerate(lines):
        a = _tts(l, lang, f"{d}/n{i:02d}.mp3")
        if t + len(a) / SR + 5 > MAX_S and i > 0:
            break
        parts.append((l, a, t)); t += len(a) / SR + 0.2
    a = _tts(T["next"], lang, f"{d}/next.mp3"); parts.append((T["next"], a, t)); t += len(a) / SR
    end_card = t + 0.2
    dur = end_card + 2.6
    # picture: the story's first photo, vertical crop with a slow zoom
    photo = os.path.join(ROOT, "assets", "photos", (e.get("photos") or ["calm/" + sorted(os.listdir(os.path.join(ROOT, "assets", "photos", "calm")))[0]])[0])
    im = Image.open(photo).convert("RGB")
    BW, BH = int(VW * 1.3), int(VH * 1.3)
    sc = max(BW / im.width, BH / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    l0, t0 = (im.width - BW) // 2, (im.height - BH) // 2
    im = im.crop((l0, t0, l0 + BW, t0 + BH))
    im = ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(1.15)).enhance(0.72)
    im.save(f"{d}/bg.jpg", quality=92)
    # overlays: title banner (whole time), captions, end card, handle
    ov = []
    th = _text_png(s["title"], lang, f"{d}/title.png", size=60, color=(25, 15, 5), box=GOLD + (240,))
    ov.append((f"{d}/title.png", 270, 0, end_card))
    _text_png(T["badge"], lang, f"{d}/badge.png", size=44, color="white", box=(204, 0, 0, 235))
    ov.append((f"{d}/badge.png", 130, 0, end_card))
    for i, (l, a, st) in enumerate(parts):
        p = f"{d}/c{i:02d}.png"; _text_png(l, lang, p, size=64)
        ov.append((p, 820, st, st + len(a) / SR + 0.15))
    _text_png(T["card"], lang, f"{d}/card.png", size=84, color=(25, 15, 5), box=GOLD + (245,))
    ov.append((f"{d}/card.png", 760, end_card, dur))
    _text_png("YouTube: " + HANDLE, "en", f"{d}/handle.png", size=48)
    ov.append((f"{d}/handle.png", 960, end_card, dur))
    # audio
    vbuf = np.zeros(int((dur + 1) * SR))
    for l, a, st in parts:
        render.place(vbuf, a, st)
    render.music("uplifting", f"{d}/music.wav", dur=dur + 1)
    render.mix(vbuf, f"{d}/music.wav", f"{d}/audio.wav")
    frames = round(dur * FPS)
    fc = [f"[0:v]zoompan=z='1.0+0.15*on/{frames}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={VW}x{VH}:fps={FPS}[v0]"]
    args = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}", "-i", f"{d}/bg.jpg"]
    for i, (png, y, a0, a1) in enumerate(ov, 1):
        args += ["-i", png]
        fc.append(f"[v{i - 1}][{i}:v]overlay=0:{y}:enable='between(t,{a0:.2f},{a1:.2f})'[v{i}]")
    args += ["-i", f"{d}/audio.wav", "-filter_complex", ";".join(fc), "-map", f"[v{len(ov)}]", "-map", f"{len(ov) + 1}:a",
             "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart"]
    mp4 = os.path.join(out_dir, f"{date}_teaser_{e['date']}.mp4")
    subprocess.run(args + [mp4], check=True)
    link = f"https://youtu.be/{e['video']}"
    title = f"{s['title']} – {T['title']} #shorts"[:95]
    tags = ["#shorts", "#Antarnaad", "#HindiKahani", "#MotivationalStory"] if lang == "hi" else ["#shorts", "#Antarnaad", "#MotivationalStory", "#Story"]
    desc = (f"{T['link']}: {link}\n\n{s.get('summary', '')}\n\n" +
            ("सब्सक्राइब करें — रोज़ एक नई कहानी और एक अच्छा विचार।" if lang == "hi" else "Subscribe for a new story and one good thought every day.") +
            "\n\n" + " ".join(tags))
    meta = {"id": f"teaser-{e['date']}", "slot": None, "pillar": "Story teaser", "language": lang,
            "youtube": {"title": title, "description": desc, "tags": [t.lstrip("#") for t in tags] + ["motivational story", "short story"],
                        "categoryId": "24", "defaultLanguage": lang, "madeForKids": False, "privacyStatus": "public"},
            "instagram": {"caption": f"{s['title']}\n\n{T['title']} 👉 YouTube {HANDLE}\n\n" + " ".join(tags[1:])},
            "source": "Antarnaad story", "used": {}, "file": os.path.basename(mp4)}
    json.dump(meta, open(mp4[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"teaser for story {e['date']} ({lang}): {dur:.0f} s -> {mp4}", flush=True)
    return mp4, meta

if __name__ == "__main__":
    r = build(dt.date.today().isoformat(), os.path.join(ROOT, "out"))
    print(r[0] if r else "no story to tease")
