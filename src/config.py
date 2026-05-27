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

    # ------------------------------------------------------------------ #
    # Phase 1 — data ingestion                                           #
    # ------------------------------------------------------------------ #
    # Set to True to open the Alpaca WebSocket feed (requires paid SIP sub)
    use_alpaca_websocket: bool = False
    alpaca_use_sip: bool = False  # False = IEX, True = SIP
    # S3 Partners squeeze divergence minimum gap to trigger
    s3_min_divergence: float = 0.0
    # SimClusters: tweets-per-minute acceleration to flag as "bridging"
    simcluster_min_velocity_delta: float = 2.0
    simcluster_window_minutes: int = 5

    # ------------------------------------------------------------------ #
    # Phase 2 — NLP / signals                                            #
    # ------------------------------------------------------------------ #
    # VIX calm-market reference level for Sentiment-VIX scaling
    vix_reference_level: float = 15.0
    # Non-negative SVC bias constant C; increase to allow slight negative SVC
    svc_bias_c: float = 0.0
    # SBERT narrative clustering
    sbert_n_clusters: int = 8
    # LSTM sequence length (bars)
    lstm_seq_len: int = 20

    # ------------------------------------------------------------------ #
    # Phase 3 — ReAct factor discovery                                   #
    # ------------------------------------------------------------------ #
    react_max_iterations: int = 10
    react_t_stat_hurdle: float = 3.0

    # ------------------------------------------------------------------ #
    # Phase 4 — LightGBM aggregation & multi-agent panel                 #
    # ------------------------------------------------------------------ #
    lgbm_breakout_threshold: float = 0.65
    panel_min_confidence: float = 0.65
    # Enable multi-agent panel debate before execution.
    # Works with GEMINI_API_KEY or GROQ_API_KEY (both free), or rule-based fallback.
    enable_panel_review: bool = False

    # ------------------------------------------------------------------ #
    # Phase 5 — backtesting                                              #
    # ------------------------------------------------------------------ #
    wf_n_folds: int = 5
    wf_embargo_bars: int = 5
    wf_expanding: bool = True
    # Next-day execution fill mode: next_ohlc_avg | next_open | twap_approx
    execution_fill_mode: str = "next_ohlc_avg"

    def __post_init__(self) -> None:
        """Allow GitHub Actions secrets/env vars to tune API pressure safely."""
        int_fields = [
            "wide_scan_limit",
            "deep_scan_limit",
            "max_data_calls_per_run",
            "max_buy_alerts_per_run",
            "max_wait_alerts_per_run",
            "max_new_orders_per_run",
            "react_max_iterations",
            "wf_n_folds",
            "wf_embargo_bars",
            "sbert_n_clusters",
            "lstm_seq_len",
        ]
        for field_name in int_fields:
            env_name = field_name.upper()
            value = os.getenv(env_name)
            if value:
                try:
                    setattr(self, field_name, int(value))
                except ValueError:
                    pass

        float_fields = [
            "lgbm_breakout_threshold",
            "panel_min_confidence",
            "react_t_stat_hurdle",
            "vix_reference_level",
            "svc_bias_c",
            "s3_min_divergence",
        ]
        for field_name in float_fields:
            value = os.getenv(field_name.upper())
            if value:
                try:
                    setattr(self, field_name, float(value))
                except ValueError:
                    pass

        bool_fields = [
            "use_alpaca_websocket",
            "alpaca_use_sip",
            "enable_panel_review",
            "wf_expanding",
        ]
        for field_name in bool_fields:
            value = os.getenv(field_name.upper())
            if value:
                setattr(self, field_name, value.lower() in ("1", "true", "yes"))

        self.max_symbols = max(self.max_symbols, self.wide_scan_limit)


CONFIG = ScannerConfig()
