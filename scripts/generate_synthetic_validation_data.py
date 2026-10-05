#!/usr/bin/env python3
"""Generate a deterministic, identifier-free synthetic validation extract.

This is an aligned baseline grid for visualization and external-reference
comparison. It does not reproduce the asynchronous runtime sampling cadence,
and it supports no realism claim until its cohort/alignment method is matched
to an approved reference extraction protocol.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.generators.blood_pressure import BloodPressureGenerator
from data.generators.correlation import correlated_delta
from data.generators.heart_rate import HeartRateGenerator
from data.generators.respiratory_rate import RespiratoryRateGenerator
from data.generators.spo2 import SpO2Generator
from data.generators.temperature import TemperatureGenerator
from scripts.validate_distributions import SIGNALS


ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ROOT / "data/profiles"
DEFAULT_OUTPUT = ROOT / ".runtime/presentation/synthetic-aligned.csv"
DEFAULT_START_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z


def _profile_rows(profile: dict, rows: int, seed: int, start_ms: int, interval_ms: int):
    generators = {
        "heart_rate": HeartRateGenerator(profile, seed),
        "respiratory_rate": RespiratoryRateGenerator(profile, seed + 1),
        "spo2": SpO2Generator(profile, seed + 2),
        "blood_pressure": BloodPressureGenerator(profile, seed + 3),
        "temperature": TemperatureGenerator(profile, seed + 4),
    }
    latest: dict[str, float] = {}
    baselines = profile["baselines"]
    copd_flag = bool(profile.get("copd_flag", False))
    for index in range(rows):
        timestamp_ms = start_ms + index * interval_ms
        heart_rate = float(generators["heart_rate"].generate(timestamp_ms))
        latest["heart_rate"] = heart_rate
        respiratory_rate = float(generators["respiratory_rate"].generate(timestamp_ms))
        latest["respiratory_rate"] = respiratory_rate
        spo2 = float(generators["spo2"].generate(timestamp_ms))
        spo2 += correlated_delta("spo2", latest, baselines, copd_flag)
        latest["spo2"] = spo2
        blood_pressure = generators["blood_pressure"].generate(timestamp_ms)
        systolic_bp = float(blood_pressure["systolic"])
        latest["systolic_bp"] = systolic_bp
        latest["diastolic_bp"] = float(blood_pressure["diastolic"])
        temperature = float(generators["temperature"].generate(timestamp_ms))
        temperature += correlated_delta("temperature", latest, baselines, copd_flag)
        latest["temperature"] = temperature
        yield {
            "heart_rate": round(heart_rate, 4),
            "spo2": round(spo2, 4),
            "systolic_bp": round(systolic_bp, 4),
            "respiratory_rate": round(respiratory_rate, 4),
            "temperature": round(temperature, 4),
        }


def generate(output: Path, rows_per_profile: int, seed: int, start_ms: int, interval_ms: int) -> dict:
    if rows_per_profile < 2:
        raise ValueError("rows per profile must be at least 2")
    if interval_ms < 1:
        raise ValueError("sample interval must be positive")
    profile_paths = sorted(PROFILES_DIR.glob("P-*.json"))
    if not profile_paths:
        raise RuntimeError("no synthetic profiles are available")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(output.parent, 0o700)
    except OSError:
        pass
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIGNALS)
        writer.writeheader()
        for profile_index, profile_path in enumerate(profile_paths):
            profile = json.loads(profile_path.read_text())
            writer.writerows(
                _profile_rows(
                    profile,
                    rows_per_profile,
                    seed + profile_index * 100,
                    start_ms,
                    interval_ms,
                )
            )
    os.chmod(output, 0o600)
    metadata = {
        "method": "aligned-baseline-grid-v1",
        "profile_count": len(profile_paths),
        "rows_per_profile": rows_per_profile,
        "total_rows": len(profile_paths) * rows_per_profile,
        "signal_seed_base": seed,
        "start_timestamp_ms": start_ms,
        "sample_interval_ms": interval_ms,
        "contains_identifiers": False,
        "runtime_cadence_reproduced": False,
        "claim_boundary": "Presentation/validation input only; external realism requires approved cohort and alignment methodology.",
        "csv_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    metadata_path = output.with_suffix(".provenance.json")
    with metadata_path.open("w") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(metadata_path, 0o600)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rows-per-profile", type=int, default=1_440)
    parser.add_argument("--signal-seed", type=int, default=1_000)
    parser.add_argument("--start-timestamp-ms", type=int, default=DEFAULT_START_MS)
    parser.add_argument("--sample-interval-ms", type=int, default=60_000)
    args = parser.parse_args()
    metadata = generate(
        args.output,
        args.rows_per_profile,
        args.signal_seed,
        args.start_timestamp_ms,
        args.sample_interval_ms,
    )
    print(
        f"Wrote {metadata['total_rows']} identifier-free synthetic rows to {args.output} "
        f"using {metadata['method']}"
    )


if __name__ == "__main__":
    main()
