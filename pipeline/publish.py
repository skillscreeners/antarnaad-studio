"""Uploads one reel to YouTube Shorts and Instagram Reels using credentials from environment
variables (GitHub Actions secrets). Nothing is read from or written to disk except the video.

YouTube:   YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Instagram: IG_USER_ID, IG_ACCESS_TOKEN  (optional IG_GRAPH_VERSION, default v21.0)
"""
import os, time
import requests

def youtube_upload(video_path, meta):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(Request())
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    y = meta["youtube"]
    body = {"snippet": {"title": y["title"], "description": y["description"], "tags": y["tags"],
                        "categoryId": y["categoryId"], "defaultLanguage": y["defaultLanguage"],
                        "defaultAudioLanguage": y["defaultLanguage"]},
            "status": {"privacyStatus": os.environ.get("YT_PRIVACY", "public"), "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]

def instagram_publish(video_path, caption):
    token, uid = os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"]
    ver = os.environ.get("IG_GRAPH_VERSION", "v21.0")
    host = os.environ.get("IG_GRAPH_HOST", "graph.facebook.com")
    g = lambda path: f"https://{host}/{ver}/{path}"
    r = requests.post(g(f"{uid}/media"), data={"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                      "share_to_feed": "true", "access_token": token}, timeout=60)
    r.raise_for_status(); cid = r.json()["id"]
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        u = requests.post(f"https://rupload.facebook.com/ig-api-upload/{ver}/{cid}",
                          headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}, data=f, timeout=600)
    u.raise_for_status()
    for _ in range(60):
        s = requests.get(g(cid), params={"fields": "status_code,status", "access_token": token}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram processing failed: {s}")
        time.sleep(10)
    else:
        raise TimeoutError("Instagram processing took more than 10 minutes")
    p = requests.post(g(f"{uid}/media_publish"), data={"creation_id": cid, "access_token": token}, timeout=60)
    p.raise_for_status()
    return p.json()["id"]
