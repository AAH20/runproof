"""Generate a JSON and static HTML passport without external services."""

import argparse
import json
from pathlib import Path

from .engine import build
from .render import render


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an evidence-labeled AI deployment passport")
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--benchmark", action="append", type=Path, default=[], help="Canonical llm-inference-benchmark JSON")
    parser.add_argument("--output", type=Path, default=Path("generated"))
    args = parser.parse_args()
    models = json.loads(args.models.read_text())
    hardware = json.loads(args.hardware.read_text())
    workload = json.loads(args.workload.read_text())
    receipts = [json.loads(p.read_text()) for p in args.benchmark]
    passport = build(models, hardware, workload, receipts)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "passport.json").write_text(json.dumps(passport, indent=2, sort_keys=True) + "\n")
    (args.output / "index.html").write_text(render(passport))
    print(f"Generated {len(passport['candidates'])} candidates in {args.output}; evidence labels preserved")


if __name__ == "__main__":
    main()
