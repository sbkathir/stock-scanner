import re
import os
import requests
import time
from datetime import datetime, timedelta, timezone
from typing import List, Set
import json

# ── CONFIG ─────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# How many days back to scan (default 5, override with env var DAYS_BACK)
DAYS_BACK = int(os.environ.get("DAYS_BACK", "5"))

TWITTER_ACCOUNTS = [
    "sunilgurjar01",
    "thechartist26",
    "chartistrj",
    "stoxmee",
    "chartnavigators",
    "_chartwizard_",
]

TELEGRAM_CHANNELS = [
    "Bschart1",
    "TradeTheTrend_",
    "ChartAddict007",
]

NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://nitter.catsarch.com",
    "https://nitter.privacydev.net",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

NSE_TICKER_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# Loaded once at runtime — real NSE ticker symbols, used to validate candidates
VALID_NSE_TICKERS: Set[str] = set()


def load_nse_tickers() -> Set[str]:
    """Download the official NSE equity list and return the set of valid symbols."""
    try:
        resp = requests.get(NSE_TICKER_LIST_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        symbols = set()
        lines = resp.text.splitlines()
        for line in lines[1:]:  # skip header row "SYMBOL,NAME OF COMPANY,..."
            parts = line.split(",")
            if parts and parts[0].strip():
                symbols.add(parts[0].strip().upper())
        print(f"📋 Loaded {len(symbols)} valid NSE ticker symbols for validation")
        return symbols
    except Exception as e:
        print(f"⚠️ Could not load NSE ticker list ({e}); falling back to unvalidated extraction")
        return set()

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
    "THIS", "WITH", "FROM", "THAT", "THEY", "BEEN", "WILL", "HAVE", "MORE",
}


# ── TICKER EXTRACTION ──────────────────────────────────────────────────────────
def extract_tickers(text: str) -> Set[str]:
    candidates = set()
    upper = text.upper()

    # ① $TICKER format — e.g. $RELIANCE
    dollar_tickers = re.findall(r'\$([A-Z]{1,15})', upper)
    for t in dollar_tickers:
        if t not in SKIP_WORDS and len(t) >= 2:
            candidates.add(t)

    # ② #TICKER format — e.g. #TALBROAUTO #SAREGAMA (stoxmee style)
    hash_tickers = re.findall(r'#([A-Z]{2,15})', upper)
    for t in hash_tickers:
        if t not in SKIP_WORDS and len(t) >= 2:
            candidates.add(t)

    # ③ STOCKNAME : description format — e.g. "LALPATHLAB : Cup & Handle" (Sunil style)
    colon_tickers = re.findall(r'(?<!\w)([A-Z]{3,15})\s*:', upper)
    for t in colon_tickers:
        if t not in SKIP_WORDS and len(t) >= 3:
            candidates.add(t)

    # ④ Fallback: plain uppercase words (only if nothing found yet)
    if not candidates:
        plain = re.findall(r'(?<!\w)([A-Z]{3,10})(?!\w)', upper)
        for t in plain:
            if t not in SKIP_WORDS and len(t) >= 3:
                candidates.add(t)

    # ⑤ VALIDATE against real NSE ticker list, if loaded — this is what
    #    actually filters out junk words like DISCLAIMER, TELEGRAM, BUYING etc.
    if VALID_NSE_TICKERS:
        tickers = {t for t in candidates if t in VALID_NSE_TICKERS}
    else:
        # NSE list failed to load this run — fall back to unvalidated (noisier)
        tickers = candidates

    return tickers


# ── DATE PARSING ───────────────────────────────────────────────────────────────
def parse_tweet_date(date_str: str) -> datetime | None:
    """Parse Nitter date strings like 'Jun 25, 2024 · 10:30 AM UTC'"""
    try:
        # Remove the · and time portion, keep date
        date_part = date_str.split("·")[0].strip()
        return datetime.strptime(date_part, "%b %d, %Y")
    except Exception:
        return None


def is_within_days(date_str: str, days: int) -> bool:
    """Check if a tweet date string is within the last N days."""
    dt = parse_tweet_date(date_str)
    if dt is None:
        return True  # If we can't parse, include it
    cutoff = datetime.now() - timedelta(days=days)
    return dt >= cutoff


# ── NITTER SCRAPING ────────────────────────────────────────────────────────────
def fetch_tweets_from_nitter(username: str, days_back: int) -> tuple[List[str], str]:
    """Try each Nitter instance and filter tweets by date.
    Returns (tweets, status_note) where status_note explains failures."""
    errors = []
    for base in NITTER_INSTANCES:
        url = f"{base}/{username}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                tweets = parse_nitter_html(resp.text, days_back)
                if tweets is not None:
                    print(f"  ✓ {base} → {len(tweets)} tweets (last {days_back}d)")
                    return tweets, "ok"
                else:
                    errors.append(f"{base}: 200 but no parseable tweets")
                    # Debug: dump a snippet of the actual HTML so we can fix the regex
                    if "DEBUG_HTML_DUMPED" not in globals():
                        globals()["DEBUG_HTML_DUMPED"] = True
                        snippet = resp.text[:3000]
                        print(f"  🔍 DEBUG HTML SNIPPET from {base}:\n{snippet}\n")
            else:
                errors.append(f"{base}: HTTP {resp.status_code}")
        except Exception as e:
            errors.append(f"{base}: {type(e).__name__}")
        time.sleep(1)
    status = " | ".join(errors)
    print(f"  ✗ ALL mirrors failed for @{username}: {status}")
    return [], status


def parse_nitter_html(html: str, days_back: int) -> List[str] | None:
    """Extract tweet text from Nitter HTML, filtered to last N days."""
    # Extract tweet blocks (content + date together)
    tweet_blocks = re.findall(
        r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>.*?'
        r'<span class="tweet-date"[^>]*>.*?title="([^"]*)"',
        html, re.DOTALL | re.IGNORECASE
    )

    # Fallback: just get content without date filtering
    if not tweet_blocks:
        pattern = re.compile(
            r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE
        )
        raw_tweets = pattern.findall(html)
        if not raw_tweets:
            return None
        cleaned = []
        for raw in raw_tweets[:30]:
            text = clean_html(raw)
            if text:
                cleaned.append(text)
        return cleaned

    # With date filtering
    cleaned = []
    for content, date_str in tweet_blocks:
        if is_within_days(date_str, days_back):
            text = clean_html(content)
            if text:
                cleaned.append(text)

    return cleaned if cleaned else None


# ── TELEGRAM CHANNEL SCRAPING (public preview, no login needed) ────────────────
def fetch_messages_from_telegram_channel(channel: str, days_back: int) -> tuple[List[str], str]:
    """Scrape public posts from a Telegram channel via t.me/s/<channel>."""
    url = f"https://t.me/s/{channel}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            note = f"HTTP {resp.status_code}"
            print(f"  ✗ t.me/s/{channel} → {note}")
            return [], note
        messages = parse_telegram_html(resp.text, days_back)
        print(f"  ✓ t.me/{channel} → {len(messages)} messages (last {days_back}d)")
        return messages, "ok"
    except Exception as e:
        note = f"{type(e).__name__}: {e}"
        print(f"  ✗ t.me/s/{channel} → {note}")
        return [], note


def parse_telegram_html(html: str, days_back: int) -> List[str]:
    """Extract message text + datetime from a t.me/s/<channel> preview page."""
    # Each message block: text + a <time datetime="...">
    blocks = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>.*?'
        r'<time[^>]*datetime="([^"]*)"',
        html, re.DOTALL | re.IGNORECASE
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    cleaned = []
    for content, dt_str in blocks:
        try:
            # ISO format e.g. 2024-06-28T20:38:00+00:00
            msg_dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except Exception:
            msg_dt = None

        if msg_dt is None or msg_dt >= cutoff:
            text = clean_html(content)
            if text:
                cleaned.append(text)

    return cleaned


def clean_html(raw: str) -> str:
    """Strip HTML tags and decode common entities."""
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'&quot;', '"', text)
    return ' '.join(text.split())


# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def send_telegram(message: str):
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
    global VALID_NSE_TICKERS
    print(f"\n{'='*50}")
    print(f"🚀 Twitter Stock Scanner — {datetime.now().strftime('%d %b %Y %I:%M %p IST')}")
    print(f"📅 Scanning last {DAYS_BACK} days")
    print(f"{'='*50}\n")

    # Load real NSE ticker list FIRST so extraction can validate against it
    VALID_NSE_TICKERS = load_nse_tickers()

    date_from = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%d %b")
    date_to   = datetime.now().strftime("%d %b %Y")

    all_tickers: dict[str, Set[str]] = {}
    source_status: dict[str, str] = {}  # source → "ok" / error description

    # ── Twitter/X accounts via Nitter ──────────────────────────────
    for account in TWITTER_ACCOUNTS:
        print(f"📡 Scraping @{account} (Twitter)...")
        tweets, status = fetch_tweets_from_nitter(account, DAYS_BACK)
        tickers = set()
        for tweet in tweets:
            tickers |= extract_tickers(tweet)
        all_tickers[f"𝕏 @{account}"] = tickers
        source_status[f"𝕏 @{account}"] = status
        print(f"   Found tickers: {tickers or 'None'}\n")
        time.sleep(2)

    # ── Telegram channels ───────────────────────────────────────────
    for channel in TELEGRAM_CHANNELS:
        print(f"📡 Scraping t.me/{channel} (Telegram)...")
        messages, status = fetch_messages_from_telegram_channel(channel, DAYS_BACK)
        tickers = set()
        for msg in messages:
            tickers |= extract_tickers(msg)
        all_tickers[f"✈️ t.me/{channel}"] = tickers
        source_status[f"✈️ t.me/{channel}"] = status
        print(f"   Found tickers: {tickers or 'None'}\n")
        time.sleep(2)

    # Build Telegram message
    period_label = f"Last {DAYS_BACK} Days ({date_from} – {date_to})" if DAYS_BACK > 1 else date_to
    lines = [f"📊 <b>Stock Picks — {period_label}</b>\n"]

    total_unique: Set[str] = set()
    has_any = False

    for source, tickers in all_tickers.items():
        if tickers:
            has_any = True
            sorted_tickers = sorted(tickers)
            total_unique |= tickers
            lines.append(f"<b>{source}</b>")
            lines.append("  " + "  |  ".join(f"#{t}" for t in sorted_tickers))
            lines.append("")

    if not has_any:
        lines.append(f"⚠️ No tickers found in last {DAYS_BACK} days.\n")
        lines.append("<b>Diagnostics:</b>")
        for source, status in source_status.items():
            icon = "✅" if status == "ok" else "❌"
            short_status = status[:60] + ("…" if len(status) > 60 else "")
            lines.append(f"{icon} {source}: {short_status}")
    else:
        lines.append("─────────────────────")
        lines.append(f"🔢 <b>Total unique: {len(total_unique)} tickers</b>")
        lines.append("  " + "  ".join(f"#{t}" for t in sorted(total_unique)))
        lines.append("")
        lines.append("📈 <i>Check TradingView watchlist: Twitter Picks</i>")

    message = "\n".join(lines)
    print("📨 Sending to Telegram...")
    print(message)
    send_telegram(message)

    # Save for TradingView updater
    output = {
        "date": date_to,
        "days_back": DAYS_BACK,
        "by_account": {k: list(v) for k, v in all_tickers.items()},
        "all_tickers": sorted(total_unique),
    }
    with open("tickers_today.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\n💾 Saved tickers_today.json")


if __name__ == "__main__":
    main()
