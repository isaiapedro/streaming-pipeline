#!/usr/bin/env python3
"""Visualize the configured noise/dropout wrapper on synthetic vital rows.

The input must contain only the five numeric signal columns used by the
distribution validator. Raw rows are neither copied nor written to output;
the command emits one figure, aggregate event counts, and configuration
provenance for a presentation-only demonstration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.generators.noise import NoiseConfig, NoiseInjector
from scripts.validate_distributions import SIGNAL_LABELS, SIGNALS, load_reference


ROOT = Path(__file__).resolve().parents[1]


def apply_noise(
    values: dict[str, np.ndarray],
    *,
    config: NoiseConfig,
    seed: int,
    sample_interval_ms: int,
    samples: int,
) -> tuple[dict[str, list[tuple[int, float] | None]], list[dict]]:
    if samples < 2:
        raise ValueError("samples must be at least 2")
    if sample_interval_ms < 1:
        raise ValueError("sample interval must be positive")
    probabilities = (config.packet_loss_rate, config.spike_probability, config.dropout_probability)
    if any(value < 0 or value > 1 for value in probabilities):
        raise ValueError("loss, spike, and dropout probabilities must be between 0 and 1")
    if config.spike_magnitude_pct < 0 or config.dropout_duration_s < 0 or config.clock_drift_ms < 0:
        raise ValueError("spike magnitude, dropout duration, and clock drift must be non-negative")
    available = min(len(values[signal]) for signal in SIGNALS)
    if available < samples:
        raise ValueError(f"input has {available} rows but {samples} were requested")

    injector = NoiseInjector(config, seed)
    observed: dict[str, list[tuple[int, float] | None]] = {signal: [] for signal in SIGNALS}
    summary = {
        signal: {"signal": signal, "samples": samples, "retained": 0, "dropped": 0, "spiked": 0, "jittered": 0}
        for signal in SIGNALS
    }
    for index in range(samples):
        timestamp_ms = index * sample_interval_ms
        for signal in SIGNALS:
            clean = float(values[signal][index])
            noisy, noisy_timestamp_ms = injector.apply(signal, clean, timestamp_ms)
            if noisy is None:
                observed[signal].append(None)
                summary[signal]["dropped"] += 1
                continue
            noisy = float(noisy)
            observed[signal].append((noisy_timestamp_ms, noisy))
            summary[signal]["retained"] += 1
            summary[signal]["spiked"] += int(not np.isclose(clean, noisy))
            summary[signal]["jittered"] += int(timestamp_ms != noisy_timestamp_ms)
    return observed, list(summary.values())


def render(
    input_path: Path,
    out_dir: Path,
    *,
    config: NoiseConfig,
    seed: int,
    sample_interval_ms: int,
    samples: int,
) -> list[dict]:
    values = load_reference(input_path)
    observed, summary = apply_noise(
        values,
        config=config,
        seed=seed,
        sample_interval_ms=sample_interval_ms,
        samples=samples,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass

    clean_time_s = np.arange(samples) * sample_interval_ms / 1_000
    fig, axes = plt.subplots(len(SIGNALS), 1, figsize=(12, 12), sharex=True, constrained_layout=True)
    for axis, signal, label in zip(axes, SIGNALS, SIGNAL_LABELS):
        clean = values[signal][:samples]
        axis.plot(clean_time_s, clean, color="#9CA3AF", linewidth=1.2, label="clean synthetic")
        observed_time = [
            clean_time_s[index] if point is None else point[0] / 1_000
            for index, point in enumerate(observed[signal])
        ]
        observed_value = [np.nan if point is None else point[1] for point in observed[signal]]
        axis.plot(observed_time, observed_value, color="#2563EB", linewidth=1, label="after injection")
        spike_indices = [
            index for index, point in enumerate(observed[signal])
            if point is not None and not np.isclose(float(clean[index]), point[1])
        ]
        if spike_indices:
            axis.scatter(
                [observed[signal][index][0] / 1_000 for index in spike_indices],
                [observed[signal][index][1] for index in spike_indices],
                marker="x", color="#DC2626", s=32, label="injected spike", zorder=3,
            )
        dropped_indices = [index for index, point in enumerate(observed[signal]) if point is None]
        if dropped_indices:
            axis.scatter(
                clean_time_s[dropped_indices], clean[dropped_indices],
                marker="|", color="#F59E0B", s=90, label="dropped sample", zorder=3,
            )
        axis.set_ylabel(label)
        axis.grid(alpha=0.2)
        axis.legend(loc="upper right", fontsize=7, ncol=4)
    axes[-1].set_xlabel("Elapsed time (seconds; observed line includes clock jitter)")
    fig.suptitle("Deterministic noise and dropout injection on synthetic signals")
    fig.savefig(out_dir / "noise_dropout_injection.png", dpi=180)
    plt.close(fig)

    with (out_dir / "noise_injection_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    with (out_dir / "noise_injection_provenance.json").open("w") as handle:
        json.dump(
            {
                "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                "noise_seed": seed,
                "samples": samples,
                "sample_interval_ms": sample_interval_ms,
                "noise_config": {
                    "packet_loss_rate": config.packet_loss_rate,
                    "spike_probability": config.spike_probability,
                    "spike_magnitude_pct": config.spike_magnitude_pct,
                    "dropout_probability": config.dropout_probability,
                    "dropout_duration_s": config.dropout_duration_s,
                    "clock_drift_ms": config.clock_drift_ms,
                },
                "privacy_boundary": "No input rows or identifiers are copied to output; only a figure, aggregate counts, configuration, and input hash are emitted.",
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    for artifact in (
        out_dir / "noise_dropout_injection.png",
        out_dir / "noise_injection_summary.csv",
        out_dir / "noise_injection_provenance.json",
    ):
        os.chmod(artifact, 0o600)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Synthetic CSV with the five required signal columns")
    parser.add_argument("--out-dir", type=Path, default=ROOT / ".runtime/presentation/noise_injection")
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--sample-interval-ms", type=int, default=1_000)
    parser.add_argument("--noise-seed", type=int, default=2_000)
    parser.add_argument("--packet-loss", type=float, default=0.02)
    parser.add_argument("--spike-probability", type=float, default=0.03)
    parser.add_argument("--spike-magnitude-pct", type=float, default=0.15)
    parser.add_argument("--dropout-probability", type=float, default=0.01)
    parser.add_argument("--dropout-duration-s", type=float, default=8.0)
    parser.add_argument("--clock-drift-ms", type=int, default=50)
    args = parser.parse_args()
    config = NoiseConfig(
        packet_loss_rate=args.packet_loss,
        spike_probability=args.spike_probability,
        spike_magnitude_pct=args.spike_magnitude_pct,
        dropout_probability=args.dropout_probability,
        dropout_duration_s=args.dropout_duration_s,
        clock_drift_ms=args.clock_drift_ms,
    )
    summary = render(
        args.input,
        args.out_dir,
        config=config,
        seed=args.noise_seed,
        sample_interval_ms=args.sample_interval_ms,
        samples=args.samples,
    )
    dropped = sum(row["dropped"] for row in summary)
    spiked = sum(row["spiked"] for row in summary)
    print(f"Wrote presentation assets to {args.out_dir} (dropped={dropped}, spiked={spiked})")


if __name__ == "__main__":
    main()
