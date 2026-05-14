from __future__ import annotations

import json
from pathlib import Path

from src.scanner import scan, write_outputs
from src.execution import process_buy_setups


if __name__ == "__main__":
    payload = scan()
    write_outputs(payload)
    execution_summary = process_buy_setups(payload)
    Path("state/execution_summary.json").write_text(json.dumps(execution_summary, indent=2, sort_keys=True))
    Path("docs/data/execution.json").write_text(json.dumps(execution_summary, indent=2, sort_keys=True))
    print(json.dumps({
        "scanner": payload["summary"],
        "execution": {
            "buy_setup_count": execution_summary["buy_setup_count"],
            "orders_submitted_this_run": execution_summary["orders_submitted_this_run"],
            "paper_only": True,
        },
    }, indent=2, sort_keys=True))
