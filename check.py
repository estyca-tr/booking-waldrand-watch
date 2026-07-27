#!/usr/bin/env python3
"""Check Booking.com apartment availability and notify via ntfy."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "config.json"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

UNAVAILABLE_PATTERNS = [
    r"sold out",
    r"no availability",
    r"we have no availability",
    r"not available for your dates",
    r"לא זמין",
]
PRICE_PATTERN = re.compile(r"[₪€$]\s?[\d,]+")
SELECT_ROOMS_PATTERN = re.compile(r"select rooms", re.IGNORECASE)


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"properties": {}}


def save_state(state: dict) -> None:
    state["last_checked"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_page_text(page: Page, url: str) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(8_000)
    return page.inner_text("body")


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
            if "₪" in price and value < 1000:
                continue
            if ("€" in price or "$" in price) and value < 100:
                continue
            numeric.append((value, price))
        lowest = min(numeric, key=lambda x: x[0])[1] if numeric else (prices[0] if prices else None)
        return True, lowest

    if "i'll reserve" in lowered or "reserve your apartment" in lowered or "reserve" in lowered:
        return True, prices[0] if prices else None

    return False, None


def send_ntfy(
    topic: str,
    title: str,
    message: str,
    priority: str = "default",
    tags: str = "house",
    click_url: str | None = None,
) -> None:
    cmd = [
        "curl", "-s",
        "-d", message,
        "-H", f"Title: {title}",
        "-H", f"Priority: {priority}",
        "-H", f"Tags: {tags}",
    ]
    if click_url:
        cmd.extend(["-H", f"Click: {click_url}"])
    cmd.append(f"https://ntfy.sh/{topic}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ntfy failed: {result.stderr or result.stdout}")


def process_property(
    prop: dict,
    prop_state: dict,
    config: dict,
    page: Page,
) -> tuple[str, dict]:
    prop_id = prop["id"]
    name = prop["name"]
    booking_url = prop["booking_url"]
    date_label = config.get("date_label", "")
    guests_label = config.get("guests_label", "")
    topic = config.get("ntfy_topic") or os.environ.get("NTFY_TOPIC", "")
    previous = prop_state.get("last_signature")

    try:
        text = fetch_page_text(page, prop["booking_url"])
    except Exception as exc:
        return f"{name}: ERROR — {exc}", prop_state

    available, lowest_price = check_availability(text)

    if available:
        price_note = f" מחיר מ-{lowest_price}." if lowest_price else ""
        send_ntfy(
            topic,
            f"עדיין זמינה: {name}",
            f"{name} עדיין זמינה ל-{date_label} ({guests_label}).{price_note}\n\nלהזמנה: {booking_url}",
            priority="default",
            tags="house,white_check_mark",
            click_url=booking_url,
        )
        prop_state["last_signature"] = "AVAILABLE"
        if lowest_price:
            prop_state["lowest_price"] = lowest_price
        return f"{name}: AVAILABLE{price_note} — heartbeat sent", prop_state

    if previous == "AVAILABLE" or (
        previous is None and os.environ.get("NOTIFY_IF_ALREADY_UNAVAILABLE") == "true"
    ):
        send_ntfy(
            topic,
            f"נתפסה: {name}!",
            f"הדירה {name} נתפסה! כבר לא זמינה ל-{date_label} ({guests_label}).\n\nלינק (לבדיקה): {booking_url}",
            priority="urgent",
            tags="warning,rotating_light",
            click_url=booking_url,
        )
        result = f"{name}: UNAVAILABLE — urgent alert sent"
    else:
        result = f"{name}: UNAVAILABLE — silent (already reported)"

    prop_state["last_signature"] = "UNAVAILABLE"
    return result, prop_state


def main() -> int:
    config = load_config()
    state = load_state()
    properties = config.get("properties", [])
    if not properties:
        print("ERROR: no properties in config", file=sys.stderr)
        return 1

    prop_states = state.setdefault("properties", {})
    results: list[str] = []
    exit_code = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        for prop in properties:
            prop_id = prop["id"]
            prop_state = prop_states.setdefault(prop_id, {})
            result, prop_states[prop_id] = process_property(prop, prop_state, config, page)
            results.append(result)
            if result.startswith(prop["name"] + ": ERROR"):
                exit_code = 1
        browser.close()

    save_state(state)
    for line in results:
        print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
