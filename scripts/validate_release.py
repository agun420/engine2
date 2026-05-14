from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    ".github/workflows/scanner.yml",
    "README.md",
    "requirements.txt",

    "src/config.py",
    "src/data.py",
    "src/indicators.py",
    "src/market_context.py",
    "src/models.py",
    "src/scanner.py",
    "src/scoring.py",
    "src/state.py",
    "src/execution.py",
    "src/backtest.py",

    "src/alerts/telegram.py",
    "src/broker/alpaca_paper.py",

    "scripts/run_scanner.py",
    "scripts/build_dashboard.py",
    "scripts/audit_repo.py",
    "scripts/validate_release.py",

    "docs/index.html",
    "docs/assets/app.js",
    "docs/assets/styles.css",
    "docs/data/signals.json",
    "docs/data/execution.json",

    "state/signal_state.json",
    "state/outcomes.json",
    "state/alert_state.json",
    "state/execution_state.json",
    "state/execution_summary.json",

    "tests/test_scoring.py",
]


FORBIDDEN_CACHE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def read_text(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="ignore")


def read_json(path: str) -> dict | list:
    file_path = ROOT / path
    if not file_path.exists():
        raise FileNotFoundError(path)

    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_cache_artifacts() -> list[str]:
    artifacts: list[str] = []

    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)

        # Skip Git internals
        if ".git" in rel.parts:
            continue

        if path.is_dir() and path.name in FORBIDDEN_CACHE_NAMES:
            artifacts.append(str(rel))

        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            artifacts.append(str(rel))

    return artifacts


def validate_required_files(errors: list[str]) -> None:
    for file_path in REQUIRED_FILES:
        if not (ROOT / file_path).exists():
            errors.append(f"missing required file: {file_path}")


def validate_no_cache_artifacts(errors: list[str]) -> None:
    artifacts = find_cache_artifacts()
    for artifact in artifacts:
        errors.append(f"cache artifact found: {artifact}")


def validate_workflow(errors: list[str]) -> None:
    workflow = read_text(".github/workflows/scanner.yml")

    required_snippets = [
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
        "WIDE_SCAN_LIMIT",
        "DEEP_SCAN_LIMIT",
        "MAX_DATA_CALLS_PER_RUN",
        "find . -type d",
        "__pycache__",
        ".pytest_cache",
    ]

    for snippet in required_snippets:
        if snippet not in workflow:
            errors.append(f"workflow missing required snippet: {snippet}")


def validate_signals_json(errors: list[str]) -> None:
    try:
        payload = read_json("docs/data/signals.json")
    except Exception as exc:
        errors.append(f"could not read docs/data/signals.json: {exc}")
        return

    if not isinstance(payload, dict):
        errors.append("docs/data/signals.json must be a JSON object")
        return

    required_top_level = [
        "generated_at",
        "paper_only",
        "signals",
    ]

    for key in required_top_level:
        if key not in payload:
            errors.append(f"signals.json missing top-level key: {key}")

    if payload.get("paper_only") is not True:
        errors.append("signals.json must have paper_only=true")

    signals = payload.get("signals", [])
    if not isinstance(signals, list):
        errors.append("signals.json key 'signals' must be a list")
        return

    for idx, signal in enumerate(signals[:10]):
        if not isinstance(signal, dict):
            errors.append(f"signal #{idx} is not an object")
            continue

        required_signal_keys = [
            "symbol",
            "decision",
            "opportunity_score",
            "entry_score",
            "entry",
            "stop_loss",
            "target_1",
            "target_2",
            "reason",
        ]

        for key in required_signal_keys:
            if key not in signal:
                errors.append(f"signal #{idx} missing key: {key}")

        if "advanced_breakdown" not in signal:
            errors.append(f"signal #{idx} missing advanced_breakdown")

        breakdown = signal.get("advanced_breakdown", {})
        if isinstance(breakdown, dict):
            expected_breakdown_keys = [
                "catalyst",
                "technicals",
                "volume_liquidity",
                "relative_strength",
                "sector_market",
                "risk_quality",
                "execution_timing",
            ]

            for key in expected_breakdown_keys:
                if key not in breakdown:
                    errors.append(f"signal #{idx} advanced_breakdown missing key: {key}")
        else:
            errors.append(f"signal #{idx} advanced_breakdown must be an object")


def validate_execution_json(errors: list[str]) -> None:
    try:
        payload = read_json("docs/data/execution.json")
    except Exception as exc:
        errors.append(f"could not read docs/data/execution.json: {exc}")
        return

    if not isinstance(payload, dict):
        errors.append("docs/data/execution.json must be a JSON object")
        return

    expected_keys = [
        "auto_paper_trade",
        "paper_only",
        "max_new_orders_per_run",
        "max_notional_per_trade",
    ]

    for key in expected_keys:
        if key not in payload:
            errors.append(f"execution.json missing key: {key}")

    if payload.get("paper_only") is not True:
        errors.append("execution.json must have paper_only=true")


def validate_paper_trading_safety(errors: list[str]) -> None:
    execution_py = read_text("src/execution.py")
    alpaca_py = read_text("src/broker/alpaca_paper.py")

    required_execution_snippets = [
        "AUTO_PAPER_TRADE",
        "BUY SETUP",
        "stale",
        "9:35",
        "3:45",
        "MAX_NEW_ORDERS_PER_RUN",
        "MAX_NOTIONAL_PER_TRADE",
        "MIN_ENTRY_SCORE_FOR_ORDER",
    ]

    for snippet in required_execution_snippets:
        if snippet not in execution_py:
            errors.append(f"src/execution.py missing safety snippet: {snippet}")

    required_alpaca_snippets = [
        "paper=True",
        "TradingClient",
        "take_profit",
        "stop_loss",
        "bracket",
    ]

    for snippet in required_alpaca_snippets:
        if snippet not in alpaca_py:
            errors.append(f"src/broker/alpaca_paper.py missing paper safety snippet: {snippet}")

    forbidden_live_snippets = [
        "paper=False",
        "live=True",
    ]

    for snippet in forbidden_live_snippets:
        if snippet in alpaca_py:
            errors.append(f"forbidden live-trading snippet found in Alpaca broker: {snippet}")


def validate_telegram_alerts(errors: list[str]) -> None:
    telegram_py = read_text("src/alerts/telegram.py")

    required_snippets = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "BUY SETUP",
        "WAIT",
        "entry",
        "stop",
        "target",
        "reason",
    ]

    for snippet in required_snippets:
        if snippet not in telegram_py:
            errors.append(f"src/alerts/telegram.py missing alert snippet: {snippet}")


def validate_dashboard_assets(errors: list[str]) -> None:
    index_html = read_text("docs/index.html")
    app_js = read_text("docs/assets/app.js")
    styles_css = read_text("docs/assets/styles.css")

    required_dashboard_snippets = [
        "BUY SETUP",
        "WAIT",
        "WATCH ONLY",
        "AVOID",
    ]

    combined = f"{index_html}\n{app_js}\n{styles_css}"

    for snippet in required_dashboard_snippets:
        if snippet not in combined:
            errors.append(f"dashboard missing visible decision label: {snippet}")

    advanced_snippets = [
        "Advanced",
        "Catalyst",
        "Technical",
        "Volume",
        "Relative",
        "Sector",
        "Risk",
        "Execution",
    ]

    for snippet in advanced_snippets:
        if snippet not in combined:
            errors.append(f"dashboard missing advanced logic label: {snippet}")


def validate_release() -> list[str]:
    errors: list[str] = []

    validate_required_files(errors)
    validate_no_cache_artifacts(errors)
    validate_workflow(errors)
    validate_signals_json(errors)
    validate_execution_json(errors)
    validate_paper_trading_safety(errors)
    validate_telegram_alerts(errors)
    validate_dashboard_assets(errors)

    return errors


if __name__ == "__main__":
    release_errors = validate_release()

    if release_errors:
        for error in release_errors:
            print(f"Release validation failed: {error}")
        raise SystemExit(1)

    print("Release validation passed.")
