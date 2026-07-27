#!/usr/bin/env python3
"""Check Waldrand Apartments availability on Booking.com and notify via ntfy."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BOOKING_URL = os.environ.get(
    "BOOKING_URL",
    "https://www.booking.com/hotel/at/apartment-waldrand.html"
    "?checkin=2026-08-03&checkout=2026-08-11"
    "&group_adults=2&group_children=4&age=10&age=6&age=7&age=8"
    "&no_rooms=2&room1=A%2C6%2C7&room2=A%2C8%2C10",
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "esty-waldrand-aug2026-watch")
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
PROPERTY_NAME = "Waldrand Apartments"

UNAVAILABLE_PATTERNS = [
    r"sold out",
    r"no availability",
    r"we have no availability",
    r"not available for your dates",
    r"לא זמין",
]
PRICE_PATTERN = re.compile(r"[₪€$]\s?[\d,]+")
SELECT_ROOMS_PATTERN = re.compile(r"select rooms", re.IGNORECASE)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_signature": None}


def save_state(state: dict) -> None:
    state["last_checked"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_page_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page.goto(BOOKING_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8_000)
        text = page.inner_text("body")
        browser.close()
    return text


def check_availability(text: str) -> tuple[bool, str | None]:
    lowered = text.lower()
    for pattern in UNAVAILABLE_PATTERNS:
        if re.search(pattern, lowered):
            return False, None

    has_select_rooms = bool(SELECT_ROOMS_PATTERN.search(text))
    prices = PRICE_PATTERN.findall(text)
    if has_select_rooms and prices:
        numeric = []
        for price in prices:
            digits = re.sub(r"[^\d]", "", price)
            if not digits:
                continue
            value = int(digits)
            # Ignore tiny false positives (fees, per-night fragments, etc.)
            if "₪" in price and value < 1000:
                continue
            if ("€" in price or "$" in price) and value < 100:
                continue
            numeric.append((value, price))
        lowest = min(numeric, key=lambda x: x[0])[1] if numeric else (prices[0] if prices else None)
        return True, lowest

    if "i'll reserve" in lowered or "reserve your apartment" in lowered:
        return True, prices[0] if prices else None

    return False, None


def send_ntfy(title: str, message: str, priority: str = "default", tags: str = "house") -> None:
    cmd = [
        "curl", "-s",
        "-d", message,
        "-H", f"Title: {title}",
        "-H", f"Priority: {priority}",
        "-H", f"Tags: {tags}",
        f"https://ntfy.sh/{NTFY_TOPIC}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ntfy failed: {result.stderr or result.stdout}")


def main() -> int:
    state = load_state()
    previous = state.get("last_signature")

    try:
        text = fetch_page_text()
    except Exception as exc:
        print(f"ERROR: could not load Booking page: {exc}", file=sys.stderr)
        return 1

    available, lowest_price = check_availability(text)
    current = "AVAILABLE" if available else "UNAVAILABLE"

    if available:
        price_note = f" מחיר מ-{lowest_price}." if lowest_price else ""
        send_ntfy(
            "דירה עדיין זמינה",
            f"{PROPERTY_NAME} עדיין זמינה ל-03.08–11.08 (2 מבוגרים + 4 ילדים).{price_note}",
            priority="default",
            tags="house,white_check_mark",
        )
        state["last_signature"] = "AVAILABLE"
        if lowest_price:
            state["lowest_price"] = lowest_price
        save_state(state)
        print(f"AVAILABLE{price_note} — heartbeat sent")
        return 0

    if previous == "AVAILABLE" or (previous is None and os.environ.get("NOTIFY_IF_ALREADY_UNAVAILABLE") == "true"):
        send_ntfy(
            "דירה נתפסה ב-Booking!",
            f"הדירה {PROPERTY_NAME} נתפסה! כבר לא זמינה ל-03.08–11.08 (2 מבוגרים + 4 ילדים).",
            priority="urgent",
            tags="warning,rotating_light",
        )
        print("UNAVAILABLE — urgent alert sent")
    else:
        print("UNAVAILABLE — silent (already reported)")

    state["last_signature"] = "UNAVAILABLE"
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
