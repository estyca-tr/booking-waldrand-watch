# Booking Apartments Watch

Free monitor for Booking.com apartments.

- Checks every **4 hours** via GitHub Actions (free)
- Sends **ntfy** push notifications (free)
- Heartbeat while available; urgent alert when taken

## Monitored properties

Configured in `config.json`:

1. Waldrand Apartments
2. Appartement Schwab Ski-in Ski-out

## Setup

1. Install [ntfy](https://ntfy.sh) and subscribe to: `esty-waldrand-aug2026-watch`
2. GitHub Actions runs automatically on the public repo

## Add another apartment

Edit `config.json` — add an entry to `properties` with `id`, `name`, and `booking_url`.
