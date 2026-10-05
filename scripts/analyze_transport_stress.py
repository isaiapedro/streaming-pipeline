#!/usr/bin/env python3
"""Repeated, aggregate-only NATS/MQTT/Kafka latency stress analysis."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka_path.parity import (
    canonical_payloads,
    run_kafka,
    run_mqtt,
    run_nats,
)
from scripts.latency_percentiles import (
    PERCENTILES,
    percentile,
    percentile_rows,
    render_percentile_plot,
    write_percentile_csv,
)

TRANSPORTS = ("nats", "mqtt", "kafka")
RUNNERS = {"nats": run_nats, "mqtt": run_mqtt, "kafka": run_kafka}
SELECTED_PERCENTILES = (50, 75, 90, 95, 99)
COLORS = {"nats": "#0072B2", "mqtt": "#E69F00", "kafka": "#009E73"}


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bootstrap_mean_ci(values: list[float], seed: int = 20_260_920) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    estimates = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(2_000)]
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def _summary(values: list[float]) -> dict[str, float | int]:
    low, high = _bootstrap_mean_ci(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "median": statistics.median(values),
        "q1": _quantile(values, 0.25),
        "q3": _quantile(values, 0.75),
        "ci95_low": low,
        "ci95_high": high,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _aggregate(run_rows: list[dict]) -> list[dict]:
    metrics = (
        "elapsed_s", "throughput_msg_s", "valid_delivery_ratio",
        "p50_ms", "p75_ms", "p90_ms", "p95_ms", "p99_ms",
        "tail_spread_ms", "tail_amplification",
    )
    output = []
    for transport in TRANSPORTS:
        selected = [row for row in run_rows if row["transport"] == transport]
        row: dict[str, object] = {"transport": transport, "repetitions": len(selected)}
        for metric in metrics:
            for name, value in _summary([float(item[metric]) for item in selected]).items():
                row[f"{metric}_{name}"] = value
        output.append(row)
    return output


def _plot_selected(run_rows: list[dict], output: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    for axis, percent in zip(axes.flat, (50, 90, 95, 99)):
        metric = f"p{percent}_ms"
        values = [[float(row[metric]) for row in run_rows if row["transport"] == name] for name in TRANSPORTS]
        boxes = axis.boxplot(values, tick_labels=[name.upper() for name in TRANSPORTS], patch_artist=True)
        for patch, name in zip(boxes["boxes"], TRANSPORTS):
            patch.set_facecolor(COLORS[name])
            patch.set_alpha(0.55)
        for index, samples in enumerate(values, 1):
            axis.scatter([index] * len(samples), samples, s=18, color="#222222", alpha=0.65)
        axis.set_title(f"P{percent} across repetitions")
        axis.set_ylabel("Validated-delivery latency (ms)")
        axis.set_yscale("log")
        axis.grid(axis="y", alpha=0.25)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _plot_operational(run_rows: list[dict], aggregate: list[dict], output: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    for axis, metric, title, ylabel in (
        (axes[0], "throughput_msg_s", "Harness completion throughput", "Valid messages/s"),
        (axes[1], "tail_amplification", "Tail amplification", "P99 / P50"),
    ):
        for index, transport in enumerate(TRANSPORTS):
            samples = [float(row[metric]) for row in run_rows if row["transport"] == transport]
            summary = next(row for row in aggregate if row["transport"] == transport)
            mean = float(summary[f"{metric}_mean"])
            low = float(summary[f"{metric}_ci95_low"])
            high = float(summary[f"{metric}_ci95_high"])
            axis.scatter([index] * len(samples), samples, color=COLORS[transport], alpha=0.45)
            axis.errorbar(index, mean, yerr=[[mean - low], [high - mean]], fmt="o", capsize=5,
                          color=COLORS[transport], markersize=7)
        axis.set_xticks(range(len(TRANSPORTS)), [name.upper() for name in TRANSPORTS])
        axis.set_title(title)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.25)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def _write_report(path: Path, run_rows: list[dict], aggregate: list[dict], args) -> None:
    by_transport = {row["transport"]: row for row in aggregate}
    lines = [
        "# Local three-transport stress analysis",
        "",
        "## Scope",
        "",
        f"This exploratory local experiment used {args.repetitions} repetitions of {args.count} valid synthetic Protobuf messages per transport, plus one intentional invalid record. NATS, MQTT QoS 1, and Kafka used the same canonical payload and validation boundary. Raw message latencies were retained only in memory; outputs contain aggregates.",
        "",
        "It characterizes this implementation and machine, not production broker capacity, clinical alarm latency, hosted behavior, or transport superiority.",
        "",
        "## Results",
        "",
        "| Transport | Throughput mean (msg/s) | P50 median (ms) | P95 median (ms) | P99 median (ms) | P99/P50 mean | Valid delivery |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in TRANSPORTS:
        row = by_transport[name]
        delivery = float(row["valid_delivery_ratio_mean"]) * 100
        lines.append(
            f"| {name.upper()} | {float(row['throughput_msg_s_mean']):.1f} "
            f"[{float(row['throughput_msg_s_ci95_low']):.1f}, {float(row['throughput_msg_s_ci95_high']):.1f}] | "
            f"{float(row['p50_ms_median']):.2f} | {float(row['p95_ms_median']):.2f} | "
            f"{float(row['p99_ms_median']):.2f} | {float(row['tail_amplification_mean']):.2f} | {delivery:.2f}% |"
        )
    lines += [
        "",
        "Mean throughput intervals are deterministic 2,000-resample bootstrap 95% intervals over repetitions. Latency cells show repetition medians. The percentile curve contains every integer percentile from P50 through P99.",
        "",
        "## Interpretation boundary",
        "",
        "- These are validated-delivery measurements, not Brain/NEWS2, storage, dashboard, or notification latency.",
        "- The brokers have different durability and acknowledgement semantics; latency alone does not select an architecture.",
        "- Setup and client behavior are part of the observed local implementation. Results must travel with configuration and machine context.",
        "- Reconnect recovery, restart persistence, memory footprint, wire overhead, packet-level degradation, and T2 producer saturation remain separate experiments.",
    ]
    path.write_text("\n".join(lines) + "\n")


def run_analysis(args) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    run_rows: list[dict] = []
    pooled: dict[str, list[float]] = defaultdict(list)
    orders = [TRANSPORTS, ("mqtt", "kafka", "nats"), ("kafka", "nats", "mqtt")]
    for repetition in range(1, args.repetitions + 1):
        messages = canonical_payloads(args.count)
        order = orders[(repetition - 1) % len(orders)]
        for position, transport in enumerate(order, 1):
            started = time.perf_counter()
            result = RUNNERS[transport](messages, args.timeout)
            elapsed = time.perf_counter() - started
            values = [value for value in result.latencies_ms if value is not None]
            pooled[transport].extend(values)
            valid_published = min(result.published, len(messages))
            p = {percent: percentile(values, percent) for percent in SELECTED_PERCENTILES}
            row = {
                "repetition": repetition, "order_position": position,
                "transport": transport, "valid_requested": len(messages),
                "valid_published": valid_published, "valid_accepted": len(values),
                "elapsed_s": elapsed,
                "throughput_msg_s": len(values) / elapsed if elapsed else 0.0,
                "valid_delivery_ratio": len(values) / valid_published if valid_published else 0.0,
                "p50_ms": p[50], "p75_ms": p[75], "p90_ms": p[90],
                "p95_ms": p[95], "p99_ms": p[99],
                "tail_spread_ms": p[99] - p[50],
                "tail_amplification": p[99] / p[50] if p[50] else 0.0,
            }
            run_rows.append(row)
            print(json.dumps(row, sort_keys=True))

    aggregate = _aggregate(run_rows)
    curves = percentile_rows(pooled, PERCENTILES)
    _write_csv(args.out_dir / "run_summary.csv", run_rows)
    _write_csv(args.out_dir / "aggregate_summary.csv", aggregate)
    write_percentile_csv(curves, args.out_dir / "percentile_curves.csv")
    render_percentile_plot(curves, args.out_dir / "percentile_curves.png",
                           title="Local validated-delivery latency: P50–P99",
                           log_y=True)
    _plot_selected(run_rows, args.out_dir / "selected_percentiles.png")
    _plot_operational(run_rows, aggregate, args.out_dir / "operational_tradeoffs.png")
    _write_report(args.out_dir / "RESULTS.md", run_rows, aggregate, args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="confirm intentional local broker access")
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this harness never contacts brokers implicitly")
    if not 1 <= args.count <= 10_000:
        parser.error("--count must be between 1 and 10000")
    if args.repetitions < 2:
        parser.error("--repetitions must be at least 2")
    run_analysis(args)


if __name__ == "__main__":
    main()
