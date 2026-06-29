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

from gridpool_sim.network import NetworkLatencySimulator, relay_profiles_from_config
from gridpool_sim.network_reporting import write_network_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GridPool network latency simulations.")
    parser.add_argument("--scenario", required=True, type=Path, help="Path to a JSON scenario file.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated reports.")
    parser.add_argument("--quick", action="store_true", help="Reduce blocks and replications for a smoke run.")
    args = parser.parse_args()

    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.quick:
        scenario = quicken(scenario)

    base_seed = int(scenario.get("random_seed", 1024))
    replications = int(scenario.get("replications", 1))
    results = []
    for profile_index, profile in enumerate(relay_profiles_from_config(scenario)):
        for replication in range(replications):
            seed = base_seed + (profile_index * 100_000) + replication
            simulator = NetworkLatencySimulator(scenario, profile, seed)
            results.append(simulator.run())

    write_network_reports(args.out_dir, scenario, results)
    print(f"Wrote network latency report to {args.out_dir / 'report.md'}")
    return 0


def quicken(scenario: dict) -> dict:
    clone = copy.deepcopy(scenario)
    clone["name"] = f"{clone.get('name', 'scenario')}_quick"
    clone["blocks"] = min(int(clone.get("blocks", 500)), 250)
    clone["replications"] = min(int(clone.get("replications", 1)), 2)
    clone["node_count"] = min(int(clone.get("node_count", 12)), 12)
    clone["peer_degree"] = min(int(clone.get("peer_degree", 4)), max(2, clone["node_count"] - 1))
    clone["shares_per_network_block_at_full_team"] = min(
        float(clone.get("shares_per_network_block_at_full_team", 120)),
        120.0,
    )
    return clone


if __name__ == "__main__":
    raise SystemExit(main())

