#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

JOBS=4
HEARTBEAT=60

usage() {
  cat <<'EOF'
Usage: run_incentive_research_batch.sh [--jobs N] [--heartbeat-seconds N]

Runs the next GridPool incentive-modeling batch:

- universal pool-hopping: what happens if every miner tries to hop?
- physical-scale solo hopping: 100 PH, 300 PH, 1 EH, 3 EH miners on 1-10 EH teams
- Bitcoin fee sensitivity: pool hopping and block withholding under low/high fees
- snapshot-policy comparison: current paid-once reserve vs old clear-each-Bitcoin-block rule

Completed outputs are skipped when their progress.json status is "complete".

Examples:
  nohup run_incentive_research_batch.sh --jobs 4 > reports/generated/incentive_research_batch.log 2>&1 &
  tail -f reports/generated/incentive_research_batch.log
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs)
      JOBS="$2"
      shift 2
      ;;
    --heartbeat-seconds)
      HEARTBEAT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p reports/generated

is_complete() {
  local out_dir="$1"
  python3 - "$out_dir/progress.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except json.JSONDecodeError:
    raise SystemExit(1)
raise SystemExit(0 if payload.get("status") == "complete" else 1)
PY
}

run_sweep() {
  local name="$1"
  local sweep="$2"
  local out_dir="$3"

  if is_complete "$out_dir"; then
    echo "[$(date --iso-8601=seconds)] skip complete: $name ($out_dir)"
    return
  fi

  echo "[$(date --iso-8601=seconds)] start: $name"
  mkdir -p "$out_dir"
  set +e
  python3 run_sweep.py \
    --sweep "$sweep" \
    --out-dir "$out_dir" \
    --jobs "$JOBS" \
    --heartbeat-seconds "$HEARTBEAT" \
    2>&1 | tee -a "$out_dir/run.log"
  local status=${PIPESTATUS[0]}
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "[$(date --iso-8601=seconds)] failed: $name status=$status" >&2
    exit "$status"
  fi
  echo "[$(date --iso-8601=seconds)] complete: $name"
}

analyze_pool_hopping() {
  local out_dir="$1"
  local csv="$out_dir/sweep_results.csv"
  if [[ ! -f "$csv" ]]; then
    echo "Pool-hopping CSV missing, cannot analyze: $csv" >&2
    exit 1
  fi
  echo "[$(date --iso-8601=seconds)] analyze: $out_dir"
  python3 analyze_pool_hopping_sweep.py \
    --csv "$csv" \
    --out "$out_dir/analysis.md"
}

plot_sweep() {
  local out_dir="$1"
  local csv="$out_dir/sweep_results.csv"
  if [[ ! -f "$csv" ]]; then
    echo "Sweep CSV missing, cannot plot: $csv" >&2
    exit 1
  fi
  echo "[$(date --iso-8601=seconds)] plot: $out_dir"
  python3 plot_sweep_results.py \
    --csv "$csv" \
    --out-dir "$out_dir/charts"
}

run_and_plot() {
  local name="$1"
  local sweep="$2"
  local out_dir="$3"
  local analyze="${4:-no}"

  run_sweep "$name" "$sweep" "$out_dir"
  if [[ "$analyze" == "yes" ]]; then
    analyze_pool_hopping "$out_dir"
  fi
  plot_sweep "$out_dir"
}

echo "[$(date --iso-8601=seconds)] GridPool incentive research batch starting"
echo "jobs=$JOBS heartbeat=${HEARTBEAT}s"

run_and_plot \
  "universal solo pool-hopping 299-slot" \
  "sweeps/pool_hopping_universal_solo_299_sweep.json" \
  "reports/generated/sweeps/pool_hopping_universal_solo_299_long" \
  "yes"

run_and_plot \
  "physical-scale solo pool-hopping 299-slot" \
  "sweeps/pool_hopping_physical_scale_solo_299_sweep.json" \
  "reports/generated/sweeps/pool_hopping_physical_scale_solo_299_long" \
  "yes"

run_and_plot \
  "pool-hopping Bitcoin fee sensitivity 299-slot" \
  "sweeps/pool_hopping_fee_sensitivity_299_sweep.json" \
  "reports/generated/sweeps/pool_hopping_fee_sensitivity_299_long" \
  "yes"

run_and_plot \
  "block-withholding Bitcoin fee sensitivity" \
  "sweeps/block_withholding_fee_sensitivity_sweep.json" \
  "reports/generated/sweeps/block_withholding_fee_sensitivity_long" \
  "no"

run_and_plot \
  "pool-hopping snapshot-policy comparison" \
  "sweeps/pool_hopping_snapshot_policy_299_sweep.json" \
  "reports/generated/sweeps/pool_hopping_snapshot_policy_299_long" \
  "yes"

echo "[$(date --iso-8601=seconds)] GridPool incentive research batch complete"
echo "Next: inspect generated reports under reports/generated/sweeps/"
