
# VIN Monitor — Google Programmable Search (only)

This version uses **Google Programmable Search (Custom Search JSON API)** only, and alerts **only when new results appear**. It stores previously-seen URLs in `state.json`.

## Setup (GitHub Actions)

1. Create a **private** GitHub repo and upload these files.
2. Add Secrets (Settings → Secrets and variables → Actions):
   - `VIN` — the VIN (or multiple, comma-separated)
   - `GOOGLE_CSE_KEY` — Google API key (enable **Custom Search API** in Google Cloud)
   - `GOOGLE_CSE_ID` — your Programmable Search Engine ID (set to **Search the entire web**) 
   - Optional email/Slack secrets for notifications: `TO_EMAIL`, `FROM_EMAIL`, `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SLACK_WEBHOOK_URL`
3. The workflow in `.github/workflows/daily-vin-check.yml` runs daily at **13:15 UTC** (~08:15 America/Chicago). Adjust the cron if needed.
4. Trigger a manual run under the **Actions** tab to test.

## Local Run

```
pip install -r requirements.txt
cp .env.example .env  # fill values
python check_vin.py
```

## Notes
- Searches use exact phrase: `"VIN"` to reduce false positives.
- Some marketplaces render VINs in images or behind JS; these may not appear.
- Respect API quotas and terms.
