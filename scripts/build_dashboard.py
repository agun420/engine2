from pathlib import Path
import json

required = [
    Path("docs/index.html"),
    Path("docs/assets/styles.css"),
    Path("docs/assets/app.js"),
    Path("docs/data/signals.json"),
    Path("docs/data/execution.json"),
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    raise SystemExit(f"Missing dashboard files: {missing}")

data = json.loads(Path("docs/data/signals.json").read_text())
for key in ["scanner_name", "schema_version", "updated_at_et", "summary", "signals", "paper_only", "data_health", "market_phase", "market_context", "api_budget", "scanner_mode"]:
    if key not in data:
        raise SystemExit(f"signals.json missing required key: {key}")

if data.get("paper_only") is not True:
    raise SystemExit("paper_only must be true")

for sig in data.get("signals", []):
    for key in ["symbol", "decision", "status", "lifecycle", "action_text", "levels", "opportunity_score", "entry_score", "sector_context", "advanced_breakdown"]:
        if key not in sig:
            raise SystemExit(f"Signal missing required key {key}: {sig}")
    for level_key in ["entry", "better_entry", "stop", "target1", "target2", "risk_reward", "target1_source"]:
        if level_key not in sig["levels"]:
            raise SystemExit(f"Signal levels missing {level_key}: {sig}")

print("Dashboard validation passed.")
