"""Phase 1 — real-time Alpaca WebSocket feed with Level 2 order book."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
_ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
_PAPER_BASE = "wss://stream.data.alpaca.markets/v2/iex"
_LIVE_BASE = "wss://stream.data.alpaca.markets/v2/sip"


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    timestamp: str


@dataclass
class Trade:
    symbol: str
    price: float
    size: int
    timestamp: str


@dataclass
class OrderBookLevel:
    price: float
    size: int


@dataclass
class Level2Snapshot:
    symbol: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)

    def spread(self) -> Optional[float]:
        if self.bids and self.asks:
            return round(self.asks[0].price - self.bids[0].price, 4)
        return None

    def imbalance(self) -> Optional[float]:
        """Bid/ask size imbalance: positive = more buying pressure."""
        total_bid = sum(b.size for b in self.bids[:5])
        total_ask = sum(a.size for a in self.asks[:5])
        denom = total_bid + total_ask
        if denom == 0:
            return None
        return round((total_bid - total_ask) / denom, 4)


class AlpacaWebSocketFeed:
    """
    Connects to Alpaca's real-time WebSocket to stream quotes, trades, and
    Level 2 order book data.

    Usage::

        feed = AlpacaWebSocketFeed(symbols=["AAPL", "GME"], use_sip=True)
        feed.on_quote(lambda q: print(q))
        feed.start()
        ...
        feed.stop()
    """

    def __init__(self, symbols: List[str], use_sip: bool = False) -> None:
        self.symbols = symbols
        self._base_url = _LIVE_BASE if use_sip else _PAPER_BASE
        self._quotes: Dict[str, Quote] = {}
        self._trades: Dict[str, Trade] = {}
        self._order_books: Dict[str, Level2Snapshot] = {}
        self._quote_callbacks: List[Callable[[Quote], None]] = []
        self._trade_callbacks: List[Callable[[Trade], None]] = []
        self._book_callbacks: List[Callable[[Level2Snapshot], None]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def on_quote(self, fn: Callable[[Quote], None]) -> None:
        self._quote_callbacks.append(fn)

    def on_trade(self, fn: Callable[[Trade], None]) -> None:
        self._trade_callbacks.append(fn)

    def on_book(self, fn: Callable[[Level2Snapshot], None]) -> None:
        self._book_callbacks.append(fn)

    def start(self) -> None:
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("AlpacaWebSocketFeed started for %d symbols", len(self.symbols))

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        log.info("AlpacaWebSocketFeed stopped")

    def latest_quote(self, symbol: str) -> Optional[Quote]:
        return self._quotes.get(symbol)

    def latest_trade(self, symbol: str) -> Optional[Trade]:
        return self._trades.get(symbol)

    def order_book(self, symbol: str) -> Optional[Level2Snapshot]:
        return self._order_books.get(symbol)

    # ------------------------------------------------------------------ #
    # Internal asyncio loop                                                #
    # ------------------------------------------------------------------ #

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._stream())

    async def _stream(self) -> None:
        try:
            import websockets  # type: ignore
            import json

            uri = self._base_url
            async with websockets.connect(uri) as ws:
                # Authenticate
                await ws.send(json.dumps({"action": "auth", "key": _ALPACA_KEY, "secret": _ALPACA_SECRET}))
                auth_resp = json.loads(await ws.recv())
                log.debug("Auth response: %s", auth_resp)

                # Subscribe to quotes, trades, and order book
                sub_msg = {
                    "action": "subscribe",
                    "quotes": self.symbols,
                    "trades": self.symbols,
                    "orderbooks": self.symbols,
                }
                await ws.send(json.dumps(sub_msg))

                while self._running:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        messages = json.loads(raw)
                        for msg in (messages if isinstance(messages, list) else [messages]):
                            self._dispatch(msg)
                    except asyncio.TimeoutError:
                        # send heartbeat
                        await ws.send(json.dumps({"action": "ping"}))
        except Exception as exc:  # noqa: BLE001
            log.error("WebSocket error: %s", exc)

    def _dispatch(self, msg: dict) -> None:
        t = msg.get("T")
        if t == "q":  # quote
            q = Quote(
                symbol=msg["S"],
                bid=float(msg.get("bp", 0)),
                ask=float(msg.get("ap", 0)),
                bid_size=int(msg.get("bs", 0)),
                ask_size=int(msg.get("as", 0)),
                timestamp=msg.get("t", ""),
            )
            self._quotes[q.symbol] = q
            for cb in self._quote_callbacks:
                cb(q)
        elif t == "t":  # trade
            tr = Trade(
                symbol=msg["S"],
                price=float(msg.get("p", 0)),
                size=int(msg.get("s", 0)),
                timestamp=msg.get("t", ""),
            )
            self._trades[tr.symbol] = tr
            for cb in self._trade_callbacks:
                cb(tr)
        elif t == "o":  # order book update
            sym = msg["S"]
            book = self._order_books.setdefault(sym, Level2Snapshot(symbol=sym))
            for side_key, target_list in (("b", book.bids), ("a", book.asks)):
                for entry in msg.get(side_key, []):
                    lv = OrderBookLevel(price=float(entry[0]), size=int(entry[1]))
                    target_list.append(lv)
            # Keep top-10 levels sorted
            book.bids.sort(key=lambda x: -x.price)
            book.bids[:] = book.bids[:10]
            book.asks.sort(key=lambda x: x.price)
            book.asks[:] = book.asks[:10]
            for cb in self._book_callbacks:
                cb(book)
