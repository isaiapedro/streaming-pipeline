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
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    missing = [signal for signal in SIGNALS if not rows or signal not in rows[0]]
    if missing:
        raise ValueError(f"Reference CSV is missing columns: {', '.join(missing)}")
    return {signal: np.array([float(row[signal]) for row in rows], dtype=float) for signal in SIGNALS}


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
    for axis, signal in zip(axes, SIGNALS):
        kl = kl_synthetic_reference(reference[signal], synthetic[signal])
        metrics.append({"signal": signal, "kl_synthetic_reference": f"{kl:.8f}", "bins": 30})
        axis.hist(reference[signal], bins=30, density=True, alpha=.55, label=f"reference ({source_id})")
        axis.hist(synthetic[signal], bins=30, density=True, alpha=.55, label="synthetic")
        axis.set_title(f"{signal}: KL={kl:.4f}")
        axis.set_ylabel("Density")
        axis.legend()
    fig.savefig(out_dir / "synthetic_vs_reference.png", dpi=180)
    plt.close(fig)
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
                "privacy_boundary": "Only aggregate histogram figures and KL metrics are emitted; source rows remain external.",
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
