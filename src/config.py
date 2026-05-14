from dataclasses import dataclass, field
from typing import List
import os


@dataclass
class ScannerConfig:
    """Conservative research-only scanner settings.

    The package is intentionally paper-only. It creates beginner decision cards,
    not broker orders. BUY SETUP means a setup passed the rules and still needs
    human chart review.
    """

    universe: List[str] = field(default_factory=lambda: [
        # Mega-cap / liquid tech
        "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "GOOG",
        "NFLX", "AVGO", "ORCL", "CRM", "ADBE", "INTC", "MU", "QCOM", "ARM",
        "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MRVL", "SMCI", "DELL", "HPE",
        # AI / software / cyber
        "PLTR", "SNOW", "NET", "CRWD", "PANW", "DDOG", "MDB", "ZS", "OKTA",
        "NOW", "SHOP", "UBER", "DASH", "ABNB", "ROKU", "RBLX", "PATH", "AI",
        # Retail / consumer / travel
        "WMT", "TGT", "COST", "HD", "LOW", "NKE", "LULU", "SBUX", "MCD",
        "CMG", "DIS", "CCL", "RCL", "NCLH", "DKNG", "MGM", "WYNN", "CELH",
        # Fintech / crypto / brokers
        "JPM", "BAC", "WFC", "C", "GS", "MS", "V", "MA", "PYPL", "SQ",
        "COIN", "HOOD", "MARA", "RIOT", "CLSK", "MSTR",
        # EV / autos / China ADRs
        "RIVN", "LCID", "F", "GM", "NIO", "LI", "XPEV", "BABA", "JD", "PDD",
        "BIDU", "TME", "BILI", "BEKE",
        # Healthcare / biotech liquid movers
        "LLY", "UNH", "MRK", "PFE", "JNJ", "ABBV", "GILD", "REGN", "MRNA",
        "BNTX", "NVAX", "VKTX", "RXRX", "SOUN", "TEM", "IONQ", "QBTS",
        # Industrials / energy / materials
        "CAT", "DE", "GE", "BA", "LMT", "XOM", "CVX", "OXY", "SLB", "HAL",
        "FCX", "NEM", "CLF", "X", "AA",
        # ETFs / market proxies and high-volume names
        "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY",
        "XLI", "XLC", "ARKK", "SOXL", "TQQQ", "SQQQ", "UVXY",
        # Additional momentum / small-mid cap watch names
        "UPST", "CVNA", "AFRM", "SOFI", "LC", "OPEN", "RUN", "ENPH", "SEDG",
        "WBD", "PARA", "GME", "AMC", "CHWY", "ETSY", "FSLR", "ANET", "FTNT",
        "CAVA", "ARMK", "ELF", "ONON", "U", "TWLO", "DOCU", "SPOT", "PINS",
        "SNAP", "LYFT", "BROS", "TOST", "HIMS", "NU", "APP", "GTLB"
    ])

    # Middle-ground API-safe coverage.
    # Wide scan checks more symbols with lightweight 5m data, then deep scan applies
    # full scoring only to the best names. This avoids burning free APIs while
    # reducing missed opportunities.
    scan_interval_minutes: int = 10
    wide_scan_limit: int = 150
    deep_scan_limit: int = 40
    max_symbols: int = 150  # backwards-compatible cap for full universe slicing
    top_n: int = 20

    # API budget guard
    api_budget_mode: str = "middle_ground"
    max_data_calls_per_run: int = 90
    stop_on_rate_limit: bool = True
    rate_limit_cooldown_minutes: int = 20

    # Alert / execution caps
    max_buy_alerts_per_run: int = 5
    max_wait_alerts_per_run: int = 3
    max_new_orders_per_run: int = 1


    # Hard filters
    min_price: float = 3.00
    max_price: float = 900.00
    min_avg_volume: int = 750_000
    min_dollar_volume: float = 20_000_000
    max_estimated_spread_pct: float = 0.65

    # Signal rules
    buy_min_opportunity_score: int = 74
    buy_min_entry_score: int = 80
    watch_min_opportunity_score: int = 55
    max_chase_risk_for_buy: str = "MEDIUM"
    max_vwap_extension_pct_for_buy: float = 4.25
    min_risk_reward_for_buy: float = 1.55

    # Levels
    atr_stop_mult: float = 1.10
    wait_pullback_atr_mult: float = 0.55
    max_stop_pct: float = 0.08

    # Outcome / validation
    signal_ttl_minutes: int = 90
    outcome_lookback_limit: int = 250
    default_time_to_expire_minutes: int = 120

    # Data freshness warning
    stale_data_minutes: int = 20

    def __post_init__(self) -> None:
        """Allow GitHub Actions secrets/env vars to tune API pressure safely."""
        int_fields = [
            "wide_scan_limit",
            "deep_scan_limit",
            "max_data_calls_per_run",
            "max_buy_alerts_per_run",
            "max_wait_alerts_per_run",
            "max_new_orders_per_run",
        ]
        for field_name in int_fields:
            env_name = field_name.upper()
            value = os.getenv(env_name)
            if value:
                try:
                    setattr(self, field_name, int(value))
                except ValueError:
                    pass
        self.max_symbols = max(self.max_symbols, self.wide_scan_limit)


CONFIG = ScannerConfig()
