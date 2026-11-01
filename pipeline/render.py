#!/usr/bin/env python3
"""Antarnaad reel generator.

Reads a JSON list of quotes and renders, for each one:
  - an original procedural background matched to the quote's theme
  - original synthesized background music matched to its mood
  - animated, readable English/Hindi text (hook -> quote lines -> credit -> CTA)
  - a 1080x1920, 30 fps H.264/AAC MP4 ready for Shorts and Reels
  - metadata.json with titles, descriptions, captions, hashtags and post time

Usage:  python3 generate.py quotes_today.json out_dir [YYYY-MM-DD]
"""
import base64, io, json, math, os, subprocess, sys, datetime, zlib
import numpy as np
from scipy import ndimage, signal
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
BW, BH = 1296, 2304            # oversized background for slow zoom
FPS = 30
DUR = 16.0
_FONT_DIR = os.environ.get("ANTARNAAD_FONT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts"))
FONT_BOLD = os.path.join(_FONT_DIR, "Poppins-Bold.ttf")
FONT_MED = os.path.join(_FONT_DIR, "Poppins-Medium.ttf")
GOLD = (245, 165, 36)
CREAM = (250, 247, 240)
HANDLE = "@antarnaadin"

# ------------------------------------------------------------------ backgrounds
def rng_for(key):
    return np.random.default_rng(zlib.crc32(key.encode("utf-8")))

def gradient(stops, h=BH, w=BW):
    """stops: list of (pos 0..1, (r,g,b)) top to bottom."""
    ys = np.linspace(0, 1, h)
    out = np.zeros((h, 3))
    pos = [s[0] for s in stops]
    for c in range(3):
        out[:, c] = np.interp(ys, pos, [s[1][c] for s in stops])
    return np.repeat(out[:, None, :], w, axis=1)

def ridge(rng, base, amp, w=BW, octaves=6, rough=0.5):
    x = np.linspace(0, 1, w)
    y = np.zeros(w)
    a, f = amp, 2.0
    for _ in range(octaves):
        y += a * np.sin(2 * math.pi * f * x + rng.uniform(0, 6.28))
        y += a * 0.5 * np.sin(2 * math.pi * f * 1.7 * x + rng.uniform(0, 6.28))
        a *= rough; f *= 2.1
    return base + y

def fill_below(img, yline, color, alpha=1.0, soft=2.0):
    h, w, _ = img.shape
    yy = np.arange(h)[:, None]
    mask = np.clip((yy - yline[None, :]) / soft + 0.5, 0, 1) * alpha
    img[:] = img * (1 - mask[..., None]) + np.array(color) * mask[..., None]

def glow(img, cx, cy, radius, color, strength=1.0):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
    g = np.exp(-d ** 2) * strength
    img[:] = img + (np.array(color) - img) * np.clip(g, 0, 1)[..., None] * 0.9 + np.array(color) * g[..., None] * 0.15

def disc(img, cx, cy, r, color, feather=3):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = np.clip((r - d) / feather + 0.5, 0, 1)
    img[:] = img * (1 - m[..., None]) + np.array(color) * m[..., None]

def mist(img, rng, y0, y1, color, alpha):
    h, w, _ = img.shape
    noise = ndimage.gaussian_filter(rng.random((h // 8, w // 8)), (2, 12))
    noise = np.array(Image.fromarray((noise * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)) / 255.0
    yy = np.arange(h)[:, None]
    band = np.exp(-((yy - (y0 + y1) / 2) / ((y1 - y0) / 2)) ** 2)
    m = np.clip(band * (0.5 + noise) * alpha, 0, 1)
    img[:] = img * (1 - m[..., None]) + np.array(color) * m[..., None]

def rays(img, cx, cy, color, n=14, alpha=0.10, rng=None):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    ang = np.arctan2(yy - cy, xx - cx)
    phase = rng.uniform(0, 6.28) if rng is not None else 0
    r = (np.sin(ang * n + phase) * 0.5 + 0.5) ** 6
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    fade = np.exp(-dist / (h * 0.45))
    m = r * fade * alpha
    img[:] = img + (np.array(color) - img) * m[..., None]

def stars(img, rng, n, ymax, size=(0.6, 2.2)):
    h, w, _ = img.shape
    layer = np.zeros((h, w))
    xs = rng.integers(0, w, n); ys = (rng.random(n) ** 1.6 * ymax).astype(int)
    b = rng.random(n) ** 3
    layer[ys, xs] = b
    bigl = np.zeros((h, w)); sel = rng.random(n) > 0.97
    bigl[ys[sel], xs[sel]] = b[sel] + 0.5
    layer = ndimage.gaussian_filter(layer, size[0]) * 6 + ndimage.gaussian_filter(bigl, size[1]) * 40
    layer = np.clip(layer, 0, 1)
    img[:] = img + (255 - img) * layer[..., None]

def clouds(img, rng, y0, y1, color, alpha, scale=10):
    h, w, _ = img.shape
    n = sum(ndimage.gaussian_filter(rng.random((h // 4, w // 4)), s) * (s / 3) for s in (scale, scale / 2, scale / 4))
    n = (n - n.min()) / (n.max() - n.min())
    n = np.array(Image.fromarray((n * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)) / 255.0
    yy = np.arange(h)[:, None]
    band = np.clip(1 - np.abs(yy - (y0 + y1) / 2) / ((y1 - y0) / 2), 0, 1)
    m = np.clip((n - 0.45) * 2.2, 0, 1) * band * alpha
    img[:] = img * (1 - m[..., None]) + np.array(color) * m[..., None]

def tree(img, x, ground, height, color):
    pil = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(pil)
    tw = height * 0.07
    d.polygon([(x - tw, ground), (x + tw, ground), (x + tw * 0.5, ground - height * 0.55), (x - tw * 0.5, ground - height * 0.55)], fill=color)
    rng = np.random.default_rng(7)
    for _ in range(38):
        a = rng.uniform(0, math.pi); r = rng.uniform(0.1, 0.42) * height
        cx = x + math.cos(a) * r * 1.3; cy = ground - height * 0.62 - math.sin(a) * r * 0.75
        rr = rng.uniform(0.08, 0.16) * height
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color)
    for side in (-1, 1):
        d.line([(x, ground - height * 0.4), (x + side * height * 0.28, ground - height * 0.62)], fill=color, width=int(tw * 0.6))
    img[:] = np.array(pil).astype(np.float64)

def pines(img, rng, ybase, color, count, hmin, hmax):
    pil = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(pil)
    w = img.shape[1]
    for _ in range(count):
        x = rng.uniform(0, w); hh = rng.uniform(hmin, hmax)
        yb = float(np.interp(x, np.arange(w), ybase))
        d.polygon([(x, yb - hh), (x - hh * 0.22, yb + 4), (x + hh * 0.22, yb + 4)], fill=color)
    img[:] = np.array(pil).astype(np.float64)

def finish(img, rng, darken=0.30):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    # vignette + central readability band
    v = 1 - 0.55 * (((xx - w / 2) / (w * 0.75)) ** 2 + ((yy - h / 2) / (h * 0.7)) ** 2)
    band = 1 - 0.22 * np.exp(-((yy - h * 0.46) / (h * 0.22)) ** 2)
    img = img * np.clip(v, 0.35, 1)[..., None] * band[..., None] * (1 - darken)
    img = img + rng.normal(0, 3.0, img.shape)  # film grain
    return np.clip(img, 0, 255).astype(np.uint8)

def scene_sunrise_mountains(key):
    r = rng_for(key)
    img = gradient([(0, (28, 22, 70)), (0.32, (110, 48, 110)), (0.52, (235, 110, 70)), (0.62, (252, 190, 100)), (1, (60, 30, 50))])
    sy = BH * 0.585
    glow(img, BW * 0.5, sy, 520, (255, 205, 120), 0.9)
    rays(img, BW * 0.5, sy, (255, 225, 160), n=16, alpha=0.16, rng=r)
    disc(img, BW * 0.5, sy, 95, (255, 236, 190))
    cols = [(150, 70, 95), (110, 50, 80), (72, 34, 62), (40, 20, 42), (20, 10, 26)]
    for i, c in enumerate(cols):
        line = ridge(r, BH * (0.60 + i * 0.065), 70 - i * 6, rough=0.55)
        fill_below(img, line, c)
        if i < 3:
            mist(img, r, BH * (0.60 + i * 0.065) - 30, BH * (0.66 + i * 0.065), (250, 190, 150), 0.30)
    return finish(img, r)

def scene_misty_path(key):
    r = rng_for(key)
    img = gradient([(0, (40, 60, 90)), (0.45, (120, 150, 165)), (0.62, (190, 200, 195)), (1, (60, 75, 80))])
    glow(img, BW * 0.62, BH * 0.40, 450, (235, 230, 210), 0.6)
    layers = [(0.48, (110, 130, 140)), (0.56, (85, 105, 115)), (0.64, (60, 78, 88)), (0.73, (36, 48, 56))]
    for i, (y, c) in enumerate(layers):
        line = ridge(r, BH * y, 55, rough=0.5)
        fill_below(img, line, c)
        pines(img, r, line, c, 90 - i * 15, 40 + i * 25, 90 + i * 45)
        mist(img, r, BH * y - 40, BH * (y + 0.06), (215, 222, 222), 0.55)
    # winding path in the foreground
    pil = Image.fromarray(img.astype(np.uint8)); d = ImageDraw.Draw(pil)
    pts_l, pts_r = [], []
    for t in np.linspace(0, 1, 60):
        y = BH * (0.74 + 0.26 * t)
        cx = BW * (0.55 + 0.12 * math.sin(t * 3.2))
        half = 8 + 330 * t ** 1.6
        pts_l.append((cx - half, y)); pts_r.append((cx + half, y))
    d.polygon(pts_l + pts_r[::-1], fill=(112, 112, 104))
    img = np.array(pil).astype(np.float64)
    mist(img, r, BH * 0.70, BH * 0.84, (205, 212, 212), 0.45)
    return finish(img, r)

def scene_storm_light(key):
    r = rng_for(key)
    img = gradient([(0, (25, 30, 40)), (0.45, (60, 66, 80)), (0.70, (95, 90, 85)), (1, (30, 30, 30))])
    clouds(img, r, BH * 0.0, BH * 0.62, (35, 38, 48), 0.9, scale=14)
    clouds(img, r, BH * 0.1, BH * 0.55, (105, 110, 125), 0.75, scale=8)
    glow(img, BW * 0.58, BH * 0.30, 300, (255, 210, 140), 0.85)
    rays(img, BW * 0.58, BH * 0.30, (255, 215, 150), n=10, alpha=0.22, rng=r)
    hill = BH * 0.80 - 160 * np.exp(-((np.arange(BW) - BW * 0.5) / (BW * 0.33)) ** 2)
    fill_below(img, hill, (22, 22, 24))
    tree(img, BW * 0.5, float(hill[BW // 2]) + 6, 420, (16, 16, 18))
    glow(img, BW * 0.5, float(hill[BW // 2]) - 40, 260, (200, 160, 110), 0.18)
    return finish(img, r, darken=0.22)

def scene_dunes_sunset(key):
    r = rng_for(key)
    img = gradient([(0, (60, 30, 40)), (0.35, (180, 80, 50)), (0.55, (245, 160, 70)), (0.62, (255, 205, 120)), (1, (90, 45, 25))])
    sy = BH * 0.60
    glow(img, BW * 0.38, sy, 480, (255, 190, 100), 0.85)
    disc(img, BW * 0.38, sy, 120, (255, 225, 160))
    x = np.arange(BW)
    for i, (base, c) in enumerate([(0.62, (190, 100, 50)), (0.69, (150, 70, 35)), (0.77, (110, 50, 25)), (0.86, (70, 30, 15))]):
        line = BH * base + 60 * np.sin(x / BW * math.pi * (1.4 + i * 0.5) + r.uniform(0, 6)) + 20 * np.sin(x / 90 + i)
        fill_below(img, line, c, soft=4)
        # wind-ripple highlight just below each crest
        hl = line + 14
        fill_below(img, hl, tuple(min(255, v + 25) for v in c), alpha=0.25, soft=10)
        fill_below(img, hl + 30, c, alpha=0.8, soft=12)
    return finish(img, r)

def scene_starry_night(key):
    r = rng_for(key)
    img = gradient([(0, (6, 8, 22)), (0.5, (16, 24, 58)), (0.75, (35, 40, 85)), (1, (8, 8, 18))])
    # milky way band
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    band = np.exp(-(((yy - h * 0.15) - (xx - w * 0.3) * 0.9) / 260.0) ** 2)
    n = ndimage.gaussian_filter(r.random((h // 4, w // 4)), 3)
    n = np.array(Image.fromarray(((n - n.min()) / (n.max() - n.min()) * 255).astype(np.uint8)).resize((w, h))) / 255.0
    m = band * (0.4 + n) * 0.35
    img[:] = img + (np.array((150, 140, 200)) - img) * np.clip(m, 0, 1)[..., None]
    stars(img, r, 2600, BH * 0.78)
    disc(img, BW * 0.74, BH * 0.20, 70, (245, 240, 220), feather=2)
    disc(img, BW * 0.74 + 32, BH * 0.20 - 16, 64, tuple(int(v) for v in img[int(BH * 0.20) - 16, int(BW * 0.74) + 100]), feather=2)
    glow(img, BW * 0.74, BH * 0.20, 200, (200, 200, 230), 0.25)
    for i, (y, c) in enumerate([(0.74, (22, 26, 52)), (0.80, (14, 16, 34)), (0.88, (6, 6, 14))]):
        fill_below(img, ridge(r, BH * y, 50, rough=0.45), c)
    return finish(img, r, darken=0.15)

SCENES = {k[6:]: v for k, v in globals().items() if k.startswith("scene_")}

# ------------------------------------------------------------------ Gemini backgrounds (optional)
# With GEMINI_API_KEY set, each reel gets a freshly generated painting matched to its mood;
# without it (or if the call fails) the procedural scenes above are used.
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
SUBJECTS = {
    "uplifting": ["sunrise over the Sahyadri mountains with mist in the valleys", "first light over a calm Himalayan lake",
                  "golden dawn over terraced tea gardens", "a lone mountain trail climbing toward a bright sunrise",
                  "sun rising behind an ancient stone fort on a hilltop"],
    "calm":      ["a misty pine forest path at dawn", "still backwaters of Kerala at early morning",
                  "a quiet stone ghat by a river in soft fog", "snow-covered peaks under a pale blue sky",
                  "a lone boat on a glassy lake surrounded by hills"],
    "rising":    ["a lone tree on a hill as sunlight breaks through storm clouds", "a lighthouse standing against crashing waves at sunset",
                  "an eagle soaring over a deep canyon at golden hour", "a mountain summit above a sea of clouds",
                  "a rocket launch trail rising into a twilight sky over the sea"],
    "raga":      ["sand dunes of the Thar desert at sunset", "an old banyan tree beside a village pond at dusk",
                  "diyas glowing on temple steps by a river at evening", "a camel caravan silhouetted against an orange sky",
                  "lotus flowers on a still pond at sunset"],
    "gentle":    ["a starry night sky over quiet hills with a crescent moon", "fireflies in a dark forest clearing at night",
                  "rain drops on a window at night with warm city lights blurred", "the Milky Way above a calm lake",
                  "a lantern-lit path through a garden at night"],
}

def gemini_prompt(q):
    if q.get("bg_prompt"):
        subject = q["bg_prompt"]
    else:
        pool = SUBJECTS.get(q.get("mood", "calm"), SUBJECTS["calm"])
        subject = pool[zlib.crc32((q.get("date", "") + q["id"]).encode()) % len(pool)]
    return ("Vertical 9:16 cinematic digital painting, painterly illustrated style, rich but soft colours, "
            f"{subject}. No people, no faces, no text, no letters, no logos, no watermark. "
            "Keep the middle third of the image calm and slightly dark so white text placed over it stays readable.")

def gemini_background(q, out_png):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return False
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {"contents": [{"parts": [{"text": gemini_prompt(q)}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}}
    try:
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=120)
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
        im = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    except Exception as e:
        print(f"  Gemini background failed for {q['id']}, using built-in scene: {e}", flush=True)
        return False
    # cover-crop to the oversized background canvas, then grade for text readability
    sc = max(BW / im.width, BH / im.height)
    im = im.resize((math.ceil(im.width * sc), math.ceil(im.height * sc)), Image.LANCZOS)
    l, t = (im.width - BW) // 2, (im.height - BH) // 2
    arr = np.asarray(im.crop((l, t, l + BW, t + BH))).astype(np.float64)
    Image.fromarray(finish(arr, rng_for(q["id"]), darken=0.32)).save(out_png)
    return True

# ------------------------------------------------------------------ text overlays
def font(path, size):
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)

def text_layer(items):
    """items: list of (text, font, fill, y_center). Returns RGBA full-frame image with soft shadow."""
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(base), ImageDraw.Draw(shadow)
    for text, f, fill, yc in items:
        lang = "hi" if any("ऀ" <= ch <= "ॿ" for ch in text) else "en"
        bbox = d.textbbox((0, 0), text, font=f, language=lang)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (W - tw) / 2 - bbox[0]; y = yc - th / 2 - bbox[1]
        ds.text((x + 3, y + 5), text, font=f, fill=(0, 0, 0, 230), language=lang, stroke_width=6, stroke_fill=(0, 0, 0, 200))
        d.text((x, y), text, font=f, fill=fill + (255,), language=lang, stroke_width=2, stroke_fill=(20, 15, 40, 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    return Image.alpha_composite(shadow, base)

def fit_size(lines, path, start, maxw=860):
    s = start
    while s > 24:
        f = font(path, s)
        if all(f.getlength(l) <= maxw for l in lines):
            return s
        s -= 2
    return s

def build_overlays(q, d):
    hi = q["lang"] == "hi"
    paths = {}
    # hook
    hf = font(FONT_BOLD, fit_size([q["hook"]], FONT_BOLD, 64 if hi else 58))
    text_layer([(q["hook"], hf, GOLD, 560)]).save(f"{d}/hook.png"); paths["hook"] = f"{d}/hook.png"
    # quote lines
    qs = fit_size(q["lines"], FONT_BOLD, 84 if hi else 78)
    qf = font(FONT_BOLD, qs)
    gap = int(qs * (1.55 if hi else 1.35))
    n = len(q["lines"])
    top = 860 - gap * (n - 1) / 2
    for i, line in enumerate(q["lines"]):
        p = f"{d}/line{i}.png"
        text_layer([(line, qf, CREAM, top + i * gap)]).save(p); paths[f"line{i}"] = p
    after = top + (n - 1) * gap + gap * 0.9
    items = []
    if q.get("subtitle"):
        sf = font(FONT_MED, fit_size([q["subtitle"]], FONT_MED, 40, maxw=800))
        items.append((q["subtitle"], sf, (225, 225, 235), after))
        after += 80
    cf = font(FONT_MED, 44)
    items.append(("— " + q["author"], cf, GOLD, after + 20))
    text_layer(items).save(f"{d}/credit.png"); paths["credit"] = f"{d}/credit.png"
    # CTA
    cta = "रोज़ ऐसे विचारों के लिए फ़ॉलो करें" if hi else "Follow for daily inspiration"
    af = font(FONT_MED, 40)
    cy = max(1290, after + 150)
    text_layer([(cta, af, CREAM, cy), (HANDLE, font(FONT_BOLD, 46), GOLD, cy + 62)]).save(f"{d}/cta.png"); paths["cta"] = f"{d}/cta.png"
    # watermark (whole reel)
    wm = text_layer([(HANDLE, font(FONT_MED, 30), CREAM, 250)])
    a = np.array(wm); a[..., 3] = (a[..., 3] * 0.55).astype(np.uint8)
    Image.fromarray(a).save(f"{d}/wm.png"); paths["wm"] = f"{d}/wm.png"
    return paths, n

# ------------------------------------------------------------------ music
SR = 44100
def midi(n): return 440.0 * 2 ** ((n - 69) / 12)

def pad_note(freq, dur, amp=0.12, attack=1.4, release=1.6):
    t = np.arange(int(dur * SR)) / SR
    s = sum(a * np.sin(2 * np.pi * freq * m * t + np.sin(2 * np.pi * 0.2 * t) * 0.3) for m, a in ((1, 1), (2, 0.25), (3, 0.08)))
    s += 0.5 * np.sin(2 * np.pi * freq * 1.004 * t)
    env = np.minimum(1, t / attack) * np.minimum(1, (dur - t) / release).clip(0, 1)
    return s * env * amp

def bell(freq, dur=2.5, amp=0.10):
    t = np.arange(int(dur * SR)) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(2 * np.pi * freq * 2.01 * t) * np.exp(-t * 3) + 0.15 * np.sin(2 * np.pi * freq * 3.0 * t) * np.exp(-t * 5)
    return s * np.exp(-t * 1.6) * np.minimum(1, t / 0.005) * amp

def place(buf, sig, start):
    i = int(start * SR); j = min(len(buf), i + len(sig))
    if i < len(buf): buf[i:j] += sig[: j - i]

MOODS = {
    # (chords as midi lists, seconds per chord, melody notes, melody step, drone)
    "uplifting": ([[62, 66, 69], [59, 62, 66], [55, 59, 62], [57, 61, 64]], 4.0, [74, 76, 78, 81, 78, 76, 74, 73], 0.5, None),
    "calm":      ([[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]], 4.0, [69, 72, 76, 72, 74, 71, 67, 71], 1.0, None),
    "rising":    ([[52, 55, 59], [48, 52, 55], [55, 59, 62], [50, 54, 57]], 4.0, [64, 67, 71, 74, 76, 74, 71, 79], 0.5, None),
    "raga":      ([], 4.0, [62, 64, 66, 69, 71, 74, 71, 69, 66, 64, 62, 69], 0.75, 50),
    "gentle":    ([[60, 64, 67], [57, 60, 64], [53, 57, 60], [55, 59, 62]], 4.0, [72, 67, 76, 67, 74, 67, 72, 71], 1.0, None),
}

def music(mood, path, dur=DUR):
    chords, cl, mel, step, drone = MOODS[mood]
    buf = np.zeros(int((dur + 3) * SR))
    for k in range(int(dur // cl) + 1):
        for n in (chords[k % len(chords)] if chords else []):
            place(buf, pad_note(midi(n), cl + 1.5), k * cl)
            place(buf, pad_note(midi(n - 12), cl + 1.5, amp=0.06), k * cl)
    if drone:  # tanpura-like Sa-Pa-Sa drone
        for k in range(int(dur // 2) + 1):
            for j, n in enumerate((drone + 7, drone + 12, drone + 12, drone)):
                place(buf, bell(midi(n), 2.4, 0.06), k * 2 + j * 0.5)
        place(buf, pad_note(midi(drone), dur + 2, amp=0.08, attack=2), 0)
    rng = np.random.default_rng(len(mood))
    t, i = 1.0, 0
    while t < dur - 2:
        place(buf, bell(midi(mel[i % len(mel)]), amp=0.075 + rng.random() * 0.02), t)
        t += step; i += 1
    # simple reverb
    ir_t = np.arange(int(2.2 * SR)) / SR
    ir = np.random.default_rng(1).normal(0, 1, len(ir_t)) * np.exp(-ir_t * 2.6)
    ir[0] = 25
    wet = signal.fftconvolve(buf, ir)[: len(buf)]
    out = buf * 0.6 + wet / np.max(np.abs(wet)) * np.max(np.abs(buf)) * 0.55
    out = out[: int(dur * SR)]
    fade = np.ones(len(out)); fl = int(2.0 * SR); fade[-fl:] = np.linspace(1, 0, fl); fade[: int(0.4 * SR)] = np.linspace(0, 1, int(0.4 * SR))
    out = out * fade
    out = out / np.max(np.abs(out)) * 0.55
    stereo = np.stack([out, np.roll(out, 240)], axis=1)
    from scipy.io import wavfile
    wavfile.write(path, SR, (stereo * 32767).astype(np.int16))

# ------------------------------------------------------------------ voice-over
# Indian neural voices (Microsoft Edge TTS, free, needs internet). Override with env vars.
VOICES = {"hi": os.environ.get("ANTARNAAD_VOICE_HI", "hi-IN-MadhurNeural"),
          "en": os.environ.get("ANTARNAAD_VOICE_EN", "en-IN-PrabhatNeural")}
VOICE_RATE = os.environ.get("ANTARNAAD_VOICE_RATE", "-12%")   # calm, unhurried delivery
VOICE_PITCH = os.environ.get("ANTARNAAD_VOICE_PITCH", "-2Hz")
FAKE_VOICE = os.environ.get("ANTARNAAD_FAKE_VOICE") == "1"     # offline testing only

def _words(text):
    return [w for w in text.split() if any(ch.isalnum() for ch in w)]

def _load_wav(path):
    from scipy.io import wavfile
    sr, a = wavfile.read(path)
    a = a.astype(np.float64) / 32768.0
    return a.mean(axis=1) if a.ndim == 2 else a

def _tts(text, voice, mp3, want_words):
    """Returns (mono float array at SR, list of word start times in s)."""
    wav = mp3[:-4] + ".wav"
    if FAKE_VOICE:  # placeholder with speech-like length and pacing
        wc = max(1, len(_words(text))); per = 0.42
        t = np.arange(int((wc * per + 0.3) * SR)) / SR
        sig = 0.25 * np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * (1 / per) * t)) ** 2
        return sig, [0.1 + i * per for i in range(wc)]
    import asyncio, edge_tts
    starts = []
    async def go():
        kw = {"boundary": "WordBoundary"} if want_words else {}
        com = edge_tts.Communicate(text, voice, rate=VOICE_RATE, pitch=VOICE_PITCH, **kw)
        with open(mp3, "wb") as f:
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    starts.append(chunk["offset"] / 1e7)   # 100-ns ticks -> s
    asyncio.run(go())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ar", str(SR), "-ac", "1", wav], check=True)
    return _load_wav(wav), starts

def voice_track(q, d, n):
    """Synthesizes hook, quote and credit; returns (voice array, timeline dict)."""
    v = VOICES[q["lang"]]
    hook, _ = _tts(q["hook"], v, f"{d}/v_hook.mp3", False)
    quote_text = " ".join(q["lines"])
    quote, wstarts = _tts(quote_text, v, f"{d}/v_quote.mp3", True)
    credit_name = q["author"] if q["lang"] == "hi" else q["author_en"]
    credit, _ = _tts(credit_name, v, f"{d}/v_credit.mp3", False)
    t_hook = 0.4
    t_quote = t_hook + len(hook) / SR + 0.6
    # first word index of each on-screen line -> time that line appears
    counts = [len(_words(l)) for l in q["lines"]]
    idx = np.cumsum([0] + counts[:-1])
    if len(wstarts) >= sum(counts):
        line_t = [t_quote + wstarts[i] - 0.15 for i in idx]
    else:  # boundary count mismatch: spread lines by character share
        chars = np.cumsum([0] + [len(l) for l in q["lines"][:-1]]) / max(1, sum(len(l) for l in q["lines"]))
        line_t = [t_quote + c * len(quote) / SR - 0.1 for c in chars]
    t_credit = t_quote + len(quote) / SR + 0.5
    t_cta = t_credit + len(credit) / SR + 0.9
    dur = float(min(45.0, max(14.0, t_cta + 3.2)))
    buf = np.zeros(int(dur * SR))
    place(buf, hook, t_hook); place(buf, quote, t_quote); place(buf, credit, t_credit)
    return buf, {"hook": (max(0.2, t_hook - 0.2), t_quote - 0.5), "lines": [max(t_hook + 0.6, t) for t in line_t],
                 "credit": t_credit - 0.2, "cta": t_cta, "dur": dur}

def mix(voice, music_path, out_path):
    """Music ducks to ~22% under the voice; voice sits on top, gently compressed."""
    from scipy.io import wavfile
    sr, m = wavfile.read(music_path)
    m = m.astype(np.float64) / 32768.0
    m = m[: len(voice)]
    if len(m) < len(voice): m = np.pad(m, ((0, len(voice) - len(m)), (0, 0)))
    env = ndimage.maximum_filter1d(np.abs(voice), int(0.25 * SR))
    env = ndimage.uniform_filter1d((env > 0.02).astype(float), int(0.35 * SR))
    duck = 1.0 - 0.78 * env
    vpk = np.max(np.abs(voice)) or 1.0
    v = np.tanh(voice / vpk * 1.6) / np.tanh(1.6) * 0.80
    out = m * duck[:, None] * 0.9 + v[:, None]
    out = out / max(1.0, np.max(np.abs(out)) / 0.95)
    wavfile.write(out_path, SR, (out * 32767).astype(np.int16))

# ------------------------------------------------------------------ video
def render_video(q, d, out_mp4, use_voice=True):
    os.makedirs(d, exist_ok=True)
    paths, n = build_overlays(q, d)
    bg = f"{d}/bg.png"
    if not gemini_background(q, bg):
        Image.fromarray(SCENES[q["scene"]](q["id"] + q.get("date", "") + q["scene"])).save(bg)
    tl = None
    if use_voice:
        try:
            vbuf, tl = voice_track(q, d, n)
        except Exception as e:  # no internet / voice service down: keep the reel, skip narration
            print(f"  voice-over skipped for {q['id']}: {e}", flush=True)
    if tl is None:
        tl = {"hook": (0.2, 2.2), "lines": [1.8 + i * 1.3 for i in range(n)], "dur": DUR}
        tl["credit"] = tl["lines"][-1] + 1.6; tl["cta"] = tl["credit"] + 2.4
    dur = tl["dur"]
    wav = f"{d}/music.wav"; music(q["mood"], wav, dur)
    if use_voice and "vbuf" in locals():
        mixed = f"{d}/mix.wav"; mix(vbuf, wav, mixed); wav = mixed
    line_t, credit_t, cta_t = tl["lines"], tl["credit"], tl["cta"]
    DURs = str(dur)
    inputs = ["-loop", "1", "-t", DURs, "-i", bg]
    for k in ["hook"] + [f"line{i}" for i in range(n)] + ["credit", "cta", "wm"]:
        inputs += ["-loop", "1", "-t", DURs, "-i", paths[k]]
    inputs += ["-i", wav]
    fc = [f"[0:v]scale=w='{W}*1.12+{W}*0.06*t/{dur}':h=-2:eval=frame:flags=bicubic,crop={W}:{H},fps={FPS},format=yuv420p[b0]"]
    fades = [("hook", tl["hook"][0], tl["hook"][1])] + [(f"line{i}", round(line_t[i], 2), None) for i in range(n)] + [("credit", round(credit_t, 2), None), ("cta", round(cta_t, 2), None), ("wm", 0.0, None)]
    cur = "b0"
    for idx, (k, st, end) in enumerate(fades, start=1):
        f = f"[{idx}:v]format=rgba,fade=t=in:st={st}:d=0.6:alpha=1"
        if end: f += f",fade=t=out:st={end}:d=0.5:alpha=1"
        fc.append(f + f"[o{idx}]")
        fc.append(f"[{cur}][o{idx}]overlay=0:0:format=auto[b{idx}]")
        cur = f"b{idx}"
    fc.append(f"[{cur}]format=yuv420p[v]")
    aidx = len(fades) + 1
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
        "-filter_complex", ";".join(fc), "-map", "[v]", "-map", f"{aidx}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-t", DURs, "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True)

# ------------------------------------------------------------------ metadata
SLOTS = {"weekday": ["07:40", "10:50", "12:50", "18:40", "20:50"], "weekend": ["08:40", "11:10", "13:20", "17:40", "21:10"]}
BRAND = ["#Antarnaad", "#अंतर्नाद"]
BROAD = {"en": ["#Motivation", "#MotivationalQuotes", "#Inspiration"], "hi": ["#HindiMotivation", "#Suvichar", "#MotivationalQuotesHindi"]}

def metadata(q, date):
    day = datetime.date.fromisoformat(date)
    slot_time = SLOTS["weekend" if day.weekday() >= 5 else "weekday"][q["slot"] - 1]
    quote = " ".join(q["lines"])
    lang = q["lang"]
    yt_tags = [BRAND[0]] + BROAD[lang][:2] + q["topic_tags"][:1]
    ig_tags = BRAND + BROAD[lang] + q["topic_tags"]
    if lang == "hi":
        title = f"{q['author_en']} Suvichar | {q['lines'][0].rstrip(',')} #shorts"
        ask = "क्या आप सहमत हैं? कमेंट में बताइए 👇"
    else:
        title = f"{q['author_en']} Quote: {q['lines'][0].rstrip(',.')}… #shorts"
        ask = "What does this line mean to you? Comment below 👇"
    title = title[:95]
    other = q.get("subtitle") or ""
    yt_desc = (f"“{quote}” — {q['author_en']}, {q['source']}\n\n" + (other + "\n\n" if other else "") +
               f"{ask}\nSubscribe to Antarnaad for daily motivation in English & Hindi.\n\n" + " ".join(yt_tags))
    ig_caption = (("क्या आप सहमत हैं?\n\n" if lang == "hi" else "Do you agree with this?\n\n") +
                  f"“{quote}” — {q['author_en']}\n" + (f"\n{other}\n" if other else "") +
                  "\n💬 Comment one word this makes you feel.\n🔁 Share it with someone who needs this today.\n➕ Follow @antarnaadin for daily inspiration.\n\n" +
                  " ".join(ig_tags))
    return {
        "id": q["id"], "slot": q["slot"], "pillar": q["pillar"], "language": lang,
        "post_at_ist": f"{date}T{slot_time}:00+05:30",
        "youtube": {"title": title, "description": yt_desc, "tags": [t.lstrip("#") for t in yt_tags] + ["motivational quotes", "motivation shorts", "suvichar"],
                     "categoryId": "27", "defaultLanguage": lang, "madeForKids": False, "privacyStatus": "public"},
        "instagram": {"caption": ig_caption},
        "source": q["source"],
    }

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    qfile, out = args[0], args[1]
    date = args[2] if len(args) > 2 else datetime.date.today().isoformat()
    use_voice = "--no-voice" not in sys.argv
    quotes = json.load(open(qfile, encoding="utf-8"))
    os.makedirs(out, exist_ok=True)
    meta = []
    for q in quotes:
        work = os.path.join(out, "_work", q["id"]); os.makedirs(work, exist_ok=True)
        mp4 = os.path.join(out, f"{date}_slot{q['slot']}_{q['id']}.mp4")
        render_video(q, work, mp4, use_voice)
        m = metadata(q, date); m["file"] = os.path.basename(mp4); meta.append(m)
        print("rendered", mp4, flush=True)
    json.dump(meta, open(os.path.join(out, "metadata.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
