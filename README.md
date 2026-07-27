# Booking Waldrand Watch

Free monitor for **Waldrand Apartments** on Booking.com.

- Checks every **4 hours** via GitHub Actions (free)
- Sends **ntfy** push notifications (free)
- Heartbeat while available; urgent alert when taken

## Setup

1. Install [ntfy](https://ntfy.sh) on your phone and subscribe to: `esty-waldrand-aug2026-watch`
2. Push this repo to GitHub (public repo = free unlimited Actions)
3. Enable GitHub Actions in the repo settings
4. Optionally run manually: Actions → Booking Waldrand Watch → Run workflow

## Local test

```bash
pip install -r requirements.txt
playwright install chromium
python check.py
```

## Dates & guests

- Check-in: 2026-08-03
- Check-out: 2026-08-11
- 2 adults + 4 children (ages 6, 7, 8, 10), 2 rooms
