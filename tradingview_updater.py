"""
TradingView Watchlist Updater
Logs into TradingView and adds scraped tickers to the 'Twitter Picks' watchlist.
Uses Playwright for browser automation.
"""

import json
import os
import time
import sys
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Installing playwright...")
    os.system("pip install playwright --break-system-packages && playwright install chromium")
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── CONFIG ─────────────────────────────────────────────────────────────────────
TV_EMAIL    = os.environ.get("TV_EMAIL", "kathirstocks@gmail.com")
TV_PASSWORD = os.environ.get("TV_PASSWORD", "")  # Always load from secret in CI
WATCHLIST_NAME = "Twitter Picks"
TICKERS_FILE   = "tickers_today.json"


def load_tickers() -> list[str]:
    """Load tickers from the JSON file produced by scraper.py."""
    if not os.path.exists(TICKERS_FILE):
        print(f"❌ {TICKERS_FILE} not found. Run scraper.py first.")
        sys.exit(1)
    with open(TICKERS_FILE) as f:
        data = json.load(f)
    tickers = data.get("all_tickers", [])
    print(f"📋 Loaded {len(tickers)} tickers: {tickers}")
    return tickers


def add_tickers_to_watchlist(tickers: list[str]):
    if not tickers:
        print("No tickers to add.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # ── 1. LOGIN ──────────────────────────────────────────────────────────
        print("🔐 Logging into TradingView...")
        page.goto("https://www.tradingview.com/accounts/signin/", wait_until="networkidle")
        time.sleep(2)

        # Click "Email" sign-in option
        try:
            page.click("text=Email", timeout=8000)
            time.sleep(1)
        except PlaywrightTimeout:
            pass  # Already on email form

        page.fill('input[name="username"]', TV_EMAIL)
        page.fill('input[name="password"]', TV_PASSWORD)
        page.click('button[type="submit"]')
        time.sleep(5)

        # Check login success
        if "signin" in page.url:
            print("❌ Login failed. Check credentials.")
            browser.close()
            sys.exit(1)
        print("✅ Logged in!")

        # ── 2. OPEN WATCHLIST PAGE ────────────────────────────────────────────
        page.goto("https://www.tradingview.com/chart/", wait_until="networkidle")
        time.sleep(4)

        # ── 3. FIND OR CREATE WATCHLIST ───────────────────────────────────────
        print(f"📂 Looking for watchlist: '{WATCHLIST_NAME}'...")

        # Click the Watchlist panel icon (right sidebar)
        try:
            page.click('[data-name="watchlists"]', timeout=6000)
            time.sleep(2)
        except PlaywrightTimeout:
            try:
                page.click('button[aria-label="Watchlist"]', timeout=6000)
                time.sleep(2)
            except PlaywrightTimeout:
                print("⚠️  Could not find watchlist button, trying keyboard shortcut...")
                page.keyboard.press("w")
                time.sleep(2)

        # Check if "Twitter Picks" watchlist exists; if not, create it
        watchlist_found = False
        try:
            wl_item = page.locator(f"text={WATCHLIST_NAME}").first
            wl_item.click(timeout=4000)
            watchlist_found = True
            print(f"✅ Found existing watchlist '{WATCHLIST_NAME}'")
        except PlaywrightTimeout:
            print(f"➕ Creating new watchlist '{WATCHLIST_NAME}'...")
            # Click the "+" or "New list" button
            try:
                page.click('[data-name="create-watchlist"]', timeout=5000)
            except PlaywrightTimeout:
                page.click('button[aria-label="Add symbol list"]', timeout=5000)
            time.sleep(1)
            # Type the name
            page.keyboard.type(WATCHLIST_NAME)
            page.keyboard.press("Enter")
            time.sleep(2)
            print(f"✅ Created watchlist '{WATCHLIST_NAME}'")

        # ── 4. ADD TICKERS ────────────────────────────────────────────────────
        print(f"\n📈 Adding {len(tickers)} tickers to '{WATCHLIST_NAME}'...")

        for ticker in tickers:
            try:
                # Click "Add symbol" button (the + icon in watchlist)
                add_btn = page.locator('[data-name="add-symbol-button"]').first
                add_btn.click(timeout=5000)
                time.sleep(0.8)

                # Type ticker in search box
                page.keyboard.type(ticker, delay=50)
                time.sleep(1.5)

                # Select first result
                first_result = page.locator('.tv-symbolList__item').first
                if first_result.is_visible():
                    first_result.click(timeout=3000)
                    print(f"  ✓ Added: {ticker}")
                else:
                    # Fallback: press Enter
                    page.keyboard.press("Enter")
                    print(f"  ✓ Added (enter): {ticker}")
                time.sleep(0.5)

            except Exception as e:
                print(f"  ✗ Skipped {ticker}: {e}")
                page.keyboard.press("Escape")
                time.sleep(0.5)

        print(f"\n🎉 Done! {len(tickers)} tickers processed in '{WATCHLIST_NAME}'")
        browser.close()


def main():
    print(f"\n{'='*50}")
    print(f"📊 TradingView Updater — {datetime.now().strftime('%d %b %Y')}")
    print(f"{'='*50}\n")

    if not TV_PASSWORD:
        print("❌ TV_PASSWORD environment variable not set!")
        sys.exit(1)

    tickers = load_tickers()
    add_tickers_to_watchlist(tickers)


if __name__ == "__main__":
    main()
