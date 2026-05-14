# Elite Scanner 100/100

Beginner-friendly stock scanner with market context, signal lifecycle tracking, outcome memory, Telegram alerts, and optional Alpaca **paper-only** auto trading.

This repo is built for research and paper testing. It is not financial advice and it does not support live trading.

## What it does

- Uses a middle-ground two-stage scanner: wide scan up to 150 symbols, then deep scan the top 40.
- Scores each ticker with two separate scores:
  - **Opportunity Score:** should this stock be watched?
  - **Entry Score:** is it actually buyable right now?
- Shows simple decisions:
  - **BUY SETUP**
  - **WAIT**
  - **WATCH ONLY**
  - **AVOID**
- Shows beginner levels:
  - entry goal
  - better entry
  - stop loss
  - target 1
  - target 2
  - risk/reward
  - reason
- Preserves advanced scanner logic with an expandable dashboard panel:
  - catalyst
  - technicals
  - volume/liquidity
  - relative strength
  - sector/market context
  - risk quality
  - execution timing
- Sends Telegram alerts when a new BUY SETUP appears. It can also send limited WAIT alerts.
- Can submit an Alpaca **paper** bracket order when explicitly enabled.
- Tracks signal outcomes through target, stop, expiration, or end-of-day close.
- Publishes a GitHub Pages dashboard from `/docs`.

## Safety rules

Auto paper trading is off by default.

The paper trading layer only runs when all of this is true:

```text
AUTO_PAPER_TRADE=true
ALPACA_API_KEY exists
ALPACA_SECRET_KEY exists
signal decision = BUY SETUP
chase risk = LOW or MEDIUM
entry score >= 80
valid entry, stop, and target levels exist
no duplicate processed signal key
```

Orders are submitted with `TradingClient(..., paper=True)` only.

The order is a long-only Alpaca paper **bracket order**:

```text
market buy
attached take-profit at target 1
attached stop-loss at stop loss
```

Default risk and API controls:

```text
SCAN_INTERVAL = every 10 minutes during regular market hours
WIDE_SCAN_LIMIT = 150
DEEP_SCAN_LIMIT = 40
MAX_BUY_ALERTS_PER_RUN = 5
MAX_WAIT_ALERTS_PER_RUN = 3
MAX_NOTIONAL_PER_TRADE = 2000
MAX_NEW_ORDERS_PER_RUN = 1
whole shares only
no live trading adapter included
```

The rule is: **scan wide, trade narrow.** The engine can look across more names, but paper orders remain capped and strict.

## GitHub setup

1. Create a new GitHub repo.
2. Upload all files from this package.
3. Go to **Settings > Pages**.
4. Set Pages source to:

```text
Branch: main
Folder: /docs
```

5. Go to **Actions**.
6. Run **Elite Scanner 100** manually once.

## Required secrets for Alpaca paper trading

Add these in GitHub:

```text
Settings > Secrets and variables > Actions > New repository secret
```

Required for Alpaca paper orders:

```text
ALPACA_API_KEY
ALPACA_SECRET_KEY
AUTO_PAPER_TRADE
```

Set:

```text
AUTO_PAPER_TRADE=true
```

Optional risk/API settings:

```text
MAX_NOTIONAL_PER_TRADE=2000
MAX_NEW_ORDERS_PER_RUN=1
MAX_BUY_ALERTS_PER_RUN=5
MAX_WAIT_ALERTS_PER_RUN=3
WIDE_SCAN_LIMIT=150
DEEP_SCAN_LIMIT=40
```

If these are not set, the scanner still runs and the dashboard still updates. It just will not place paper orders.

## Telegram bot alerts

Create a Telegram bot with BotFather, then add these GitHub secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

When the scanner finds a new BUY SETUP, Telegram sends:

```text
stock name
price
entry goal
better entry
stop loss
sell target 1
sell target 2
risk/reward
opportunity score
entry score
reason
paper order status
```

## Local run

```bash
python -m pip install -r requirements.txt
PYTHONPATH=. pytest -q
PYTHONPATH=. python scripts/run_scanner.py
PYTHONPATH=. python scripts/build_dashboard.py
PYTHONPATH=. python scripts/validate_release.py
```

## Important note

This is a 100/100 foundation package, not a proven trading edge. The scanner needs several weeks of paper outcomes before the scores should be trusted.

## Middle-ground scanner mode

This package is tuned to reduce missed opportunities without exhausting free APIs:

```text
Every 10 minutes
Wide scan: up to 150 symbols
Deep scan: top 40 ranked names
BUY alerts: max 5 per run
WAIT alerts: max 3 per run
Paper orders: max 1 per run
Trade size: max $2,000 notional by default
```

Wide scan is lightweight and ranks movers. Deep scan does the heavier work: VWAP, ATR, entry, stop, target, risk/reward, chase risk, sector context, and paper-trade eligibility.


## 100/100 release safeguards

This release includes the final pre-release blocker fixes:

- Recursive GitHub Actions cache cleanup before repo audit.
- API budget enforcement using `MAX_DATA_CALLS_PER_RUN`.
- Open tracked BUY/WAIT signals are refreshed before new candidates.
- Alpaca paper orders are blocked on stale data.
- Alpaca paper orders are blocked outside 9:35 AM-3:45 PM ET, Monday-Friday.
- WAIT Telegram alert counts are separated into attempted, sent, and suppressed.
- Release validation checks that these safeguards stay in place.

For the middle-ground setup, keep these defaults first:

```env
WIDE_SCAN_LIMIT=150
DEEP_SCAN_LIMIT=40
MAX_DATA_CALLS_PER_RUN=90
MAX_BUY_ALERTS_PER_RUN=5
MAX_WAIT_ALERTS_PER_RUN=3
MAX_NEW_ORDERS_PER_RUN=1
MAX_NOTIONAL_PER_TRADE=2000
```

Paper trading remains opt-in only:

```env
AUTO_PAPER_TRADE=true
```

No live trading adapter is included.


## Simple view + advanced view

The dashboard now keeps both layers:

```text
Simple View = BUY SETUP / WAIT / WATCH ONLY / AVOID with entry, stop, and targets.
Advanced View = factor breakdown for catalyst, technicals, volume/liquidity, relative strength, sector/market, risk quality, and execution timing.
```

This avoids sacrificing scanner logic while keeping the main dashboard beginner-friendly.
