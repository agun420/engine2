from __future__ import annotations

import json
from pathlib import Path
import yaml

REQUIRED_FILES = [
    "README.md",
    "BOARD_REVIEW.md",
    "requirements.txt",
    ".github/workflows/scanner.yml",
    "src/scanner.py",
    "src/scoring.py",
    "src/state.py",
    "src/backtest.py",
    "src/market_context.py",
    "src/execution.py",
    "src/broker/alpaca_paper.py",
    "src/alerts/telegram.py",
    "scripts/run_scanner.py",
    "scripts/build_dashboard.py",
    "scripts/validate_release.py",
    "docs/index.html",
    "docs/assets/styles.css",
    "docs/assets/app.js",
    "docs/data/signals.json",
    "docs/data/execution.json",
    "state/signal_state.json",
    "state/outcomes.json",
    "state/execution_state.json",
    "state/alert_state.json",
]

missing = [p for p in REQUIRED_FILES if not Path(p).exists()]
if missing:
    raise SystemExit(f"Release validation failed. Missing files: {missing}")

payload = json.loads(Path("docs/data/signals.json").read_text())
for key in ["scanner_name", "schema_version", "updated_at_et", "summary", "signals", "paper_only", "data_health", "market_phase", "market_context", "api_budget", "scanner_mode"]:
    if key not in payload:
        raise SystemExit(f"signals.json missing required key: {key}")
if payload.get("paper_only") is not True:
    raise SystemExit("Release validation failed: paper_only must be true")

for sig in payload.get("signals", []):
    for key in ["symbol", "decision", "status", "lifecycle", "action_text", "levels", "opportunity_score", "entry_score", "sector_context", "advanced_breakdown"]:
        if key not in sig:
            raise SystemExit(f"Signal missing required key {key}: {sig}")
    levels = sig["levels"]
    for level_key in ["entry", "better_entry", "stop", "target1", "target2", "risk_reward", "target1_source"]:
        if level_key not in levels:
            raise SystemExit(f"Signal levels missing {level_key}: {sig}")
    if sig["decision"] == "BUY SETUP" and levels["risk_reward"] < 1.55:
        raise SystemExit(f"BUY SETUP with weak RR found: {sig['symbol']}")
    adv = sig.get("advanced_breakdown", {})
    if "factors" not in adv or "composite" not in adv:
        raise SystemExit(f"Signal missing advanced factor details: {sig['symbol']}")
    for factor in ["catalyst", "technical", "volume_liquidity", "relative_strength", "sector_market", "risk_quality", "execution_timing"]:
        if factor not in adv.get("factors", {}):
            raise SystemExit(f"Signal missing advanced factor {factor}: {sig['symbol']}")

workflow = yaml.safe_load(Path(".github/workflows/scanner.yml").read_text())
job = workflow["jobs"]["run-scanner"]
if "concurrency" not in workflow:
    raise SystemExit("Workflow missing concurrency guard")
if job.get("timeout-minutes", 0) < 1:
    raise SystemExit("Workflow missing job timeout")
steps_text = Path(".github/workflows/scanner.yml").read_text()
for required in ["pytest -q", "python scripts/run_scanner.py", "python scripts/build_dashboard.py", "python scripts/validate_release.py"]:
    if required not in steps_text:
        raise SystemExit(f"Workflow missing validation step: {required}")

if "find . -type d" not in steps_text or "__pycache__" not in steps_text:
    raise SystemExit("Workflow cleanup must remove nested __pycache__ folders with find")
if "MAX_DATA_CALLS_PER_RUN" not in steps_text:
    raise SystemExit("Workflow missing MAX_DATA_CALLS_PER_RUN API budget env")

for env_name in ["AUTO_PAPER_TRADE", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MAX_NOTIONAL_PER_TRADE"]:
    if env_name not in steps_text:
        raise SystemExit(f"Workflow missing execution/alert env: {env_name}")

execution_payload = json.loads(Path("docs/data/execution.json").read_text())
if execution_payload.get("paper_only") is not True:
    raise SystemExit("execution.json must stay paper_only=true")

# Source-level release gates for the 100/100 blocker fixes.
scanner_text = Path("src/scanner.py").read_text()
if "TRIMMED_TO_BUDGET" not in scanner_text or "active_tracked" not in scanner_text:
    raise SystemExit("Scanner must enforce API budget and refresh active tracked signals")
broker_text = Path("src/broker/alpaca_paper.py").read_text()
for required in ["is_safe_paper_execution_window", "stale data guard", "9:35 AM ET", "3:45 PM ET"]:
    if required not in broker_text:
        raise SystemExit(f"Paper broker missing execution safety guard: {required}")
app_text = Path("docs/assets/app.js").read_text()
if "Advanced Logic Breakdown" not in app_text or "makeAdvancedBreakdown" not in app_text:
    raise SystemExit("Dashboard must include an advanced logic breakdown panel")
scoring_text = Path("src/scoring.py").read_text()
if "build_advanced_breakdown" not in scoring_text or "volume_liquidity" not in scoring_text:
    raise SystemExit("Scoring must preserve advanced factor breakdown logic")

execution_text = Path("src/execution.py").read_text()
for required in ["wait_alerts_attempted_this_run", "wait_alerts_suppressed_this_run"]:
    if required not in execution_text:
        raise SystemExit(f"Execution summary missing clear WAIT alert count: {required}")

print("Release validation passed.")


for bad in ["__pycache__", ".pytest_cache"]:
    if any(bad in str(p) for p in Path(".").rglob("*")):
        raise SystemExit(f"Release validation failed: cache artifact found: {bad}")

print("No cache artifacts found.")
