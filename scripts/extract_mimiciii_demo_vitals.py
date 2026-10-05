#!/usr/bin/env python3
"""Create an identifier-free five-signal reference CSV from MIMIC-III Demo.

The input is the official MIMIC-III Clinical Database Demo v1.4 ZIP. Relevant
CHARTEVENTS are aggregated to six-hour medians per ICU stay, only complete
five-signal windows are retained, and identifiers/timestamps are not emitted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import statistics
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_URL = "https://physionet.org/content/mimiciii-demo/1.4/"
SOURCE_ID = "PHYSIONET_MIMICIII_DEMO_1_4"
METHOD_ID = "mimiciii-demo-chartevents-6h-median-complete-case-v1"
BIN_HOURS = 6
SIGNALS = ("heart_rate", "spo2", "systolic_bp", "respiratory_rate", "temperature")

# Canonical CareVue and MetaVision CHARTEVENTS ITEMIDs used for these vitals.
ITEM_SIGNALS = {
    211: "heart_rate",
    220045: "heart_rate",
    646: "spo2",
    220277: "spo2",
    51: "systolic_bp",
    442: "systolic_bp",
    455: "systolic_bp",
    6701: "systolic_bp",
    220050: "systolic_bp",
    220179: "systolic_bp",
    615: "respiratory_rate",
    618: "respiratory_rate",
    220210: "respiratory_rate",
    224690: "respiratory_rate",
    676: "temperature",   # Celsius
    223762: "temperature",
    678: "temperature",   # Fahrenheit; converted below
    223761: "temperature",
}
FAHRENHEIT_ITEMIDS = {678, 223761}
PLAUSIBLE_RANGES = {
    "heart_rate": (20.0, 250.0),
    "spo2": (50.0, 100.0),
    "systolic_bp": (40.0, 300.0),
    "respiratory_rate": (1.0, 80.0),
    "temperature": (25.0, 45.0),
}


def _chartevents_member(archive: zipfile.ZipFile) -> str:
    matches = [name for name in archive.namelist() if Path(name).name.upper() == "CHARTEVENTS.CSV"]
    if len(matches) != 1:
        raise ValueError(f"Expected one CHARTEVENTS.csv in archive, found {len(matches)}")
    return matches[0]


def extract(input_zip: Path, output_csv: Path, provenance_path: Path) -> int:
    if not input_zip.is_file():
        raise FileNotFoundError(f"Official MIMIC-III demo ZIP not found: {input_zip}")

    grouped: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    accepted_events = 0
    accepted_by_signal: Counter[str] = Counter()
    with zipfile.ZipFile(input_zip) as archive:
        member = _chartevents_member(archive)
        with archive.open(member) as binary:
            rows = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8", newline=""))
            for row in rows:
                row = {key.upper(): value for key, value in row.items()}
                try:
                    item_id = int(row["ITEMID"])
                    signal = ITEM_SIGNALS[item_id]
                    value = float(row["VALUENUM"])
                except (KeyError, TypeError, ValueError):
                    continue
                if row.get("ERROR", "").strip() == "1":
                    continue
                if item_id in FAHRENHEIT_ITEMIDS:
                    value = (value - 32.0) * 5.0 / 9.0
                low, high = PLAUSIBLE_RANGES[signal]
                if not low <= value <= high:
                    continue
                stay = row.get("ICUSTAY_ID") or row.get("HADM_ID") or row.get("SUBJECT_ID")
                charttime = row.get("CHARTTIME", "")
                if not stay or len(charttime) < 13:
                    continue
                # Identifier and time are used only as an in-memory aggregation
                # key and are deliberately absent from the output.
                try:
                    hour_bin = int(charttime[11:13]) // BIN_HOURS
                except ValueError:
                    continue
                key = (row.get("SUBJECT_ID", ""), stay, f"{charttime[:10]}:{hour_bin}")
                grouped[key][signal].append(value)
                accepted_events += 1
                accepted_by_signal[signal] += 1

    aligned = [
        {signal: statistics.median(values[signal]) for signal in SIGNALS}
        for values in grouped.values()
        if all(values.get(signal) for signal in SIGNALS)
    ]
    if not aligned:
        groups_by_signal = {
            signal: sum(bool(values.get(signal)) for values in grouped.values())
            for signal in SIGNALS
        }
        raise ValueError(
            "No complete five-signal windows were found; "
            f"accepted_events={dict(accepted_by_signal)}, groups={groups_by_signal}"
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(output_csv.parent, 0o700)
    with output_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIGNALS)
        writer.writeheader()
        writer.writerows(aligned)
    os.chmod(output_csv, 0o600)

    provenance = {
        "source": SOURCE_ID,
        "source_url": SOURCE_URL,
        "license": "Open Data Commons Open Database License v1.0",
        "method": METHOD_ID,
        "aggregation_window_hours": BIN_HOURS,
        "input_zip_sha256": hashlib.sha256(input_zip.read_bytes()).hexdigest(),
        "output_csv_sha256": hashlib.sha256(output_csv.read_bytes()).hexdigest(),
        "accepted_vital_events": accepted_events,
        "complete_window_rows": len(aligned),
        "signals": list(SIGNALS),
        "itemids": {signal: sorted(key for key, value in ITEM_SIGNALS.items() if value == signal) for signal in SIGNALS},
        "privacy_boundary": "Output contains only five six-hour aggregate values; patient/stay identifiers and timestamps are omitted.",
        "limitation": "The demo cohort contains 100 patients selected from patients who eventually died and is not population-representative.",
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    with provenance_path.open("w") as handle:
        json.dump(provenance, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(provenance_path, 0o600)
    return len(aligned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    args = parser.parse_args()
    count = extract(args.input_zip, args.output, args.provenance)
    print(f"Wrote {count} identifier-free complete six-hour rows to {args.output}")
    print(f"Source ID: {SOURCE_ID}")
    print(f"Transformation method: {METHOD_ID}")


if __name__ == "__main__":
    main()
