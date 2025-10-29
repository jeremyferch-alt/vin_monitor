#!/usr/bin/env python3
"""
VIN monitor: searches the web daily for exact VIN matches and only alerts on *new* hits.
- Uses Bing Web Search API by default (recommended).
- Stores seen URLs in a local JSON state file to avoid duplicate alerts.
- Notifies via SMTP email and/or Slack webhook (both optional—configure via env).
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

import requests
from dotenv import load_dotenv

# ----- Config -----
load_dotenv()  # load from .env if present (for local runs)

VIN = os.getenv("VIN")  # REQUIRED (single VIN string). For multiple, separate with commas.
BING_KEY = os.getenv("BING_KEY")  # REQUIRED if using Bing
GOOGLE_CSE_KEY = os.getenv("GOOGLE_CSE_KEY")  # Optional
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    # Optional

STATE_PATH = os.getenv("STATE_PATH", "state.json")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "25"))
USER_AGENT = os.getenv("USER_AGENT", "vin-monitor/1.0 (+no-auto-scrape; search-api-only)")

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
        return {"seen": {}}  # {vin: set-of-urls}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # ensure shapes
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
    """Normalize URL to reduce duplicates; strip common tracking params."""
    try:
        parsed = urlparse(u)
        # drop query tracking params
        qs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
              if not k.lower().startswith(("utm_", "gclid", "fbclid", "mc_cid", "mc_eid"))]
        new_query = urlencode(qs)
        # force scheme/host lower
        new_netloc = parsed.netloc.lower()
        # remove default ports
        new_netloc = new_netloc.replace(":80", "").replace(":443", "")
        normalized = urlunparse((parsed.scheme.lower(), new_netloc, parsed.path, parsed.params, new_query, ""))
        return normalized
    except Exception:
        return u

def chunk(items, size):
    for i in range(0, len(items), size):
        yield items[i:i+size]

# ----- Search Providers -----
def search_bing_exact(query: str, count: int = 20) -> list[dict]:
    if not BING_KEY:
        return []
    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": BING_KEY, "User-Agent": USER_AGENT}
    params = {"q": query, "count": min(count, 50), "textDecorations": False, "textFormat": "Raw"}
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    web = data.get("webPages", {}).get("value", [])
    out = []
    for w in web:
        out.append({
            "title": w.get("name"),
            "url": w.get("url"),
            "snippet": w.get("snippet"),
            "source": "bing",
            "date": w.get("dateLastCrawled"),
        })
    return out

def search_google_cse_exact(query: str, num: int = 10) -> list[dict]:
    if not (GOOGLE_CSE_KEY and GOOGLE_CSE_ID):
        return []
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_CSE_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": min(num, 10)}
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
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
    # exact phrase search per VIN
    queries = [f'"{v}"' for v in vins]

    state = load_state(STATE_PATH)

    any_new = False
    for v, q in zip(vins, queries):
        print(f"Searching for VIN: {v}")
        results = []
        # Provider 1: Bing (recommended, set BING_KEY)
        results.extend(search_bing_exact(q, count=MAX_RESULTS))
        time.sleep(0.5)
        # Provider 2: Google CSE (optional, set GOOGLE_CSE_*)
        results.extend(search_google_cse_exact(q, num=min(10, MAX_RESULTS)))

        seen = set(state["seen"].get(v, []))
        new_hits = []

        for r in results:
            u_norm = normalize_url(r["url"])
            if u_norm not in seen:
                new_hits.append((u_norm, r))

        if new_hits:
            any_new = True
            # Update state
            for u_norm, _ in new_hits:
                seen.add(u_norm)
            state["seen"][v] = sorted(seen)

            # Prepare notification
            lines = [f"New matches for VIN {v} (found {len(new_hits)}):", ""]
            for u_norm, r in new_hits:
                title = r.get("title") or "(no title)"
                snippet = r.get("snippet") or ""
                source = r.get("source", "unknown")
                date = r.get("date") or ""
                lines.append(f"- {title}\n  {u_norm}\n  [{source}] {date}\n  {snippet}\n")
            body = "\n".join(lines)

            # Send
            send_email(subject=f"VIN NEW MATCH: {v}", body=body)
            send_slack(body)
            print(body)
        else:
            print(f"No NEW matches for {v}. ({len(results)} results scanned)")

    # Persist state if anything changed
    if any_new:
        save_state(STATE_PATH, state)

if __name__ == "__main__":
    main()
