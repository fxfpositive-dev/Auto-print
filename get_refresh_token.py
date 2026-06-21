# One-time script — run locally to get your Google OAuth2 refresh token.
# Prerequisites:
#   1. Google Cloud Console > APIs & Services > Credentials
#   2. Create OAuth 2.0 Client ID (Desktop app)
#   3. Download the JSON and save as client_secret.json in this directory
#   4. Enable Gmail API and Google Calendar API in the project
#
# Usage:
#   pip install google-auth-oauthlib
#   python get_refresh_token.py
#
# Then add the printed values as GitHub repository secrets.

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0)

print("\n=== Add these as GitHub repository secrets ===")
print(f"GOOGLE_CLIENT_ID     = {creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET = {creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN = {creds.refresh_token}")
