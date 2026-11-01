#!/usr/bin/env python3
"""One-time, on your own computer: prints the YouTube refresh token for the GitHub secret.

  pip install google-auth-oauthlib
  python tools/get_youtube_token.py client_secret.json

A browser opens. Sign in with embeddedtestsolutions@gmail.com and, when Google asks which
account or channel to use, pick "Antarnaad Studio" (not Embedded QA Architect).
"""
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json",
                                                 ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
print("\nYT_CLIENT_ID     =", creds.client_id)
print("YT_CLIENT_SECRET =", creds.client_secret)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
print("\nPaste these three into GitHub: repo Settings -> Secrets and variables -> Actions -> New repository secret.")
