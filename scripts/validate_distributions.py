#!/usr/bin/env python3
"""Compare synthetic vital distributions with an approved reference CSV.

The input CSV must contain numeric columns named heart_rate, spo2,
systolic_bp, respiratory_rate, and temperature. It is intentionally supplied
at run time: no clinical source data belongs in this repository.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

SIGNALS = ("heart_rate", "spo2", "systolic_bp", "respiratory_rate", "temperature")
SIGNAL_LABELS = ("Heart rate", "SpO2", "Systolic BP", "Respiratory rate", "Temperature")


def kl_synthetic_reference(reference: np.ndarray, synthetic: np.ndarray, bins: int = 30) -> float:
    """Return KL(P_synthetic || P_reference) over shared histogram bins.

    KL divergence is directional. This order matches the declared health-corpus
    validation target and must be preserved in labels and provenance.
    """

    low, high = min(reference.min(), synthetic.min()), max(reference.max(), synthetic.max())
    if low == high:
        return 0.0
    ref, edges = np.histogram(reference, bins=bins, range=(low, high), density=False)
    syn, _ = np.histogram(synthetic, bins=edges, density=False)
    epsilon = 1e-12
    ref = (ref.astype(float) + epsilon) / (ref.sum() + epsilon * len(ref))
    syn = (syn.astype(float) + epsilon) / (syn.sum() + epsilon * len(syn))
    return float(np.sum(syn * np.log(syn / ref)))


# Compatibility for callers that imported the original function name. The
# direction is intentionally the documented synthetic-to-reference direction.
kl_divergence = kl_synthetic_reference


def load_reference(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Input CSV not found: {path}. Replace documentation placeholders with a real local path."
        )
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing = [signal for signal in SIGNALS if not rows or signal not in rows[0]]
    if missing:
        raise ValueError(f"Reference CSV is missing columns: {', '.join(missing)}")
    return {signal: np.array([float(row[signal]) for row in rows], dtype=float) for signal in SIGNALS}


def correlation_matrix(values: dict[str, np.ndarray]) -> np.ndarray:
    """Return a finite Pearson matrix using complete rows across all signals."""

    matrix = np.column_stack([values[signal] for signal in SIGNALS])
    complete = matrix[np.isfinite(matrix).all(axis=1)]
    if len(complete) < 2:
        raise ValueError("At least two complete finite rows are required for correlation")
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.corrcoef(complete, rowvar=False)
    # A constant signal has undefined Pearson correlation. Retain the useful
    # diagonal identity and label unavailable cross-signal cells as NaN.
    np.fill_diagonal(result, 1.0)
    return result


def _plot_kl(metrics: list[dict], path: Path) -> None:
    values = [float(row["kl_synthetic_reference"]) for row in metrics]
    fig, axis = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
    bars = axis.barh(SIGNAL_LABELS, values, color="#4C78A8")
    axis.bar_label(bars, labels=[f"{value:.4f}" for value in values], padding=4)
    axis.set(
        xlabel="KL divergence, synthetic → reference (lower means closer)",
        title="Per-signal distribution divergence",
    )
    axis.grid(axis="x", alpha=0.2)
    axis.text(
        0,
        -0.18,
        "KL is directional and has no universal pass/fail threshold; interpret with the overlays.",
        transform=axis.transAxes,
        fontsize=9,
    )
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _plot_correlations(reference: np.ndarray, synthetic: np.ndarray, path: Path) -> None:
    difference = synthetic - reference
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), constrained_layout=True)
    panels = (
        (reference, "Reference correlation", -1.0, 1.0),
        (synthetic, "Synthetic correlation", -1.0, 1.0),
        (difference, "Synthetic − reference", -2.0, 2.0),
    )
    for axis, (matrix, title, low, high) in zip(axes, panels):
        image = axis.imshow(matrix, cmap="coolwarm", vmin=low, vmax=high)
        axis.set_title(title)
        axis.set_xticks(range(len(SIGNALS)), SIGNAL_LABELS, rotation=45, ha="right")
        axis.set_yticks(range(len(SIGNALS)), SIGNAL_LABELS)
        for row in range(len(SIGNALS)):
            for column in range(len(SIGNALS)):
                value = matrix[row, column]
                label = "N/A" if np.isnan(value) else f"{value:.2f}"
                axis.text(column, row, label, ha="center", va="center", fontsize=8)
        fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    fig.suptitle("Inter-signal Pearson correlation structure")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _write_correlations(reference: np.ndarray, synthetic: np.ndarray, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["signal_x", "signal_y", "reference_pearson_r", "synthetic_pearson_r", "difference"],
        )
        writer.writeheader()
        for row, signal_x in enumerate(SIGNALS):
            for column, signal_y in enumerate(SIGNALS):
                ref_value = reference[row, column]
                syn_value = synthetic[row, column]
                writer.writerow({
                    "signal_x": signal_x,
                    "signal_y": signal_y,
                    "reference_pearson_r": "" if np.isnan(ref_value) else f"{ref_value:.8f}",
                    "synthetic_pearson_r": "" if np.isnan(syn_value) else f"{syn_value:.8f}",
                    "difference": "" if np.isnan(ref_value) or np.isnan(syn_value) else f"{syn_value - ref_value:.8f}",
                })


def validate(
    reference_path: Path,
    synthetic_path: Path,
    out_dir: Path,
    source_id: str,
    transformation_method: str,
) -> list[dict]:
    if not source_id.strip() or source_id.strip().lower() in {"unknown", "unset"}:
        raise ValueError("A non-sensitive approved reference --source-id is required")
    if not transformation_method.strip():
        raise ValueError("--transformation-method must describe how the reference CSV was derived")
    reference, synthetic = load_reference(reference_path), load_reference(synthetic_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = []
    fig, axes = plt.subplots(len(SIGNALS), 1, figsize=(10, 14), constrained_layout=True)
    reference_label = f"reference ({source_id.replace('_', ' ')})"
    synthetic_handle = reference_handle = None
    for axis, signal in zip(axes, SIGNALS):
        kl = kl_synthetic_reference(reference[signal], synthetic[signal])
        metrics.append({"signal": signal, "kl_synthetic_reference": f"{kl:.8f}", "bins": 30})
        reference_handle = axis.hist(reference[signal], bins=30, density=True, alpha=.55, label=reference_label)[2][0]
        synthetic_handle = axis.hist(synthetic[signal], bins=30, density=True, alpha=.55, label="synthetic")[2][0]
        axis.set_title(f"{SIGNAL_LABELS[SIGNALS.index(signal)]} — KL={kl:.4f}", fontsize=16, fontweight="bold")
        axis.set_ylabel("Density", fontsize=14)
        axis.tick_params(labelsize=12)
    axes[0].legend(
        [reference_handle, synthetic_handle],
        [reference_label, "synthetic"],
        loc="upper right",
        fontsize=11,
        frameon=True,
    )
    fig.savefig(out_dir / "synthetic_vs_reference.png", dpi=180)
    plt.close(fig)
    _plot_kl(metrics, out_dir / "kl_divergence.png")
    reference_correlation = correlation_matrix(reference)
    synthetic_correlation = correlation_matrix(synthetic)
    _plot_correlations(
        reference_correlation,
        synthetic_correlation,
        out_dir / "inter_signal_correlation.png",
    )
    _write_correlations(
        reference_correlation,
        synthetic_correlation,
        out_dir / "correlation_matrix.csv",
    )
    with (out_dir / "kl_divergence.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["signal", "kl_synthetic_reference", "bins"])
        writer.writeheader()
        writer.writerows(metrics)
    with (out_dir / "provenance.json").open("w") as handle:
        json.dump(
            {
                "approved_reference_source_id": source_id,
                "transformation_method": transformation_method,
                "reference_rows": len(next(iter(reference.values()))),
                "synthetic_rows": len(next(iter(synthetic.values()))),
                "kl_definition": "KL(P_synthetic || P_reference) using 30 shared histogram bins and additive smoothing epsilon=1e-12",
                "kl_direction": "synthetic_to_reference",
                "correlation_definition": "Pearson correlation over complete finite rows within each dataset",
                "privacy_boundary": "Only aggregate distribution/correlation figures and metrics are emitted; source rows remain external.",
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--synthetic", required=True, type=Path,
                        help="CSV generated from the benchmark with the same five columns")
    parser.add_argument("--out-dir", type=Path, default=Path("distribution_validation"))
    parser.add_argument("--source-id", required=True,
                        help="Non-sensitive identifier for the approved external reference source")
    parser.add_argument("--transformation-method", required=True,
                        help="How the external source was transformed into the input columns")
    args = parser.parse_args()
    validate(
        args.reference,
        args.synthetic,
        args.out_dir,
        args.source_id,
        args.transformation_method,
    )


if __name__ == "__main__":
    main()
