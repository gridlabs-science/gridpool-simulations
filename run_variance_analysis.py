#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gridpool_sim.variance import analyze_variance_scenario
from gridpool_sim.variance_reporting import write_variance_reports


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze GridPool payout variance against solo and FPPS benchmarks."
    )
    parser.add_argument("--scenario", required=True, type=Path, help="Path to a JSON scenario file.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated reports.")
    parser.add_argument("--quick", action="store_true", help="Reduce the scenario for a smoke run.")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.quick:
        scenario = quicken(scenario)

    results = analyze_variance_scenario(scenario)
    write_variance_reports(args.out_dir, scenario, results)
    print(f"Wrote payout variance report to {args.out_dir / 'report.md'}")
    return 0


def quicken(scenario: dict) -> dict:
    clone = copy.deepcopy(scenario)
    clone["name"] = f"{clone.get('name', 'scenario')}_quick"
    clone["miners"] = clone.get("miners", [])[:2]
    clone["team_multipliers"] = [value for value in clone.get("team_multipliers", []) if value in {10, 100, 300}]
    clone["total_slots"] = [value for value in clone.get("total_slots", []) if value in {30, 300}]
    return clone


if __name__ == "__main__":
    raise SystemExit(main())
