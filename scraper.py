import re
import os
import requests
import time
from datetime import datetime, timedelta
from typing import List, Set
import json

# ── CONFIG (loaded from environment / GitHub Secrets) ──────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TWITTER_ACCOUNTS = [
    "sunilgurjar01",
    "thechartist26",
    "chartistrj",
    "stoxmee",
    "chartnavigators",
]

# Nitter public mirrors (fallback list)
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ── TICKER EXTRACTION ──────────────────────────────────────────────────────────
# Matches $TICKER (1-5 uppercase letters) or plain NSE/BSE style e.g. RELIANCE, INFY
TICKER_REGEX = re.compile(r'\$([A-Z]{1,10})|(?<!\w)([A-Z]{2,10})(?!\w)')

# Common false-positive words to skip
SKIP_WORDS = {
    "THE", "FOR", "AND", "BUT", "NOT", "YOU", "ALL", "CAN", "HAS", "ARE",
    "WAS", "HAD", "HIS", "HER", "ITS", "OUR", "OUT", "NOW", "GET", "SET",
    "NEW", "OLD", "BIG", "TOP", "LOW", "HIGH", "BUY", "SELL", "HOLD",
    "NSE", "BSE", "IPO", "SIP", "ETF", "FII", "DII", "LTP", "ATH", "ATL",
    "RSI", "EMA", "SMA", "MACD", "CEO", "CFO", "AGM", "EGM", "QIP",
    "LONG", "SHORT", "STOP", "LOSS", "TARGET", "PROFIT", "MARKET", "STOCK",
    "TRADE", "CHART", "VIEW", "IDEA", "SECTOR", "INDEX", "NIFTY", "SENSEX",
    "INDIA", "INR", "USD", "GOOD", "GREAT", "NEXT", "WEEK", "MONTH", "YEAR",
    "TODAY", "DAILY", "WATCH", "LIST", "ALERT", "SIGNAL", "CALL", "PUT",
    "TREND", "BREAK", "MOVE", "HUGE", "MEGA", "MINI", "MICRO", "MID", "CAP",
}


def extract_tickers(text: str) -> Set[str]:
    """Extract stock tickers from tweet text."""
    tickers = set()
    # Priority: $TICKER mentions
    dollar_tickers = re.findall(r'\$([A-Z]{1,10})', text.upper())
    for t in dollar_tickers:
        if t not in SKIP_WORDS and len(t) >= 2:
            tickers.add(t)

    # Also catch plain uppercase words if no $ tickers found
    if not dollar_tickers:
        plain = re.findall(r'(?<!\w)([A-Z]{2,10})(?!\w)', text.upper())
        for t in plain:
            if t not in SKIP_WORDS and len(t) >= 3:
                tickers.add(t)

    return tickers


# ── NITTER SCRAPING ────────────────────────────────────────────────────────────
def fetch_tweets_from_nitter(username: str) -> List[str]:
    """Try each Nitter instance until one works."""
    for base in NITTER_INSTANCES:
        url = f"{base}/{username}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                tweets = parse_nitter_html(resp.text)
                if tweets:
                    print(f"  ✓ Fetched @{username} from {base} ({len(tweets)} tweets)")
                    return tweets
        except Exception as e:
            print(f"  ✗ {base} failed for @{username}: {e}")
        time.sleep(1)
    print(f"  ✗ All Nitter instances failed for @{username}")
    return []


def parse_nitter_html(html: str) -> List[str]:
    """Extract tweet text from Nitter HTML (simple regex approach)."""
    # Nitter wraps tweet content in <div class="tweet-content ...">
    pattern = re.compile(
        r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
        re.DOTALL | re.IGNORECASE
    )
    raw_tweets = pattern.findall(html)
    cleaned = []
    for raw in raw_tweets:
        # Strip HTML tags
        text = re.sub(r'<[^>]+>', ' ', raw)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&#39;', "'", text)
        text = re.sub(r'&quot;', '"', text)
        text = ' '.join(text.split())
        if text:
            cleaned.append(text)
    return cleaned[:20]  # Latest 20 tweets per account


# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        print(f"Telegram error: {resp.text}")
    else:
        print("✅ Telegram message sent!")


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"🚀 Twitter Stock Scanner — {datetime.now().strftime('%d %b %Y %I:%M %p IST')}")
    print(f"{'='*50}\n")

    all_tickers: dict[str, Set[str]] = {}  # account → tickers

    for account in TWITTER_ACCOUNTS:
        print(f"📡 Scraping @{account}...")
        tweets = fetch_tweets_from_nitter(account)
        tickers = set()
        for tweet in tweets:
            tickers |= extract_tickers(tweet)
        all_tickers[account] = tickers
        print(f"   Found tickers: {tickers or 'None'}\n")
        time.sleep(2)

    # Build Telegram message
    date_str = datetime.now().strftime("%d %b %Y")
    lines = [f"📊 <b>Daily Stock Picks — {date_str}</b>\n"]

    total_unique = set()
    has_any = False

    for account, tickers in all_tickers.items():
        if tickers:
            has_any = True
            sorted_tickers = sorted(tickers)
            total_unique |= tickers
            lines.append(f"<b>@{account}</b>")
            lines.append("  " + "  |  ".join(f"#{t}" for t in sorted_tickers))
            lines.append("")

    if not has_any:
        lines.append("⚠️ No tickers found today. Nitter may be down.")
    else:
        lines.append(f"─────────────────────")
        lines.append(f"🔢 <b>Total unique: {len(total_unique)} tickers</b>")
        lines.append("  " + "  ".join(f"#{t}" for t in sorted(total_unique)))
        lines.append("")
        lines.append("📈 <i>Check TradingView watchlist: Twitter Picks</i>")

    message = "\n".join(lines)
    print("📨 Sending to Telegram...")
    print(message)
    send_telegram(message)

    # Save tickers to file for TradingView script
    output = {
        "date": date_str,
        "by_account": {k: list(v) for k, v in all_tickers.items()},
        "all_tickers": sorted(total_unique),
    }
    with open("tickers_today.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\n💾 Saved tickers_today.json")


if __name__ == "__main__":
    main()
