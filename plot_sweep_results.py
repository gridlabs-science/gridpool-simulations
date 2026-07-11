#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import math
from pathlib import Path
import re
from typing import Iterable


PALETTE = [
    "#33d17a",
    "#62a0ea",
    "#f6d32d",
    "#ff7800",
    "#dc8add",
    "#5bc8af",
    "#e01b24",
    "#c0bfbc",
]

SERIES_COLORS = {
    "compact_websocket_relay": "#33d17a",
    "json_http_relay": "#62a0ea",
    "udp_fast_relay_with_fallback": "#f6d32d",
}

SERIES_DASHES = {
    "compact_websocket_relay": "7 4",
    "json_http_relay": "",
    "udp_fast_relay_with_fallback": "2 4",
}

SERIES_DRAW_PRIORITY = {
    "json_http_relay": 0,
    "udp_fast_relay_with_fallback": 1,
    "compact_websocket_relay": 2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SVG charts from GridPool sweep_results.csv.")
    parser.add_argument("--csv", required=True, type=Path, help="sweep_results.csv from run_sweep.py")
    parser.add_argument("--out-dir", type=Path, help="Directory for SVG charts. Defaults to CSV sibling / charts")
    parser.add_argument("--target-miner", default="hopper_15", help="Pool-hopping target miner")
    args = parser.parse_args()

    rows = read_rows(args.csv)
    if not rows:
        raise ValueError(f"No rows found in {args.csv}")

    out_dir = args.out_dir or (args.csv.parent / "charts")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.svg"):
        stale.unlink()

    engine = rows[0].get("engine", "")
    generated: list[Path] = []
    if engine == "economic":
        generated.extend(plot_economic(rows, out_dir, args.target_miner))
    elif engine == "variance":
        generated.extend(plot_variance(rows, out_dir))
    elif engine == "network":
        generated.extend(plot_network(rows, out_dir))
    elif engine == "adversary":
        generated.extend(plot_adversary(rows, out_dir))
    else:
        raise ValueError(f"Unsupported sweep engine for plotting: {engine!r}")

    write_charts_index(out_dir.parent, out_dir, generated)
    print(f"Wrote {len(generated)} chart(s) to {out_dir}")
    return 0


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def plot_economic(rows: list[dict[str, str]], out_dir: Path, target_miner: str) -> list[Path]:
    labels = {row.get("result_label", "") for row in rows}
    if any("withholds" in label for label in labels):
        return plot_block_withholding(rows, out_dir)

    miner_rows = [
        row
        for row in rows
        if row.get("entity_type") == "miner" and row.get("entity") == target_miner
    ]
    paired_rows = [
        row
        for row in rows
        if row.get("entity_type") == "paired_delta" and row.get("entity") == target_miner
    ]
    if not miner_rows:
        return []

    modes = sorted({row.get("param_external_payout_mode", "deterministic_fpps") for row in miner_rows})
    x_key, x_label, x_slug = choose_economic_x_axis(miner_rows)
    generated: list[Path] = []
    for mode in modes:
        mode_rows = [
            row
            for row in miner_rows
            if row.get("param_external_payout_mode", "deterministic_fpps") == mode
        ]
        mode_rows = with_economic_series_labels(mode_rows, x_key=x_key)
        points = group_points(
            mode_rows,
            x_key=x_key,
            y_key="metric_primary",
            series_key="__series_label",
        )
        path = out_dir / f"pool_hopping_absolute_ev_{slug(mode)}_by_{x_slug}.svg"
        write_line_chart(
            path,
            title=f"Pool Hopping Absolute EV: {mode}",
            subtitle=f"Target miner: {target_miner}. Y=BTC earned / theoretical hashrate EV.",
            x_label=x_label,
            y_label="EV ratio",
            series=points,
            y_reference=1.0,
        )
        generated.append(path)

        delta_rows = [
            row
            for row in paired_rows
            if row.get("param_external_payout_mode", "deterministic_fpps") == mode
        ]
        if delta_rows:
            delta_rows = with_economic_series_labels(delta_rows, x_key=x_key)
            delta_points = group_points(
                delta_rows,
                x_key=x_key,
                y_key="mean_delta_ev_ratio",
                series_key="__series_label",
            )
            path = out_dir / f"pool_hopping_paired_delta_{slug(mode)}_by_{x_slug}.svg"
            write_line_chart(
                path,
                title=f"Pool Hopping Paired Delta: {mode}",
                subtitle="Delta versus always-on GridPool on paired Monte Carlo seeds.",
                x_label=x_label,
                y_label="Delta EV ratio",
                series=delta_points,
                y_reference=0.0,
            )
            generated.append(path)

    return generated


def plot_block_withholding(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    attacker = "attacker_15"
    miner_rows = [
        row
        for row in rows
        if row.get("entity_type") == "miner" and row.get("entity") == attacker
    ]
    paired_rows = [
        row
        for row in rows
        if row.get("entity_type") == "paired_delta" and row.get("entity") == attacker
    ]
    if not miner_rows:
        return []

    generated: list[Path] = []
    ev_points = group_points(
        miner_rows,
        x_key="param_fees_btc",
        y_key="metric_primary",
        series_key="result_label",
    )
    path = out_dir / "block_withholding_attacker_ev_by_fees_btc.svg"
    write_line_chart(
        path,
        title="Block Withholding Attacker EV By Fee Level",
        subtitle="Target miner: attacker_15. Y=BTC earned / theoretical hashrate EV.",
        x_label="Bitcoin transaction fees per block (BTC)",
        y_label="Attacker EV ratio",
        series=ev_points,
        y_reference=1.0,
    )
    generated.append(path)

    if paired_rows:
        delta_points = group_points(
            paired_rows,
            x_key="param_fees_btc",
            y_key="mean_delta_ev_ratio",
            series_key="result_label",
        )
        path = out_dir / "block_withholding_attacker_delta_by_fees_btc.svg"
        write_line_chart(
            path,
            title="Block Withholding Paired Delta By Fee Level",
            subtitle="Target miner: attacker_15. Delta versus honest mining on paired Monte Carlo seeds.",
            x_label="Bitcoin transaction fees per block (BTC)",
            y_label="Delta EV ratio",
            series=delta_points,
            y_reference=0.0,
        )
        generated.append(path)

    return generated


def choose_economic_x_axis(rows: list[dict[str, str]]) -> tuple[str, str, str]:
    team_ph = {
        as_number(row.get("research_team_hashrate_ph"))
        for row in rows
        if math.isfinite(as_number(row.get("research_team_hashrate_ph")))
    }
    if len(team_ph) > 1:
        return "research_team_hashrate_ph", "GridPool team size (PH/s)", "team_ph"

    target_shares = {
        as_number(row.get("target_miner_hashrate_share"))
        for row in rows
        if math.isfinite(as_number(row.get("target_miner_hashrate_share")))
    }
    if len(target_shares) > 1:
        return "target_miner_hashrate_share", "Target miner share of GridPool team", "target_share"

    fees = {
        as_number(row.get("param_external_fee_rate"))
        for row in rows
        if math.isfinite(as_number(row.get("param_external_fee_rate")))
            }
    if len(fees) > 1:
        return "param_external_fee_rate", "External fee rate", "external_fee"

    block_fees = {
        as_number(row.get("param_fees_btc"))
        for row in rows
        if math.isfinite(as_number(row.get("param_fees_btc")))
    }
    if len(block_fees) > 1:
        return "param_fees_btc", "Bitcoin transaction fees per block (BTC)", "fees_btc"

    pool_shares = {
        as_number(row.get("param_pool_network_share"))
        for row in rows
        if math.isfinite(as_number(row.get("param_pool_network_share")))
    }
    if len(pool_shares) > 1:
        return "param_pool_network_share", "GridPool share of Bitcoin network hashrate", "pool_network_share"

    return "param_external_fee_rate", "External fee rate", "external_fee"


def with_economic_series_labels(rows: list[dict[str, str]], *, x_key: str) -> list[dict[str, str]]:
    extra_keys = [
        ("param_snapshot_policy", "policy"),
        ("research_target_hashrate_ph", "target PH"),
        ("param_fees_btc", "fees"),
    ]
    varying = [
        (key, label)
        for key, label in extra_keys
        if key != x_key and len({row.get(key, "") for row in rows if row.get(key, "")}) > 1
    ]
    enriched = []
    for row in rows:
        clone = dict(row)
        pieces = [row.get("result_label", "")]
        for key, label in varying:
            value = row.get(key, "")
            if value:
                pieces.append(f"{label} {value}")
        clone["__series_label"] = " | ".join(pieces)
        enriched.append(clone)
    return enriched


def plot_variance(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    miner_rows = [row for row in rows if row.get("entity_type") == "miner"]
    if not miner_rows:
        return []

    filtered = filter_numeric(miner_rows, "param_fees_btc", 0.05)
    filtered = [row for row in filtered if row.get("param_support_slot_enabled") == "False"]
    filtered = filter_numeric(filtered, "team_multiplier", 300.0)
    if not filtered:
        filtered = miner_rows

    generated: list[Path] = []
    cv_points = group_points(filtered, x_key="total_slots", y_key="grid_cv", series_key="entity")
    path = out_dir / "variance_gridpool_cv_by_slots.svg"
    write_line_chart(
        path,
        title="GridPool Payout Variance By Payout List Size",
        subtitle="Filtered to fee=0.05 BTC, support slot off, team multiplier=300 when available.",
        x_label="Total payout slots",
        y_label="GridPool CV",
        series=cv_points,
        log_y=True,
    )
    generated.append(path)

    zero_points = group_points(
        filtered,
        x_key="total_slots",
        y_key="probability_zero_grid_payout",
        series_key="entity",
    )
    path = out_dir / "variance_zero_payout_probability_by_slots.svg"
    write_line_chart(
        path,
        title="Probability Of Zero GridPool Payout In Period",
        subtitle="Filtered to fee=0.05 BTC, support slot off, team multiplier=300 when available.",
        x_label="Total payout slots",
        y_label="P(zero payout)",
        series=zero_points,
        y_min=0.0,
        y_max=1.0,
    )
    generated.append(path)

    reduction_by_slots = collapse_mean_by_x(filtered, x_key="total_slots", y_key="metric_primary")
    path = out_dir / "variance_reduction_by_slots.svg"
    write_line_chart(
        path,
        title="Variance Reduction Versus Solo By Slot Count",
        subtitle="Mean across miner sizes after applying the same filter as the CV chart.",
        x_label="Total payout slots",
        y_label="Variance reduction vs solo",
        series={"variance reduction": reduction_by_slots},
    )
    generated.append(path)
    return generated


def plot_network(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    relay_rows = [row for row in rows if row.get("entity_type") == "relay_profile"]
    if not relay_rows:
        return []

    generated: list[Path] = []
    duration_text = network_duration_text(relay_rows)
    for node_count in sorted({as_number(row.get("param_node_count")) for row in relay_rows}):
        subset = [row for row in relay_rows if as_number(row.get("param_node_count")) == node_count]
        points = group_points(subset, x_key="param_peer_degree", y_key="mean_split_rate", series_key="result_label")
        path = out_dir / f"latency_split_rate_nodes_{int(node_count)}.svg"
        write_line_chart(
            path,
            title=f"Snapshot Split Rate: {int(node_count)} Nodes",
            subtitle=f"Total network nodes={int(node_count)}. Peer degree=active peers per node. {latency_profile_note()}",
            x_label="Peer degree (active peers per node)",
            y_label="Split rate",
            series=points,
            y_min=0.0,
        )
        generated.append(path)

        payload_points = group_points(
            subset,
            x_key="param_peer_degree",
            y_key="mean_estimated_payload_mb",
            series_key="result_label",
        )
        path = out_dir / f"latency_payload_nodes_{int(node_count)}.svg"
        write_line_chart(
            path,
            title=f"Estimated Relay Payload: {int(node_count)} Nodes",
            subtitle=f"Lower-bound full-network payload over {duration_text}; mostly flat because this estimate counts delivery to all nodes, not per-edge duplicates.",
            x_label="Peer degree (active peers per node)",
            y_label=f"Payload MB / {duration_text}",
            series=payload_points,
            y_min=0.0,
        )
        generated.append(path)

    combined_degree = choose_combined_network_degree(relay_rows)
    combined_rows = [
        row
        for row in relay_rows
        if as_number(row.get("param_peer_degree")) == combined_degree
    ]
    if combined_rows:
        payload_by_nodes = group_points(
            combined_rows,
            x_key="param_node_count",
            y_key="mean_estimated_payload_mb",
            series_key="result_label",
        )
        path = out_dir / f"latency_payload_by_node_count_degree_{int(combined_degree)}.svg"
        write_line_chart(
            path,
            title=f"Relay Payload Scaling At Degree {int(combined_degree)}",
            subtitle=f"Total network payload over {duration_text}. X=total GridPool nodes; degree={int(combined_degree)} active peers per node.",
            x_label="Total GridPool nodes",
            y_label=f"Payload MB / {duration_text}",
            series=payload_by_nodes,
            y_min=0.0,
        )
        generated.append(path)

        split_by_nodes = group_points(
            combined_rows,
            x_key="param_node_count",
            y_key="mean_split_rate",
            series_key="result_label",
        )
        path = out_dir / f"latency_split_rate_by_node_count_degree_{int(combined_degree)}.svg"
        write_line_chart(
            path,
            title=f"Snapshot Split Scaling At Degree {int(combined_degree)}",
            subtitle=f"X=total GridPool nodes; degree={int(combined_degree)} active peers per node. {latency_profile_note()}",
            x_label="Total GridPool nodes",
            y_label="Split rate",
            series=split_by_nodes,
            y_min=0.0,
        )
        generated.append(path)
    return generated


def plot_adversary(rows: list[dict[str, str]], out_dir: Path) -> list[Path]:
    miner_rows = [row for row in rows if row.get("entity_type") == "miner"]
    if not miner_rows:
        return []

    generated: list[Path] = []
    for role in ["target", "cartel"]:
        subset = [row for row in miner_rows if row.get("role") == role]
        if not subset:
            continue
        points = group_points(
            subset,
            x_key="param_cartel_share",
            y_key="metric_primary",
            series_key="result_label",
            x_transform=parse_cartel_percent,
        )
        path = out_dir / f"majority_{role}_ev_by_cartel_share.svg"
        write_line_chart(
            path,
            title=f"Majority/Censorship Model: {role.title()} EV",
            subtitle="Y=BTC earned / theoretical hashrate EV.",
            x_label="Cartel share (%)",
            y_label="EV ratio",
            series=points,
            y_reference=1.0,
        )
        generated.append(path)

    reject_rows = [row for row in miner_rows if row.get("role") == "target"]
    reject_points = group_points(
        reject_rows,
        x_key="param_cartel_share",
        y_key="mean_shares_rejected_by_team",
        series_key="result_label",
        x_transform=parse_cartel_percent,
    )
    path = out_dir / "majority_target_rejected_shares.svg"
    write_line_chart(
        path,
        title="Target Proofs Rejected By Team",
        subtitle="Shows when a strategy is explicitly censoring the target miner's valid proofs.",
        x_label="Cartel share (%)",
        y_label="Mean rejected proofs",
        series=reject_points,
        y_min=0.0,
    )
    generated.append(path)
    return generated


def group_points(
    rows: list[dict[str, str]],
    *,
    x_key: str,
    y_key: str,
    series_key: str,
    x_transform=None,
) -> dict[str, list[tuple[float, float]]]:
    grouped: dict[str, dict[float, list[float]]] = {}
    for row in rows:
        x = x_transform(row.get(x_key, "")) if x_transform else as_number(row.get(x_key))
        y = as_number(row.get(y_key))
        if math.isnan(x) or math.isnan(y):
            continue
        grouped.setdefault(row.get(series_key, ""), {}).setdefault(x, []).append(y)

    result: dict[str, list[tuple[float, float]]] = {}
    for label, values_by_x in grouped.items():
        result[label] = sorted(
            (x, sum(values) / len(values))
            for x, values in values_by_x.items()
            if values
        )
    return result


def collapse_mean_by_x(rows: list[dict[str, str]], *, x_key: str, y_key: str) -> list[tuple[float, float]]:
    values_by_x: dict[float, list[float]] = {}
    for row in rows:
        x = as_number(row.get(x_key))
        y = as_number(row.get(y_key))
        if math.isnan(x) or math.isnan(y):
            continue
        values_by_x.setdefault(x, []).append(y)
    return sorted((x, sum(values) / len(values)) for x, values in values_by_x.items())


def filter_numeric(rows: list[dict[str, str]], key: str, value: float) -> list[dict[str, str]]:
    return [row for row in rows if math.isclose(as_number(row.get(key)), value)]


def write_line_chart(
    path: Path,
    *,
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    series: dict[str, list[tuple[float, float]]] | dict[str, list],
    width: int = 980,
    height: int = 560,
    y_reference: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    log_y: bool = False,
) -> None:
    clean_series = {
        label: [(float(x), float(y)) for x, y in points if finite(x) and finite(y)]
        for label, points in series.items()
    }
    clean_series = {label: points for label, points in clean_series.items() if points}
    if not clean_series:
        path.write_text(empty_svg(title, subtitle, width, height), encoding="utf-8")
        return

    all_x = [x for points in clean_series.values() for x, _ in points]
    all_y = [y for points in clean_series.values() for _, y in points]
    if y_reference is not None:
        all_y.append(y_reference)
    if y_min is not None:
        all_y.append(y_min)
    if y_max is not None:
        all_y.append(y_max)

    left, right, top, bottom = 84, 260, 82, 78
    plot_w = width - left - right
    plot_h = height - top - bottom

    x0, x1 = min(all_x), max(all_x)
    if math.isclose(x0, x1):
        x0 -= 1.0
        x1 += 1.0

    if log_y:
        positive = [y for y in all_y if y > 0]
        y0 = min(positive) if positive else 0.1
        y1 = max(positive) if positive else 1.0
        y0 = y_min if y_min is not None and y_min > 0 else y0
        y1 = y_max if y_max is not None else y1
        if math.isclose(y0, y1):
            y0 /= 2.0
            y1 *= 2.0
        y0_log = math.log10(y0)
        y1_log = math.log10(y1)
    else:
        y0 = y_min if y_min is not None else min(all_y)
        y1 = y_max if y_max is not None else max(all_y)
        padding = (y1 - y0) * 0.08 if not math.isclose(y0, y1) else max(abs(y0) * 0.1, 1.0)
        if y_min is None:
            y0 -= padding
        if y_max is None:
            y1 += padding
        if math.isclose(y0, y1):
            y0 -= 1.0
            y1 += 1.0

    def sx(x: float) -> float:
        return left + ((x - x0) / (x1 - x0)) * plot_w

    def sy(y: float) -> float:
        if log_y:
            y = max(y, 1e-18)
            return top + (1.0 - ((math.log10(y) - y0_log) / (y1_log - y0_log))) * plot_h
        return top + (1.0 - ((y - y0) / (y1 - y0))) * plot_h

    x_ticks = nice_ticks(x0, x1, count=5)
    y_ticks = log_ticks(y0, y1) if log_y else nice_ticks(y0, y1, count=6)

    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append("<style>")
    out.append("text{font-family:Arial,Helvetica,sans-serif;fill:#e8ecef} .muted{fill:#9aa4aa} .grid{stroke:#26313a;stroke-width:1} .axis{stroke:#7a858d;stroke-width:1.2} .ref{stroke:#ffcc66;stroke-width:1.5;stroke-dasharray:5 5} .line{fill:none;stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round} .dot{stroke:#081017;stroke-width:1.3}")
    out.append("</style>")
    out.append('<rect width="100%" height="100%" fill="#081017"/>')
    out.append(f'<text x="{left}" y="34" font-size="22" font-weight="700">{esc(title)}</text>')
    out.append(f'<text x="{left}" y="58" class="muted" font-size="13">{esc(subtitle)}</text>')

    for tick in y_ticks:
        if log_y and tick <= 0:
            continue
        y = sy(tick)
        out.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" class="grid"/>')
        out.append(f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" class="muted" font-size="11">{fmt(tick)}</text>')
    for tick in x_ticks:
        x = sx(tick)
        out.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_h}" class="grid"/>')
        out.append(f'<text x="{x:.2f}" y="{top + plot_h + 24}" text-anchor="middle" class="muted" font-size="11">{fmt(tick)}</text>')

    out.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" class="axis"/>')
    out.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" class="axis"/>')

    if y_reference is not None and (log_y is False or y_reference > 0):
        y = sy(y_reference)
        out.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" class="ref"/>')
        out.append(f'<text x="{left + plot_w + 8}" y="{y + 4:.2f}" fill="#ffcc66" font-size="11">ref {fmt(y_reference)}</text>')

    out.append(f'<text x="{left + plot_w / 2}" y="{height - 20}" text-anchor="middle" class="muted" font-size="13">{esc(x_label)}</text>')
    out.append(f'<text x="22" y="{top + plot_h / 2}" text-anchor="middle" transform="rotate(-90 22 {top + plot_h / 2})" class="muted" font-size="13">{esc(y_label)}{" (log)" if log_y else ""}</text>')

    legend_x = left + plot_w + 28
    legend_y = top
    ordered = sorted(
        clean_series.items(),
        key=lambda item: (SERIES_DRAW_PRIORITY.get(item[0], 1), item[0]),
    )
    color_index = 0
    for index, (label, points) in enumerate(ordered):
        color = color_for_series(label, color_index)
        dash = SERIES_DASHES.get(label, "")
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        coords = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in points if not log_y or y > 0)
        if coords:
            out.append(f'<polyline points="{coords}" class="line" stroke="{color}"{dash_attr}/>')
        for x, y in points:
            if log_y and y <= 0:
                continue
            out.append(f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="4" fill="{color}" class="dot"/>')
        y = legend_y + index * 24
        out.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x + 18}" y2="{y}" stroke="{color}" stroke-width="3"{dash_attr}/>')
        out.append(f'<text x="{legend_x + 26}" y="{y + 4}" class="muted" font-size="11">{esc(short_label(label))}</text>')
        if label not in SERIES_COLORS:
            color_index += 1

    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def write_charts_index(parent_dir: Path, chart_dir: Path, charts: list[Path]) -> None:
    lines = [
        "# Sweep Charts",
        "",
        "Status: generated by `plot_sweep_results.py`.",
        "",
    ]
    for chart in charts:
        rel = chart.relative_to(parent_dir)
        lines.append(f"## {chart.stem.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"![{chart.stem}]({rel.as_posix()})")
        lines.append("")
    (parent_dir / "charts.md").write_text("\n".join(lines), encoding="utf-8")


def nice_ticks(v0: float, v1: float, *, count: int) -> list[float]:
    if math.isclose(v0, v1):
        return [v0]
    raw = (v1 - v0) / max(1, count - 1)
    power = 10 ** math.floor(math.log10(abs(raw))) if raw else 1.0
    step = min([1, 2, 2.5, 5, 10], key=lambda m: abs(raw - m * power)) * power
    start = math.ceil(v0 / step) * step
    ticks = []
    value = start
    while value <= v1 + step * 0.5 and len(ticks) < count + 3:
        ticks.append(0.0 if abs(value) < step * 1e-9 else value)
        value += step
    return ticks or [v0, v1]


def log_ticks(v0: float, v1: float) -> list[float]:
    start = math.floor(math.log10(v0))
    end = math.ceil(math.log10(v1))
    ticks = [10 ** power for power in range(start, end + 1)]
    return [tick for tick in ticks if v0 <= tick <= v1] or [v0, v1]


def choose_combined_network_degree(rows: list[dict[str, str]]) -> float:
    degrees = sorted({as_number(row.get("param_peer_degree")) for row in rows})
    finite_degrees = [degree for degree in degrees if math.isfinite(degree)]
    if 8.0 in finite_degrees:
        return 8.0
    return finite_degrees[len(finite_degrees) // 2] if finite_degrees else 0.0


def network_duration_text(rows: list[dict[str, str]]) -> str:
    blocks = first_finite(rows, "blocks")
    interval = first_finite(rows, "block_interval_seconds")
    if math.isfinite(blocks) and math.isfinite(interval):
        days = (blocks * interval) / 86_400
        return f"{int(blocks)} Bitcoin blocks (~{days:.1f} days)"
    return "the full simulated run (current latency sweep: 600 Bitcoin blocks, ~4.2 days)"


def latency_profile_note() -> str:
    return "Assumed one-hop share latency: JSON 650ms, compact WS 190ms, UDP-fast 35ms; block notification mean 850ms."


def first_finite(rows: list[dict[str, str]], key: str) -> float:
    for row in rows:
        value = as_number(row.get(key))
        if math.isfinite(value):
            return value
    return math.nan


def color_for_series(label: str, fallback_index: int) -> str:
    if label in SERIES_COLORS:
        return SERIES_COLORS[label]
    return PALETTE[fallback_index % len(PALETTE)]


def empty_svg(title: str, subtitle: str, width: int, height: int) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#081017"/>',
            f'<text x="40" y="44" font-family="Arial" font-size="22" fill="#e8ecef">{esc(title)}</text>',
            f'<text x="40" y="72" font-family="Arial" font-size="13" fill="#9aa4aa">{esc(subtitle)}</text>',
            '<text x="40" y="120" font-family="Arial" font-size="15" fill="#9aa4aa">No plottable data found.</text>',
            "</svg>",
        ]
    )


def as_number(value: str | None) -> float:
    if value is None or value == "":
        return math.nan
    try:
        return float(value)
    except ValueError:
        match = re.search(r"(\d+(?:\.\d+)?)", value)
        return float(match.group(1)) if match else math.nan


def parse_cartel_percent(value: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else math.nan


def finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def fmt(value: float) -> str:
    if not math.isfinite(value):
        return ""
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    if abs(value) >= 1:
        return f"{value:.3f}"
    if abs(value) >= 0.01:
        return f"{value:.3f}"
    if abs(value) >= 0.0001:
        return f"{value:.5f}"
    return f"{value:.1e}"


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "value"


def short_label(value: str) -> str:
    value = value.replace("hopper_leaves_", "leaves_")
    value = value.replace("_with_fallback", "")
    value = value.replace("_relay", "")
    value = value.replace("cartel_", "cartel ")
    value = value.replace("_", " ")
    return value[:42]


if __name__ == "__main__":
    raise SystemExit(main())
