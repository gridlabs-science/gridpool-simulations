#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

JOBS=4
HEARTBEAT=60
PROFILE="core"

usage() {
  cat <<'EOF'
Usage: run_research_batch.sh [--jobs N] [--heartbeat-seconds N] [--profile core]

Runs the next publishable GridPool modeling sweeps sequentially. Completed
outputs are skipped when their progress.json status is "complete".

Profiles:
  core   Pool hopping external-mode, payout variance, latency, majority/censorship.

Examples:
  nohup run_research_batch.sh --jobs 4 > reports/generated/research_batch.log 2>&1 &
  tail -f reports/generated/research_batch.log
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
    --profile)
      PROFILE="$2"
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

if [[ "$PROFILE" != "core" ]]; then
  echo "Unknown profile: $PROFILE" >&2
  usage >&2
  exit 2
fi

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
  echo "[$(date --iso-8601=seconds)] analyze: pool hopping ($out_dir)"
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

echo "[$(date --iso-8601=seconds)] GridPool research batch starting"
echo "profile=$PROFILE jobs=$JOBS heartbeat=${HEARTBEAT}s"

run_sweep \
  "pool hopping external-mode 299-slot" \
  "sweeps/pool_hopping_external_mode_299_sweep.json" \
  "reports/generated/sweeps/pool_hopping_external_mode_299_long"
analyze_pool_hopping "reports/generated/sweeps/pool_hopping_external_mode_299_long"
plot_sweep "reports/generated/sweeps/pool_hopping_external_mode_299_long"

run_sweep \
  "payout variance fee/support sensitivity" \
  "sweeps/payout_variance_fee_sweep.json" \
  "reports/generated/sweeps/payout_variance_fee_long"
plot_sweep "reports/generated/sweeps/payout_variance_fee_long"

run_sweep \
  "latency peer-degree sensitivity" \
  "sweeps/latency_peer_degree_sweep.json" \
  "reports/generated/sweeps/latency_peer_degree_long"
plot_sweep "reports/generated/sweeps/latency_peer_degree_long"

run_sweep \
  "majority censorship cartel-share sensitivity" \
  "sweeps/majority_cartel_share_sweep.json" \
  "reports/generated/sweeps/majority_cartel_share_long"
plot_sweep "reports/generated/sweeps/majority_cartel_share_long"

echo "[$(date --iso-8601=seconds)] GridPool research batch complete"
echo "Next: inspect generated reports under reports/generated/sweeps/"
