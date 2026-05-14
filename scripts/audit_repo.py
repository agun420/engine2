from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
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

FORBIDDEN_LIVE_TRADING_PATTERNS = [
    "paper=False",
    "live=True",
]

# These files are allowed to contain forbidden strings as text because they are
# validating that live-trading patterns do not exist in the real engine.
LIVE_PATTERN_SCAN_EXCLUDE = {
    "scripts/audit_repo.py",
    "scripts/validate_release.py",
}

# We only need to scan actual runtime/source files for live-trading risk.
LIVE_PATTERN_SCAN_DIRS = {
    "src",
    ".github",
}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def check_required_paths(errors: list[str]) -> None:
    for required in REQUIRED_PATHS:
        if not (ROOT / required).exists():
            errors.append(f"Missing required path: {required}")


def check_cache_artifacts(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        relative = rel(path)

        if ".git/" in relative or relative == ".git":
            continue

        if path.is_dir() and path.name in FORBIDDEN_CACHE_NAMES:
            errors.append(f"Cache artifact found: {relative}")

        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            errors.append(f"Python bytecode artifact found: {relative}")


def should_scan_for_live_patterns(path: Path) -> bool:
    relative = rel(path)

    if relative in LIVE_PATTERN_SCAN_EXCLUDE:
        return False

    if not path.is_file():
        return False

    if path.suffix not in {".py", ".yml", ".yaml"}:
        return False

    first_part = relative.split("/", 1)[0]
    return first_part in LIVE_PATTERN_SCAN_DIRS


def check_forbidden_live_trading_patterns(errors: list[str]) -> None:
    for path in ROOT.rglob("*"):
        if not should_scan_for_live_patterns(path):
            continue

        text = read_text(path)
        relative = rel(path)

        for pattern in FORBIDDEN_LIVE_TRADING_PATTERNS:
            if pattern in text:
                errors.append(
                    f"Forbidden live-trading pattern '{pattern}' found in {relative}"
                )


def check_paper_broker_safety(errors: list[str]) -> None:
    broker_path = ROOT / "src/broker/alpaca_paper.py"

    if not broker_path.exists():
        errors.append("Missing Alpaca paper broker file: src/broker/alpaca_paper.py")
        return

    text = read_text(broker_path)

    required = [
        "TradingClient",
        "paper=True",
        "bracket",
        "take_profit",
        "stop_loss",
    ]

    for item in required:
        if item not in text:
            errors.append(f"Alpaca paper broker missing required safety marker: {item}")


def check_workflow_safety(errors: list[str]) -> None:
    workflow_path = ROOT / ".github/workflows/scanner.yml"

    if not workflow_path.exists():
        errors.append("Missing workflow: .github/workflows/scanner.yml")
        return

    text = read_text(workflow_path)

    required = [
        "concurrency:",
        "timeout-minutes:",
        "AUTO_PAPER_TRADE",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "pytest -q",
        "python scripts/run_scanner.py",
        "python scripts/build_dashboard.py --validate-only",
        "python scripts/validate_release.py",
        "find . -type d",
        "__pycache__",
        ".pytest_cache",
    ]

    for item in required:
        if item not in text:
            errors.append(f"Workflow missing required marker: {item}")


def audit_repo() -> list[str]:
    errors: list[str] = []

    check_required_paths(errors)
    check_cache_artifacts(errors)
    check_forbidden_live_trading_patterns(errors)
    check_paper_broker_safety(errors)
    check_workflow_safety(errors)

    return errors


if __name__ == "__main__":
    audit_errors = audit_repo()

    if audit_errors:
        for error in audit_errors:
            print(error)
        raise SystemExit(1)

    print("Repo audit passed.")
