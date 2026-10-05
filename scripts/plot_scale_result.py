#!/usr/bin/env python3
"""Plot one aggregate scale-tier JSON result without raw message data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def render(input_path: Path, output_path: Path) -> None:
    import matplotlib.pyplot as plt

    result = json.loads(input_path.read_text())
    target = float(result["target_rate_msg_s"])
    achieved = float(result["achieved_rate_msg_s"])
    attainment = achieved / target * 100 if target else 0
    p50 = result.get("p50_latency_ms")
    p99 = result.get("p99_latency_ms")

    figure, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    axes[0].bar(("Target", "Achieved"), (target, achieved), color=("#999999", "#0072B2"))
    axes[0].set_ylabel("Messages per second")
    axes[0].set_title(f"{result['tier']} throughput — {attainment:.1f}% of target")
    for index, value in enumerate((target, achieved)):
        axes[0].text(index, value, f"{value:,.0f}", ha="center", va="bottom")

    labels, values = [], []
    for label, value in (("P50", p50), ("P99", p99)):
        if value is not None:
            labels.append(label)
            values.append(float(value))
    axes[1].bar(labels, values, color=("#009E73", "#D55E00")[: len(values)])
    axes[1].set_ylabel("Publish-to-fetch latency (ms)")
    axes[1].set_title(f"Latency; final backlog={result.get('backlog_messages', 'unknown')}")
    for index, value in enumerate(values):
        axes[1].text(index, value, f"{value:.1f} ms", ha="center", va="bottom")

    figure.suptitle(
        f"Local {result['tier']} transport result: {result['patients']} synthetic patients, "
        f"{result['signal_rate_hz']:g} Hz"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.input, args.output)


if __name__ == "__main__":
    main()
