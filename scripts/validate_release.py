from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    ".github/workflows/scanner.yml",
    "README.md",
    "requirements.txt",

    "src/config.py",
    "src/data.py",
    "src/indicators.py",
    "src/models.py",
    "src/scanner.py",
    "src/scoring.py",
    "src/state.py",

    "scripts/run_scanner.py",
    "scripts/build_dashboard.py",
    "scripts/audit_repo.py",
    "scripts/validate_release.py",

    "docs/index.html",
    "docs/assets/app.js",
    "docs/assets/styles.css",
    "docs/data/signals.json",

    "tests/test_scoring.py",
]

OPTIONAL_BUT_EXPECTED_FILES = [
    "src/execution.py",
    "src/broker/alpaca_paper.py",
    "src/alerts/telegram.py",
    "src/backtest.py",
    "src/market_context.py",
    "docs/data/execution.json",
    "state/signal_state.json",
    "state/outcomes.json",
    "state/alert_state.json",
    "state/execution_state.json",
    "state/execution_summary.json",
]

FORBIDDEN_CACHE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def path_exists(path: str) -> bool:
    return (ROOT / path).exists()


def read_text(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="ignore")


def read_json(path: str) -> Any:
    file_path = ROOT / path
    if not file_path.exists():
        raise FileNotFoundError(path)
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_cache_artifacts() -> list[str]:
    artifacts: list[str] = []

    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)

        if ".git" in rel.parts:
            continue

        if path.is_dir() and path.name in FORBIDDEN_CACHE_NAMES:
            artifacts.append(str(rel))

        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            artifacts.append(str(rel))

    return artifacts


def first_present(obj: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in obj and obj.get(key) not in (None, ""):
            return obj.get(key)
    return None


def normalize_signal(signal: dict[str, Any]) -> dict[str, Any]:
    levels = signal.get("levels") if isinstance(signal.get("levels"), dict) else {}
    advanced = signal.get("advanced_breakdown")
    if not isinstance(advanced, dict):
        advanced = signal.get("breakdown")
    if not isinstance(advanced, dict):
        advanced = signal.get("scores")
    if not isinstance(advanced, dict):
        advanced = {}

    return {
        "symbol": first_present(signal, ["symbol", "ticker", "name"]),
        "decision": first_present(signal, ["decision", "status", "action", "label"]),
        "opportunity_score": first_present(
            signal,
            ["opportunity_score", "score", "total_score", "conviction_score"],
        ),
        "entry_score": first_present(
            signal,
            ["entry_score", "trade_score", "setup_score", "execution_score"],
        ),
        "entry": first_present(signal, ["entry", "entry_goal", "entry_area", "buy_zone"])
        or first_present(levels, ["entry", "entry_goal", "entry_area", "buy_zone"]),
        "stop_loss": first_present(signal, ["stop_loss", "stop", "sl"])
        or first_present(levels, ["stop_loss", "stop", "sl"]),
        "target_1": first_present(signal, ["target_1", "target1", "tp1", "sell_target_1"])
        or first_present(levels, ["target_1", "target1", "tp1", "sell_target_1"]),
        "target_2": first_present(signal, ["target_2", "target2", "tp2", "sell_target_2"])
        or first_present(levels, ["target_2", "target2", "tp2", "sell_target_2"]),
        "reason": first_present(signal, ["reason", "why", "notes", "summary"]),
        "advanced_breakdown": advanced,
    }


def validate_required_files(errors: list[str], warnings: list[str]) -> None:
    for file_path in REQUIRED_FILES:
        if not path_exists(file_path):
            errors.append(f"missing required file: {file_path}")

    for file_path in OPTIONAL_BUT_EXPECTED_FILES:
        if not path_exists(file_path):
            warnings.append(f"optional expected file missing: {file_path}")


def validate_no_cache_artifacts(errors: list[str]) -> None:
    for artifact in find_cache_artifacts():
        errors.append(f"cache artifact found: {artifact}")


def validate_workflow(errors: list[str], warnings: list[str]) -> None:
    workflow = read_text(".github/workflows/scanner.yml")

    hard_required = [
        "concurrency:",
        "timeout-minutes:",
        "pytest -q",
        "python scripts/audit_repo.py",
        "python scripts/run_scanner.py",
        "python scripts/build_dashboard.py --validate-only",
        "python scripts/validate_release.py",
        "AUTO_PAPER_TRADE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "find . -type d",
        "__pycache__",
        ".pytest_cache",
    ]

    for snippet in hard_required:
        if snippet not in workflow:
            errors.append(f"workflow missing required snippet: {snippet}")

    soft_required = [
        "WIDE_SCAN_LIMIT",
        "DEEP_SCAN_LIMIT",
        "MAX_DATA_CALLS_PER_RUN",
        "MAX_BUY_ALERTS_PER_RUN",
        "MAX_WAIT_ALERTS_PER_RUN",
        "MIN_ENTRY_SCORE_FOR_ORDER",
    ]

    for snippet in soft_required:
        if snippet not in workflow:
            warnings.append(f"workflow missing recommended snippet: {snippet}")


def validate_signals_json(errors: list[str], warnings: list[str]) -> None:
    try:
        payload = read_json("docs/data/signals.json")
    except Exception as exc:
        errors.append(f"could not read docs/data/signals.json: {exc}")
        return

    if not isinstance(payload, dict):
        errors.append("docs/data/signals.json must be a JSON object")
        return

    timestamp = first_present(
        payload,
        ["generated_at", "updated_at", "last_updated", "timestamp", "as_of"],
    )
    if timestamp is None:
        warnings.append(
            "signals.json missing timestamp key; accepted for now, but add generated_at later"
        )

    if "paper_only" in payload and payload.get("paper_only") is not True:
        errors.append("signals.json paper_only must be true when present")

    signals = payload.get("signals")
    if signals is None:
        signals = payload.get("picks")
    if signals is None:
        signals = payload.get("opportunities")
    if signals is None:
        signals = payload.get("rows")

    if signals is None:
        errors.append("signals.json missing signals/picks/opportunities/rows list")
        return

    if not isinstance(signals, list):
        errors.append("signals list must be a list")
        return

    for idx, raw_signal in enumerate(signals[:10]):
        if not isinstance(raw_signal, dict):
            errors.append(f"signal #{idx} is not an object")
            continue

        signal = normalize_signal(raw_signal)

        if not signal["symbol"]:
            errors.append(f"signal #{idx} missing symbol/ticker")

        if not signal["decision"]:
            warnings.append(f"signal #{idx} missing decision/status/action")

        if signal["opportunity_score"] is None:
            warnings.append(f"signal #{idx} missing opportunity score")

        if signal["entry_score"] is None:
            warnings.append(f"signal #{idx} missing entry score")

        missing_level_keys = [
            key
            for key in ["entry", "stop_loss", "target_1", "target_2"]
            if signal[key] is None
        ]

        if missing_level_keys:
            warnings.append(
                f"signal #{idx} missing level keys {missing_level_keys}; accepted for legacy output"
            )

        if signal["reason"] is None:
            warnings.append(f"signal #{idx} missing reason; accepted for legacy output")

        breakdown = signal["advanced_breakdown"]
        if not breakdown:
            warnings.append(
                f"signal #{idx} missing advanced_breakdown; accepted for legacy output"
            )


def validate_execution_json(errors: list[str], warnings: list[str]) -> None:
    if not path_exists("docs/data/execution.json"):
        warnings.append("execution.json missing; accepted if paper trading is disabled")
        return

    try:
        payload = read_json("docs/data/execution.json")
    except Exception as exc:
        errors.append(f"could not read docs/data/execution.json: {exc}")
        return

    if not isinstance(payload, dict):
        errors.append("docs/data/execution.json must be a JSON object")
        return

    if "paper_only" in payload and payload.get("paper_only") is not True:
        errors.append("execution.json paper_only must be true when present")

    recommended = [
        "auto_paper_trade",
        "max_new_orders_per_run",
        "max_notional_per_trade",
    ]

    for key in recommended:
        if key not in payload:
            warnings.append(f"execution.json missing recommended key: {key}")


def validate_paper_trading_safety(errors: list[str], warnings: list[str]) -> None:
    execution_py = read_text("src/execution.py")
    alpaca_py = read_text("src/broker/alpaca_paper.py")

    if not execution_py:
        warnings.append("src/execution.py missing; accepted if repo is scanner-only")
    else:
        recommended_execution_snippets = [
            "AUTO_PAPER_TRADE",
            "BUY SETUP",
            "MAX_NEW_ORDERS_PER_RUN",
            "MAX_NOTIONAL_PER_TRADE",
            "MIN_ENTRY_SCORE_FOR_ORDER",
        ]

        for snippet in recommended_execution_snippets:
            if snippet not in execution_py:
                warnings.append(f"src/execution.py missing recommended safety snippet: {snippet}")

        stale_markers = ["stale", "data_age", "freshness"]
        if not any(marker in execution_py for marker in stale_markers):
            warnings.append("src/execution.py missing stale-data guard marker")

        market_time_markers = ["9:35", "3:45", "market_hours", "safe_market"]
        if not any(marker in execution_py for marker in market_time_markers):
            warnings.append("src/execution.py missing market-hours guard marker")

    if not alpaca_py:
        warnings.append("src/broker/alpaca_paper.py missing; accepted if paper trading is disabled")
    else:
        required_alpaca_snippets = [
            "paper=True",
            "TradingClient",
        ]

        for snippet in required_alpaca_snippets:
            if snippet not in alpaca_py:
                errors.append(f"src/broker/alpaca_paper.py missing paper safety snippet: {snippet}")

        recommended_alpaca_snippets = [
            "take_profit",
            "stop_loss",
            "bracket",
        ]

        for snippet in recommended_alpaca_snippets:
            if snippet not in alpaca_py:
                warnings.append(f"src/broker/alpaca_paper.py missing recommended order snippet: {snippet}")

        forbidden_live_snippets = [
            "paper=False",
            "live=True",
        ]

        for snippet in forbidden_live_snippets:
            if snippet in alpaca_py:
                errors.append(f"forbidden live-trading snippet found in Alpaca broker: {snippet}")


def validate_telegram_alerts(errors: list[str], warnings: list[str]) -> None:
    telegram_py = read_text("src/alerts/telegram.py")

    if not telegram_py:
        warnings.append("src/alerts/telegram.py missing; accepted if Telegram alerts are disabled")
        return

    recommended_snippets = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BUY SETUP",
        "WAIT",
        "entry",
        "stop",
        "target",
        "reason",
    ]

    for snippet in recommended_snippets:
        if snippet not in telegram_py:
            warnings.append(f"src/alerts/telegram.py missing recommended alert snippet: {snippet}")


def validate_dashboard_assets(errors: list[str], warnings: list[str]) -> None:
    index_html = read_text("docs/index.html")
    app_js = read_text("docs/assets/app.js")
    styles_css = read_text("docs/assets/styles.css")

    combined = f"{index_html}\n{app_js}\n{styles_css}"

    decision_labels = ["BUY SETUP", "WAIT", "WATCH ONLY", "AVOID"]
    for label in decision_labels:
        if label not in combined:
            warnings.append(f"dashboard missing recommended decision label: {label}")

    advanced_labels = [
        "Advanced",
        "Catalyst",
        "Technical",
        "Volume",
        "Relative",
        "Sector",
        "Risk",
        "Execution",
    ]

    for label in advanced_labels:
        if label not in combined:
            warnings.append(f"dashboard missing recommended advanced logic label: {label}")


def validate_release() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    validate_required_files(errors, warnings)
    validate_no_cache_artifacts(errors)
    validate_workflow(errors, warnings)
    validate_signals_json(errors, warnings)
    validate_execution_json(errors, warnings)
    validate_paper_trading_safety(errors, warnings)
    validate_telegram_alerts(errors, warnings)
    validate_dashboard_assets(errors, warnings)

    return errors, warnings


if __name__ == "__main__":
    release_errors, release_warnings = validate_release()

    for warning in release_warnings:
        print(f"Release validation warning: {warning}")

    if release_errors:
        for error in release_errors:
            print(f"Release validation failed: {error}")
        raise SystemExit(1)

    print("Release validation passed.")
