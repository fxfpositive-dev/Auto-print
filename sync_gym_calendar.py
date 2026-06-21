import os
import re
import base64
import html as html_lib
from datetime import datetime, timedelta
import pytz

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SENDER = "sender@goodlifegymjapan.com"
CALENDAR_ID = "fxfpositive@gmail.com"
EVENT_SUMMARY = "GYM"
TZ = pytz.timezone("Asia/Tokyo")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

DATETIME_RE = re.compile(
    r"日時：(\d{4})年(\d{1,2})月(\d{1,2})日[（(][月火水木金土日][）)]\s*(\d{2}):(\d{2})〜(\d{2}):(\d{2})"
)
STORE_RE = re.compile(r"店舗：(.+)")


def get_credentials():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def _decode_b64(data: str) -> str:
    pad = (4 - len(data) % 4) % 4
    return base64.urlsafe_b64decode(data + "=" * pad).decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html_lib.unescape(text)


def extract_body(payload: dict) -> str:
    """Return plain text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data", "")

    if mime == "text/plain" and data:
        return _decode_b64(data)
    if mime == "text/html" and data:
        return _strip_html(_decode_b64(data))

    # multipart: prefer text/plain, fall back to text/html
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            d = part.get("body", {}).get("data", "")
            if d:
                return _decode_b64(d)
    for part in parts:
        if part.get("mimeType") == "text/html":
            d = part.get("body", {}).get("data", "")
            if d:
                return _strip_html(_decode_b64(d))
    return ""


def parse_booking(body: str):
    """Extract start/end datetimes and store name from email body."""
    text = _strip_html(body) if "<" in body else body
    m = DATETIME_RE.search(text)
    s = STORE_RE.search(text)
    if not m or not s:
        return None
    year, month, day, sh, sm, eh, em = (int(x) for x in m.groups())
    store = s.group(1).strip()
    start = TZ.localize(datetime(year, month, day, sh, sm))
    end = TZ.localize(datetime(year, month, day, eh, em))
    return {"start": start, "end": end, "store": store}


def create_event(cal, info: dict):
    body = {
        "summary": EVENT_SUMMARY,
        "location": f"GOODLIFE GYM {info['store']}",
        "start": {"dateTime": info["start"].isoformat(), "timeZone": "Asia/Tokyo"},
        "end":   {"dateTime": info["end"].isoformat(),   "timeZone": "Asia/Tokyo"},
    }
    cal.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    print(f"[+] Created: {info['start'].strftime('%Y-%m-%d %H:%M')} {info['store']}")


def delete_event(cal, info: dict):
    time_min = info["start"].isoformat()
    time_max = (info["start"] + timedelta(minutes=1)).isoformat()
    resp = cal.events().list(
        calendarId=CALENDAR_ID,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
    ).execute()
    for event in resp.get("items", []):
        if event.get("summary") == EVENT_SUMMARY:
            cal.events().delete(calendarId=CALENDAR_ID, eventId=event["id"]).execute()
            print(f"[-] Deleted: {info['start'].strftime('%Y-%m-%d %H:%M')} {info['store']}")
            return
    print(f"[?] No calendar event found for: {info['start'].strftime('%Y-%m-%d %H:%M')}")


def trash_message(gmail, msg_id: str):
    gmail.users().messages().trash(userId="me", id=msg_id).execute()


def main():
    creds = get_credentials()
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)

    query = f"from:{SENDER} is:unread (subject:予約完了 OR subject:予約キャンセル)"
    result = gmail.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = result.get("messages", [])

    if not messages:
        print("No unread gym emails.")
        return

    for ref in messages:
        msg = gmail.users().messages().get(
            userId="me", id=ref["id"], format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        subject = headers.get("Subject", "")
        body = extract_body(msg["payload"])
        info = parse_booking(body)

        if not info:
            print(f"[!] Could not parse: {subject}")
            continue

        try:
            if "予約完了" in subject:
                create_event(cal, info)
            elif "予約キャンセル" in subject:
                delete_event(cal, info)
            else:
                continue
            trash_message(gmail, msg["id"])
        except Exception as e:
            print(f"[!] Error on '{subject}': {e}")
            raise


if __name__ == "__main__":
    main()
