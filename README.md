# Antarnaad Studio

Posts 10 narrated motivational reels a day (weekday 08:40 and 10:10 slots are work-motivation reels) to YouTube Shorts ([@antarnaadin](https://www.youtube.com/@antarnaadin))
and Instagram Reels (@antarnaadin) using GitHub Actions. Nothing runs on your computer.

Each run renders one reel just before its slot: a verified quote from `data/quote_bank.json`, an Indian
AI voice-over (Microsoft Edge neural voices), original music, and a background that is either a fresh
Gemini painting (if `GEMINI_API_KEY` is set) or one of the built-in scenes. Then it uploads.

| Slot | Mon–Fri (IST) | Sat–Sun (IST) | Language |
|---|---|---|---|
| 1 Subah ka Vichar | 07:40 | 08:40 | Hindi |
| 2 Global Greats | 10:50 | 11:10 | English |
| 3 In the News | 12:50 | 13:20 | alternates (or `data/trending.json`) |
| 4 Indian Icons | 18:40 | 17:40 | Hindi |
| 5 Life Lessons | 20:50 | 21:10 | English |

```
pipeline/plan.py        which quote goes in which slot (no state; ~11 days before a quote repeats)
pipeline/render.py      video, voice-over, music, Gemini/built-in backgrounds, titles and captions
pipeline/publish.py     YouTube + Instagram upload
pipeline/run_slot.py    render + post the slot that is due
data/quote_bank.json    59 quotes with sources — add more in the same format
data/trending.json      optional "In the News" quote by date
docs/                   GitHub Pages site: homepage + privacy policy (for Google and Meta app review)
tools/get_youtube_token.py   one-time, on your computer
```

## Setup

### 1. Repository and website
1. Push this repo to GitHub (public, so Pages is free).
2. Settings → Pages → Source: *Deploy from a branch* → `main` / `/docs`.
   Site: `https://<user>.github.io/antarnaad-studio/` — privacy policy at `.../privacy.html`.

### 2. YouTube API
Use a **separate Google Cloud project** from Embedded QA Architect: each upload costs about 1,600 of
the default 10,000 daily quota units, so 5 Antarnaad reels a day would crowd out the other channel.

1. console.cloud.google.com → new project `antarnaad-studio` → enable **YouTube Data API v3**.
2. OAuth consent screen → External → app name "Antarnaad Studio Uploader", homepage and privacy
   policy = the Pages URLs above, scope `youtube.upload`, add embeddedtestsolutions@gmail.com as test user.
   Publish the app ("In production") so the refresh token does not expire after 7 days.
3. Credentials → OAuth client ID → Desktop app → download `client_secret.json`.
4. On your computer: `pip install google-auth-oauthlib` then
   `python tools/get_youtube_token.py client_secret.json` → choose **Antarnaad Studio** when asked
   which channel → it prints three values.
5. Until Google completes the API audit, API uploads stay private. Set the repo variable
   `YT_PRIVACY=private` meanwhile and publish from YouTube Studio, or request the audit right away.

### 3. Instagram API
1. Instagram account `antarnaadin` → Professional (Creator) → linked to a Facebook Page "Antarnaad Studio".
2. Same Meta developer app as Embedded QA Architect is fine, or a new one; privacy URL = Pages privacy page.
3. Permissions: `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`.
4. Long-lived token + Instagram business account ID (Graph API Explorer: `me/accounts` → page id →
   `{page-id}?fields=instagram_business_account`). Tokens last ~60 days — renew before then.

### 4. Gemini backgrounds (optional)
aistudio.google.com → Get API key. Image generation may be billed on your Google account; without the key
the next fallback is used. Model can be changed with the repo variable `GEMINI_IMAGE_MODEL`.
The free Gemini tier has no image quota (HTTP 429): turn on billing for the key's project to use it.

Background order: Pexels video → Pixabay video → Gemini image → reviewed CC0/public-domain photo from
`assets/photos/` → built-in drawn scene.

### 4b. Photo library (no key needed)
Actions → *Harvest background photos* → Run. It adds real CC0 photos from Openverse to `assets/photos/<mood>/`.
**Review every new photo by eye** before the next post: delete unsuitable ones (people in swimwear, text,
weapons, logos…) and add their ids to `assets/photos/rejected.txt` so they never come back.

### 5. GitHub secrets and variables
Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | from step 2.4 |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | from step 3.4 |
| `PIXABAY_API_KEY` | free key from pixabay.com/api/docs (real stock-video backgrounds) |
| `PEXELS_API_KEY` | optional, pexels.com/api (new keys paused as of Nov 2026) |
| `GEMINI_API_KEY` | from step 4 (optional: photorealistic AI images when no stock clip fits) |

| Variable (optional) | Default |
|---|---|
| `YT_PRIVACY` | `public` |
| `ANTARNAAD_VOICE_HI` | `hi-IN-MadhurNeural` (female: `hi-IN-SwaraNeural`) |
| `ANTARNAAD_VOICE_EN` | `en-IN-PrabhatNeural` (female: `en-IN-NeerjaNeural`) |

A platform with no secrets is skipped, so YouTube can go live before Instagram is ready.

### 6. First test
Actions → *Post Antarnaad reels* → **Run workflow** → set `preview_day` to tomorrow's date → Run.
Download the 5 reels from the run's artifacts and check voice, text and music. Then run once with
`slot = 1` and `dry_run` unticked to post a real reel. After that the schedule takes over.

## Daily care (optional, 2 minutes)
For a positive story in the news, add a verified quote to `data/trending.json` (edit it on github.com):

```json
{
  "2026-11-03": {
    "id": "news-2026-11-03", "lang": "en", "hook": "Today's champion said:",
    "lines": ["line one", "line two", "line three"],
    "subtitle": "हिंदी में एक पंक्ति", "author": "Name", "author_en": "Name",
    "source": "Interview with ..., 2 Nov 2026", "topic_tags": ["#Name", "#ProudIndian"]
  }
}
```
Exact words from a named source only. No photos or logos; no politics, controversy or tragedy.

## Feedback loop (learns what works)
- `pipeline/collect_stats.py` reads views and likes of the latest videos from the channel's public RSS feed every
  3 hours (no key) into `data/stats.json`. Each post is also logged in `data/history.json`.
- `pipeline/feedback.py` scores each post (views + 10 × likes, read about a day after posting), averages by author,
  and picks for each slot the best-scoring quote that has rested 7 days. About 1 slot in 5 tries a quote that was
  never posted, at most 2 reels per author per day. With no stats yet it falls back to the fixed rotation.
- To see what is winning: `python pipeline/feedback.py` is not a CLI; use
  `python -c "import sys; sys.path.insert(0,'pipeline'); import plan, feedback; print(feedback.report(plan.all_quotes()))"`.
- More quotes by the top authors make the loop more useful: add them to `data/quote_bank.json`.

## Festivals and national days
`data/special_days.json` lists dated reels that replace the normal slots that day (2–3 in the morning slots):
`{"2026-11-14": {"name": "Children's Day", "slots": {"1": {...quote...}, "2": {"ref": "<existing quote id>"}}}}`.
Titles become "<Name> Special | …". Filled through Jan 2027; extend it a few months ahead.
