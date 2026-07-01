#!/usr/bin/env python3
"""Estimate rough node resource cost for V3 branch-market designs.

This is intentionally a first-order sizing model, not a packet-level simulator.
It answers: if a node tracks N payout branches, each with a fixed proof reserve,
how much RAM/disk/bandwidth might it need under different proof sizes and proof
overlap assumptions?
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def parse_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def parse_floats(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


@dataclass(frozen=True)
class ResourceRow:
    branch_count: int
    reserve_depth: int
    proof_bytes: int
    proof_overlap: float
    peer_degree: int
    proofs_per_branch_per_hour: float
    effective_unique_branch_factor: float
    unique_proof_count: float
    proof_blob_bytes: float
    branch_ref_bytes: float
    branch_metadata_bytes: float
    estimated_ram_bytes: float
    estimated_disk_bytes: float
    worst_case_proof_relay_bytes_per_day: float
    deduped_proof_relay_bytes_per_day: float
    branch_summary_bytes_per_day: float
    total_worst_case_bandwidth_bytes_per_day: float
    total_deduped_bandwidth_bytes_per_day: float


def estimate(
    branch_count: int,
    reserve_depth: int,
    proof_bytes: int,
    proof_overlap: float,
    peer_degree: int,
    proofs_per_branch_per_hour: float,
    ref_bytes: int,
    branch_metadata_bytes: int,
    ram_overhead_multiplier: float,
    summary_bytes: int,
    summary_interval_seconds: int,
) -> ResourceRow:
    overlap = max(0.0, min(1.0, proof_overlap))
    effective_unique_branch_factor = 1.0 + max(0, branch_count - 1) * (1.0 - overlap)
    unique_proof_count = reserve_depth * effective_unique_branch_factor
    proof_blob_bytes = unique_proof_count * proof_bytes
    branch_ref_bytes = branch_count * reserve_depth * ref_bytes
    branch_metadata_total = branch_count * branch_metadata_bytes
    estimated_disk_bytes = proof_blob_bytes + branch_ref_bytes + branch_metadata_total
    estimated_ram_bytes = estimated_disk_bytes * ram_overhead_multiplier

    proof_events_per_day = branch_count * proofs_per_branch_per_hour * 24.0
    worst_case_proof_relay = proof_events_per_day * proof_bytes * peer_degree
    deduped_proof_events_per_day = effective_unique_branch_factor * proofs_per_branch_per_hour * 24.0
    deduped_proof_relay = deduped_proof_events_per_day * proof_bytes * peer_degree

    summaries_per_day = 86400.0 / max(1, summary_interval_seconds)
    branch_summary_bytes = branch_count * summaries_per_day * summary_bytes * peer_degree

    return ResourceRow(
        branch_count=branch_count,
        reserve_depth=reserve_depth,
        proof_bytes=proof_bytes,
        proof_overlap=overlap,
        peer_degree=peer_degree,
        proofs_per_branch_per_hour=proofs_per_branch_per_hour,
        effective_unique_branch_factor=effective_unique_branch_factor,
        unique_proof_count=unique_proof_count,
        proof_blob_bytes=proof_blob_bytes,
        branch_ref_bytes=branch_ref_bytes,
        branch_metadata_bytes=branch_metadata_total,
        estimated_ram_bytes=estimated_ram_bytes,
        estimated_disk_bytes=estimated_disk_bytes,
        worst_case_proof_relay_bytes_per_day=worst_case_proof_relay,
        deduped_proof_relay_bytes_per_day=deduped_proof_relay,
        branch_summary_bytes_per_day=branch_summary_bytes,
        total_worst_case_bandwidth_bytes_per_day=worst_case_proof_relay + branch_summary_bytes,
        total_deduped_bandwidth_bytes_per_day=deduped_proof_relay + branch_summary_bytes,
    )


def write_report(out_dir: Path, rows: list[ResourceRow], args: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "resource_estimates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    metadata = {
        "status": "complete",
        "model": "branch_market_resource_envelope_v1",
        "args": vars(args),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    selected = [
        row
        for row in rows
        if row.reserve_depth == max(args.reserve_depths)
        and row.proof_bytes == max(args.proof_bytes)
        and row.proof_overlap in {0.5, 0.9}
    ]
    selected.sort(key=lambda row: (row.proof_overlap, row.branch_count))

    lines = [
        "# Branch Market Resource Envelope",
        "",
        "Status: first-order estimate.",
        "",
        "This model estimates rough node RAM, disk, and outbound relay bandwidth if",
        "a V3 Branch Market node tracks many payout branches. It is intentionally",
        "coarse; it is meant to identify deal-breaker ranges before deeper modeling.",
        "",
        "## Assumptions",
        "",
        f"- Branch counts: `{', '.join(map(str, args.branch_counts))}`",
        f"- Reserve depths: `{', '.join(map(str, args.reserve_depths))}`",
        f"- Proof sizes: `{', '.join(str(x) + ' B' for x in args.proof_bytes)}`",
        f"- Proof overlap values: `{', '.join(str(x) for x in args.proof_overlaps)}`",
        f"- Peer degree: `{args.peer_degree}`",
        f"- New proofs per branch per hour: `{args.proofs_per_branch_per_hour}`",
        f"- Branch summary interval: `{args.summary_interval_seconds}` seconds",
        f"- Branch summary bytes: `{args.summary_bytes}`",
        "",
        "The overlap model is simple:",
        "",
        "```text",
        "effective_unique_branch_factor = 1 + (branch_count - 1) * (1 - overlap)",
        "```",
        "",
        "So `90%` overlap means each additional branch contributes only `10%` of a",
        "fresh reserve of unique proof blobs, while still requiring branch proof-ID",
        "references.",
        "",
        "## Selected Worst-Proof-Size Cases",
        "",
        "| Branches | Overlap | Unique proofs | Est. RAM | Est. disk | Worst relay/day | Deduped relay/day | Summary/day |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in selected:
        lines.append(
            "| "
            f"{row.branch_count} | "
            f"{row.proof_overlap:.0%} | "
            f"{row.unique_proof_count:.0f} | "
            f"{human_bytes(row.estimated_ram_bytes)} | "
            f"{human_bytes(row.estimated_disk_bytes)} | "
            f"{human_bytes(row.worst_case_proof_relay_bytes_per_day)} | "
            f"{human_bytes(row.deduped_proof_relay_bytes_per_day)} | "
            f"{human_bytes(row.branch_summary_bytes_per_day)} |"
        )

    worst_ram = max(rows, key=lambda row: row.estimated_ram_bytes)
    worst_deduped_bw = max(rows, key=lambda row: row.total_deduped_bandwidth_bytes_per_day)
    worst_full_bw = max(rows, key=lambda row: row.total_worst_case_bandwidth_bytes_per_day)

    lines.extend(
        [
            "",
            "## Extremes In This Run",
            "",
            f"- Highest estimated RAM: `{human_bytes(worst_ram.estimated_ram_bytes)}` at "
            f"`{worst_ram.branch_count}` branches, `{worst_ram.reserve_depth}` reserve, "
            f"`{worst_ram.proof_bytes}` B proofs, `{worst_ram.proof_overlap:.0%}` overlap.",
            f"- Highest deduped bandwidth/day: `{human_bytes(worst_deduped_bw.total_deduped_bandwidth_bytes_per_day)}` at "
            f"`{worst_deduped_bw.branch_count}` branches, `{worst_deduped_bw.proof_overlap:.0%}` overlap.",
            f"- Highest worst-case bandwidth/day: `{human_bytes(worst_full_bw.total_worst_case_bandwidth_bytes_per_day)}` at "
            f"`{worst_full_bw.branch_count}` branches.",
            "",
            "## Interpretation",
            "",
            "- Full proof duplication per branch gets expensive quickly.",
            "- Storing full proof blobs once and representing branches as proof-ID",
            "  references is likely mandatory.",
            "- Summary gossip can dominate if branch summaries are sent too often to too",
            "  many peers.",
            "- A consumer node probably needs a bounded branch set, lazy full-proof fetch,",
            "  and pruning rules for low-viability branches.",
            "",
        ]
    )

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="reports/generated/branch_market_resource_model")
    parser.add_argument("--branch-counts", type=parse_ints, default=parse_ints("1,5,10,25,50,100,250"))
    parser.add_argument("--reserve-depths", type=parse_ints, default=parse_ints("300,897"))
    parser.add_argument("--proof-bytes", type=parse_ints, default=parse_ints("1200,2500,5000"))
    parser.add_argument("--proof-overlaps", type=parse_floats, default=parse_floats("0,0.5,0.9,0.98"))
    parser.add_argument("--peer-degree", type=int, default=8)
    parser.add_argument("--proofs-per-branch-per-hour", type=float, default=60.0)
    parser.add_argument("--ref-bytes", type=int, default=48)
    parser.add_argument("--branch-metadata-bytes", type=int, default=4096)
    parser.add_argument("--ram-overhead-multiplier", type=float, default=2.0)
    parser.add_argument("--summary-bytes", type=int, default=512)
    parser.add_argument("--summary-interval-seconds", type=int, default=60)
    args = parser.parse_args()

    rows: list[ResourceRow] = []
    for branch_count in args.branch_counts:
        for reserve_depth in args.reserve_depths:
            for proof_bytes in args.proof_bytes:
                for proof_overlap in args.proof_overlaps:
                    rows.append(
                        estimate(
                            branch_count=branch_count,
                            reserve_depth=reserve_depth,
                            proof_bytes=proof_bytes,
                            proof_overlap=proof_overlap,
                            peer_degree=args.peer_degree,
                            proofs_per_branch_per_hour=args.proofs_per_branch_per_hour,
                            ref_bytes=args.ref_bytes,
                            branch_metadata_bytes=args.branch_metadata_bytes,
                            ram_overhead_multiplier=args.ram_overhead_multiplier,
                            summary_bytes=args.summary_bytes,
                            summary_interval_seconds=args.summary_interval_seconds,
                        )
                    )

    write_report(Path(args.out_dir), rows, args)
    print(f"Wrote {len(rows)} rows to {args.out_dir}")


if __name__ == "__main__":
    main()
