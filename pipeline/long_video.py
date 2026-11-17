#!/usr/bin/env python3
"""Weekly long video (16:9, 5-8 min): "10 Kabir dohe with meaning" and similar series.

Each week takes the next series from SERIES. Every quote comes from the verified quote bank; the
everyday meaning is written by Gemini (checked, with the bank's own explanation as fallback).
Layout: blurred landscape backdrop, title strip, quote, then its meaning; voice reads both over soft
music. The description gets chapters (one per quote) so viewers can jump around.

    python pipeline/long_video.py --date 2026-11-22 [--series kabir-1] [--dry-run]
"""
import argparse, datetime as dt, json, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan, render
from render import SR, font, FONT_BOLD, FONT_MED, GOLD, CREAM, HANDLE

W, H = 1920, 1080
FIRST_SUNDAY = dt.date(2026, 11, 22)

# (id, language, title, authors, opening line, outro)
SERIES = [
    ("kabir-1", "hi", "कबीर के 10 दोहे अर्थ सहित", ["Sant Kabir"], "Kabir Ke Dohe with Meaning in Hindi"),
    ("stoic-1", "en", "10 Stoic Lessons for a Calm Mind", ["Marcus Aurelius", "Epictetus", "Seneca"], "Marcus Aurelius, Epictetus, Seneca"),
    ("rahim-1", "hi", "रहीम के 10 दोहे अर्थ सहित", ["Abdul Rahim Khan-i-Khanan"], "Rahim Ke Dohe with Meaning in Hindi"),
    ("kabir-2", "hi", "कबीर के और दोहे अर्थ सहित", ["Sant Kabir"], "More Kabir Ke Dohe with Meaning"),
    ("tulsi-1", "hi", "तुलसीदास के दोहे अर्थ सहित", ["Goswami Tulsidas"], "Tulsidas Ke Dohe with Meaning in Hindi"),
    ("stoic-2", "en", "More Stoic Lessons for Daily Life", ["Marcus Aurelius", "Epictetus", "Seneca"], "Marcus Aurelius, Epictetus, Seneca"),
    ("tagore-1", "en", "Rabindranath Tagore: Lines That Light the Way", ["Rabindranath Tagore"], "Tagore Quotes with Meaning"),
    ("franklin-1", "en", "Benjamin Franklin's Lessons on Work and Wealth", ["Benjamin Franklin"], "Benjamin Franklin Quotes Explained"),
]
TEXT = {
    "hi": {"intro": "नमस्कार, अंतर्नाद में आपका स्वागत है। आज सुनिए {title}।",
           "meaning": "अर्थ", "outro": "अगर ये बातें दिल को छू गईं, तो वीडियो को लाइक करें, शेयर करें, और अंतर्नाद को सब्सक्राइब करें।",
           "outro_card": ["पसंद आया? लाइक • शेयर • सब्सक्राइब", "हर दिन एक अच्छी बात — " + HANDLE]},
    "en": {"intro": "Welcome to Antarnaad. Today: {title}.",
           "meaning": "Meaning", "outro": "If these lines helped you, like, share, and subscribe to Antarnaad for one good thought every day.",
           "outro_card": ["Found it useful? Like • Share • Subscribe", "One good thought every day — " + HANDLE]},
}

def week_index(date):
    return max(0, (date - FIRST_SUNDAY).days // 7)

def series_for(date, name=None):
    """Series of the week; after the named series run out, a weekly 'Antarnaad suvichar' collection."""
    if name:
        return next(s for s in SERIES if s[0] == name)
    k = week_index(date)
    if k < len(SERIES):
        return SERIES[k]
    lang = "hi" if k % 2 == 0 else "en"
    return (f"antarnaad-{k}", lang, "अंतर्नाद के 10 सुविचार" if lang == "hi" else "10 Good Thoughts for Your Week",
            ["Antarnaad"], "Hindi Suvichar Collection" if lang == "hi" else "Motivational Thoughts Collection")

def items_for(series, date):
    sid, lang, _, authors, _ = series
    bank = [q for q in plan._bank() if q["author_en"] in authors and (q["lang"] == lang or authors != ["Antarnaad"])]
    bank.sort(key=lambda q: q["id"])
    if sid.endswith("-2"):
        bank = bank[10:] or bank
    elif sid.startswith("antarnaad-"):
        k = week_index(date) - len(SERIES)
        bank = [q for q in bank if q["lang"] == lang]
        start = (k // 2) * 10 % max(1, len(bank))
        bank = (bank[start:] + bank[:start])
    return bank[:10]

def meanings(items, lang):
    """Short everyday meaning for each quote: Gemini, checked; falls back to the bank's own explanation."""
    out = {q["id"]: (q.get("subtitle") if lang == "hi" and re.search(r"[ऀ-ॿ]", q.get("subtitle", "")) else "") for q in items}
    if not os.environ.get("GEMINI_API_KEY"):
        return out
    import refill
    ask = ("Explain each quote below in " + ("simple everyday Hindi (Devanagari)" if lang == "hi" else "simple everyday English")
           + " for a family audience: 2 short sentences, at most 220 characters, practical and positive, how to apply it in daily "
             "life. Do not add facts about the author. Return only JSON: [{\"id\": \"...\", \"meaning\": \"...\"}]\n"
           + "\n".join(f"{q['id']}: {' '.join(q['lines'])} — {q['author_en']}" for q in items))
    try:
        for m in refill.ask_gemini(ask):
            t = str(m.get("meaning", "")).strip()
            ok = 30 <= len(t) <= 260 and (lang == "hi") == bool(re.search(r"[ऀ-ॿ]", t)) \
                and not any(b in t.lower() for b in ("kill", "suicide", "sex", "politic", "मौत", "हत्या"))
            if ok and m.get("id") in out:
                out[m["id"]] = t
    except Exception as e:
        print(f"::warning::meanings from Gemini failed, using bank text: {e}")
        return out
    try:   # save so the reviewed text is reused and can be edited on github.com
        import collect_stats
        saved, sha = collect_stats.get_file("data/long_meanings.json")
        saved = saved or {}
        saved.update({q["id"]: out[q["id"]] for q in items if out.get(q["id"])})
        collect_stats.put_file("data/long_meanings.json", saved, sha, "long video meanings")
    except Exception as e:
        print(f"::warning::meanings not saved: {e}")
    return out

def wrap(text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    return lines + ([cur] if cur else [])

def backdrop(q, d):
    """Blurred, darkened landscape version of the reel background for this quote."""
    p = f"{d}/bg_src.png"
    if not render.portrait_background(q, p) and not render.library_background(q, p):
        render.SCENES.get(q.get("scene", "misty_path"), render.scene_misty_path)(q["id"]).save(p)
    im = Image.open(p).convert("RGB")
    sc = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(10))
    arr = np.asarray(im).astype(np.float32) * 0.55
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))

def draw_centered(d, text, f, y, fill, lang):
    bb = d.textbbox((0, 0), text, font=f, language=lang)
    x = (W - (bb[2] - bb[0])) / 2 - bb[0]
    d.text((x + 3, y + 4), text, font=f, fill=(0, 0, 0), language=lang)
    d.text((x, y), text, font=f, fill=fill, language=lang)
    return bb[3] - bb[1]

def card(bg, header, lines, meaning, lang, meaning_label, credit):
    im = bg.copy(); d = ImageDraw.Draw(im)
    if header:
        draw_centered(d, header, font(FONT_MED, 40), 60, GOLD, lang)
    size = render.fit_size(lines, FONT_BOLD, 78, maxw=1560)
    fq = font(FONT_BOLD, size)
    block = len(lines) * int(size * 1.35)
    y = (300 if meaning else (H - block) // 2 - 40)
    for l in lines:
        draw_centered(d, l, fq, y, CREAM, lang); y += int(size * 1.35)
    if credit:
        draw_centered(d, "— " + credit, font(FONT_MED, 40), y + 12, GOLD, lang); y += 80
    if meaning:
        fm = font(FONT_MED, 40)
        y += 30
        draw_centered(d, meaning_label, font(FONT_BOLD, 36), y, GOLD, lang); y += 62
        for l in wrap(meaning, fm, 1500)[:4]:
            draw_centered(d, l, fm, y, CREAM, lang); y += 58
    draw_centered(d, HANDLE, font(FONT_MED, 30), H - 70, (220, 210, 190), "en")
    return im

def build(date, series_name=None, out_dir="out"):
    series = series_for(date, series_name)
    sid, lang, title, authors, en_title = series
    items = items_for(series, date)
    if len(items) < 5:
        raise SystemExit(f"series {sid}: only {len(items)} quotes")
    title = title.replace("10", str(len(items)))
    d = os.path.join(out_dir, f"long-{date}"); os.makedirs(d, exist_ok=True)
    mean = meanings(items, lang)
    for q in items:
        print(f"  {q['id']}: {' / '.join(q['lines'])}\n     -> {mean.get(q['id'])}")
    voice = render.VOICES[lang]
    T = TEXT[lang]
    segs = []   # (image, seconds, audio array)

    def say(text, name):
        a, _ = render._tts(text, voice, f"{d}/{name}.mp3", False)
        return a

    bg0 = backdrop(items[0], d)
    a = say(T["intro"].format(title=title), "intro")
    segs.append((card(bg0, "ANTARNAAD • अंतर्नाद", [title], "", lang, "", ""), len(a) / SR + 1.6, a))
    chapters = [("0:00", "Intro" if lang == "en" else "परिचय")]
    for i, q in enumerate(items, 1):
        bg = backdrop(q, d)
        credit = q["author"] if lang == "hi" else q["author_en"]
        header = f"{title}  •  {i}/{len(items)}"
        start = sum(s[1] for s in segs)
        qa = say(" ".join(q["lines"]), f"q{i}")
        segs.append((card(bg, header, q["lines"], "", lang, "", credit), len(qa) / SR + 1.2, qa))
        if mean.get(q["id"]):
            ma = say(f"{T['meaning']}: {mean[q['id']]}", f"m{i}")
            segs.append((card(bg, header, q["lines"], mean[q["id"]], lang, T["meaning"], credit), len(ma) / SR + 1.8, ma))
        chapters.append((f"{int(start // 60)}:{int(start % 60):02d}", f"{i}. {q['lines'][0].rstrip(',;।')}"))
    oa = say(T["outro"], "outro")
    segs.append((card(bg0, "", T["outro_card"], "", lang, "", ""), len(oa) / SR + 2.5, oa))

    total = sum(s[1] for s in segs)
    voice_buf = np.zeros(int((total + 1) * SR)); t = 0.0
    for k, (img, sec, au) in enumerate(segs):
        img.save(f"{d}/s{k:02d}.png")
        render.place(voice_buf, au, t + 0.5)
        t += sec
    render.music("calm" if lang == "en" else "raga", f"{d}/music.wav", dur=total + 1)
    render.mix(voice_buf, f"{d}/music.wav", f"{d}/audio.wav")
    with open(f"{d}/list.txt", "w") as f:
        for k, (_, sec, _) in enumerate(segs):
            f.write(f"file 's{k:02d}.png'\nduration {sec:.3f}\n")
        f.write(f"file 's{len(segs) - 1:02d}.png'\n")
    out = os.path.join(out_dir, f"{date}_long_{sid}.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{d}/list.txt",
                    "-i", f"{d}/audio.wav", "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "22", "-tune", "stillimage", "-c:a", "aac", "-b:a", "160k", "-shortest", out], check=True)

    names = ", ".join(dict.fromkeys(q["author_en"] for q in items))
    yt_title = (f"{title} | {en_title} | Antarnaad" if lang == "hi" else f"{title} | {en_title} | Antarnaad")[:100]
    intro = (f"{title}। हर दोहा/विचार सरल अर्थ के साथ — रोज़मर्रा की ज़िंदगी में अपनाने के लिए।" if lang == "hi"
             else f"{title}: each quote read aloud with a simple explanation you can use in daily life.")
    desc = "\n".join([intro, "", "Chapters:"] + [f"{c} {n}" for c, n in chapters] + ["",
            f"Quotes: {names}. Sources are listed in our quote bank; meanings are simple explanations by Antarnaad.",
            "Subscribe for one good thought every day: https://www.youtube.com/@antarnaadin", "",
            "#Antarnaad #अंतर्नाद " + ("#Suvichar #HindiMotivation #Dohe" if lang == "hi" else "#Motivation #Stoicism #Wisdom")])
    meta = {"id": f"long-{sid}", "youtube": {"title": yt_title, "description": desc[:4900],
            "tags": ["Antarnaad", en_title, title, "motivation", "suvichar", "quotes with meaning"] + authors,
            "categoryId": "27", "defaultLanguage": lang}}
    json.dump(meta, open(out[:-4] + ".json", "w"), ensure_ascii=False, indent=1)
    print(f"long video {sid}: {len(items)} quotes, {total / 60:.1f} min -> {out}")
    return out, meta

LONG_TIME = (11, 0)    # Sundays, IST

def due_now():
    """True on Sunday from 11:00 to 13:30 IST if this week's long video is not posted yet."""
    import due
    now = dt.datetime.now(plan.IST)
    start = now.replace(hour=LONG_TIME[0], minute=LONG_TIME[1], second=0, microsecond=0)
    return now.weekday() == 6 and dt.timedelta(0) <= now - start <= dt.timedelta(minutes=150) \
        and not due._tag_exists(f"posted-long-{now.date()}")

if __name__ == "__main__":
    if sys.argv[1:] == ["--due"]:
        out = os.environ.get("GITHUB_OUTPUT")
        ok = due_now()
        print("long video due:", ok)
        if out:
            open(out, "a").write(f"long={'yes' if ok else ''}\n")
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(plan.IST).date().isoformat())
    ap.add_argument("--series"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    date = dt.date.fromisoformat(a.date)
    import due
    tag = f"long-{date}"
    if not a.dry_run and not a.force and due._tag_exists(f"posted-{tag}"):
        print("already posted"); sys.exit(0)
    out, meta = build(date, a.series)
    if a.dry_run:
        sys.exit(0)
    import publish
    vid = publish.youtube_upload(out, meta)
    print(f"youtube: https://youtu.be/{vid}")
    due._make_tag(f"posted-{tag}", os.environ.get("GITHUB_SHA", ""))
