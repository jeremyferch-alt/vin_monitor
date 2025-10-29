
# VIN Monitor (alerts only on NEW matches)

This project searches the web for an exact VIN match and **alerts only when new results appear**, using a small JSON `state.json` to remember previously-seen URLs.

## Two ways to run

### A) GitHub Actions (no server needed)
1. Create a **private GitHub repo** and upload these files.
2. In your repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add at minimum:
   - `VIN` – the VIN (or multiple, comma-separated)
   - `BING_KEY` – your Azure Bing Web Search API key
   - (Optional) Email/Slack secrets for notifications: `TO_EMAIL`, `FROM_EMAIL`, `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SLACK_WEBHOOK_URL`
3. The workflow in `.github/workflows/daily-vin-check.yml` is scheduled for **13:15 UTC** (~08:15 America/Chicago during DST). Adjust the cron as needed.
4. You can also run it anytime via **Actions → Run workflow**.

The workflow uploads the current `state.json` as an artifact after each run so you can inspect it.

### B) Run locally (cron / Task Scheduler)
1. Install Python 3.10+.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill values.
4. Test: `python check_vin.py`
5. Schedule:
   - **macOS / Linux**: `crontab -e` → `15 8 * * * /usr/bin/python3 /path/to/check_vin.py`
   - **Windows**: Task Scheduler → Create Basic Task to run `python check_vin.py` daily.

## How it avoids duplicate alerts
- Every URL is **normalized** (strips UTM, fbclid, etc.) and stored under your VIN in `state.json`.
- On each run, only **previously unseen** URLs trigger an alert.

## Multiple VINs
Set `VIN` to a comma-separated list, e.g. `VIN=VIN1,VIN2,VIN3`. Each VIN maintains its own seen list.

## Providers
- **Bing Web Search API** (recommended): comprehensive and reliable.
- **Google Custom Search** (optional): requires a CSE engine (`GOOGLE_CSE_ID`) and API key.

## Notifications
- **Email via SMTP**: set the SMTP env vars and `TO_EMAIL`/`FROM_EMAIL`.
- **Slack**: set `SLACK_WEBHOOK_URL`.

## Tips
- Searches use **exact phrase** (`"VIN"`) to reduce false positives.
- Some marketplaces render VINs as images or script-loaded; those may not appear in generic web search.
- Respect all site terms and API usage limits.

## Security
Keep your repo **private** and store secrets in **GitHub Actions Secrets**, not in code.

---

Made for daily VIN checks with minimal noise.
