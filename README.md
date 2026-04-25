# Texas DPS Earlier Slot Monitor

A local web app that monitors Texas DPS appointment availability and can reschedule to an earlier slot when one is found.

## Important Notice

- This tool is unofficial and is **not affiliated** with Texas DPS.
- Use it only for your own appointment/account.
- Run it locally on your own machine.
- Session tokens can expire and may need to be refreshed.

## What It Does

- Stores your DPS lookup settings in server memory while the app is running.
- Tests your login/session token before starting monitoring.
- Polls for earlier appointment availability near your ZIP code.
- Optionally attempts auto-reschedule when an earlier slot is available.
- Can restrict same-day booking unless **Allow rescheduling to today's available slots** is enabled.
- Shows live activity logs in the UI.
- Shows appointment details in a collapsible panel (when available):
  - Current appointment
  - Current location

## Tech Stack

- FastAPI backend
- Vanilla HTML/CSS/JavaScript frontend
- `requests` for DPS API calls

## Project Structure

```text
app/
  main.py           # FastAPI app and API routes
static/
  index.html        # UI layout
  app.js            # Frontend behavior and polling
  styles.css        # Styling
dps_client.py       # DPS client logic + monitor loop
requirements.txt    # Python dependencies
```

## Requirements

- Python 3.9+ (recommended)
- macOS/Linux/Windows terminal

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Usage Flow

1. Open the app in your browser.
2. Choose scheduler site (`public` or `www`) to match the site you use for DPS login.
3. Enter your details.
4. Click **Save settings**.
5. Click **Connect DPS session** and complete login/captcha in the opened browser window.
6. Click **Test connection**.
7. Click **Start monitoring**.
8. Watch the status strip, activity log, and appointment details panel.

## Session Token (High Level)

Preferred: use **Connect DPS session** to capture token automatically from a real browser login.

The app stores token/session state server-side for monitoring; if it expires, run **Connect DPS session** again.

## API Endpoints

- `GET /` – UI
- `GET /api/status` – monitor state, logs, and appointment details
- `POST /api/settings` – save settings
- `GET /api/settings` – load saved settings
- `POST /api/test-connection` – validate identity/token
- `POST /api/session/connect` – open browser login and capture session token
- `POST /api/start` – start monitoring
- `POST /api/stop` – stop monitoring
- `POST /api/logs/clear` – clear activity log

## Troubleshooting

- `401` errors:
  - Token/session expired or scheduler host mismatched (`public` vs `www`).
  - Run **Connect DPS session** again and complete login/captcha.
- No earlier slots found:
  - Increase max distance.
  - Enable same-day booking if you also want today's slots considered.
  - Keep monitor running longer.
- App won’t start:
  - Save settings first.
  - Run **Test connection** to verify credentials/token.

## Security Notes

- This app keeps data in process memory; it does not implement persistent encrypted storage.
- Treat your session token and personal details as sensitive.
- Do not share logs/screenshots containing private information.

## License

See [LICENSE](LICENSE).
