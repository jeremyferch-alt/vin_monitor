#!/usr/bin/env python3
"""
VIN monitor (Google-only): searches daily for exact VIN matches and alerts only on *new* hits.
- Uses Google Programmable Search (Custom Search JSON API).
- Stores seen URLs in state.json to avoid duplicate alerts.
- Notifies via SMTP email and/or Slack webhook (optional).
"""
import json
import os
import sys
import time
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

import requests
from dotenv import load_dotenv

# ----- Config -----
load_dotenv()  # load from .env if present (for local runs)

VIN = os.getenv("VIN")  # REQUIRED (single VIN or comma-separated list)
GOOGLE_CSE_KEY = os.getenv("GOOGLE_CSE_KEY")  # REQUIRED
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    # REQUIRED

STATE_PATH = os.getenv("STATE_PATH", "state.json")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "10"))  # Google CSE returns up to 10 per call
USER_AGENT = os.getenv("USER_AGENT", "vin-monitor/1.0 (google-cse)")

# Notifications (optional)
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else None
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# ----- Helpers -----
def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"seen": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("seen", {})
        return data
    except Exception:
        return {"seen": {}}

def save_state(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def normalize_url(u: str) -> str:
    try:
        parsed = urlparse(u)
        qs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
              if not k.lower().startswith(("utm_", "gclid", "fbclid", "mc_cid", "mc_eid"))]
        new_query = urlencode(qs)
        new_netloc = parsed.netloc.lower().replace(":80", "").replace(":443", "")
        return urlunparse((parsed.scheme.lower(), new_netloc, parsed.path, parsed.params, new_query, ""))
    except Exception:
        return u

# ----- Search (Google only) -----
def search_google_cse_exact(query: str, num: int = 10) -> list[dict]:
    if not (GOOGLE_CSE_KEY and GOOGLE_CSE_ID):
        raise SystemExit("ERROR: GOOGLE_CSE_KEY and GOOGLE_CSE_ID must be set.")
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_CSE_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": min(num, 10)}
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
    if r.status_code == 429:
        print("Rate limited by Google CSE (HTTP 429). Try again later or reduce frequency.", file=sys.stderr)
        return []
    r.raise_for_status()
    data = r.json()
    items = data.get("items", []) or []
    out = []
    for it in items:
        out.append({
            "title": it.get("title"),
            "url": it.get("link"),
            "snippet": it.get("snippet"),
            "source": "google_cse",
            "date": it.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time")
        })
    return out

# ----- Notifications -----
def send_email(subject: str, body: str):
    if not (TO_EMAIL and FROM_EMAIL and SMTP_SERVER and SMTP_PORT and SMTP_USER and SMTP_PASS):
        return
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=15)
    except Exception as e:
        print("Slack notify failed:", e, file=sys.stderr)

# ----- Main -----
def main():
    if not VIN:
        print("ERROR: Set VIN environment variable.", file=sys.stderr)
        sys.exit(2)

    vins = [v.strip() for v in VIN.split(",") if v.strip()]
    queries = [f'\"{v}\"' for v in vins]  # exact phrase

    state = load_state(STATE_PATH)
    any_new = False

    for v, q in zip(vins, queries):
        print(f"Searching for VIN via Google CSE: {v}")
        results = search_google_cse_exact(q, num=MAX_RESULTS)

        seen = set(state["seen"].get(v, []))
        new_hits = []

        for r in results:
            u_norm = normalize_url(r["url"])
            if u_norm not in seen:
                new_hits.append((u_norm, r))

        if new_hits:
            any_new = True
            for u_norm, _ in new_hits:
                seen.add(u_norm)
            state["seen"][v] = sorted(seen)

            lines = [f"New matches for VIN {v} (found {len(new_hits)}):", ""]
            for u_norm, r in new_hits:
                title = r.get("title") or "(no title)"
                snippet = r.get("snippet") or ""
                source = r.get("source", "google_cse")
                date = r.get("date") or ""
                lines.append(f"- {title}\n  {u_norm}\n  [{source}] {date}\n  {snippet}\n")
            body = "\n".join(lines)

            send_email(subject=f"VIN NEW MATCH: {v}", body=body)
            send_slack(body)
            print(body)
        else:
            print(f"No NEW matches for {v}. ({len(results)} results scanned)")

    if any_new:
        save_state(STATE_PATH, state)

if __name__ == "__main__":
    main()
