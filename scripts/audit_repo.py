from __future__ import annotations

from pathlib import Path

FORBIDDEN_PATTERNS = [
    "live=True",
    "paper=False",
]

failures = []
for path in Path(".").rglob("*"):
    if not path.is_file():
        continue
    if path.suffix in {".pyc", ".pyo"} or "__pycache__" in str(path) or ".pytest_cache" in str(path):
        failures.append(f"Cache/build artifact should not ship: {path}")
        continue
    if path.name == "audit_repo.py":
        continue
    if path.suffix not in {".py", ".md", ".yml", ".yaml", ".js", ".html", ".css", ".json"}:
        continue
    text = path.read_text(errors="ignore")
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in text:
            failures.append(f"Forbidden live-trading pattern '{pattern}' found in {path}")

broker = Path("src/broker/alpaca_paper.py")
if not broker.exists():
    failures.append("Missing Alpaca paper broker adapter")
else:
    broker_text = broker.read_text()
    if "paper=True" not in broker_text:
        failures.append("Alpaca broker adapter must explicitly use paper=True")
    if "AUTO_PAPER_TRADE" not in broker_text:
        failures.append("Alpaca paper adapter must require AUTO_PAPER_TRADE opt-in")
    if "OrderClass.BRACKET" not in broker_text:
        failures.append("Alpaca paper adapter must use bracket orders")

if failures:
    raise SystemExit("\n".join(failures))
print("Repo audit passed: paper-only broker guardrails verified.")
