#!/usr/bin/env python3
"""Audit required telemetry tags without exporting identifiers or measurements.

The auditor accepts either a local Influx CSV export or an explicit live query.
Its output contains coverage counts and percentages only. It never copies tag
values, patient identifiers, timestamps, or measured vital values.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

REQUIRED_TAGS = (
    "patient_id",
    "schema_version",
    "pipeline_version",
    "threshold_version",
    "scoring_approach",
    "scenario_id",
    "transport",
)
ALLOWED_MEASUREMENTS = {"patient_vitals", "alarms"}
ALLOWED_TRANSPORTS = {"nats", "mqtt", "kafka", "in_process"}
VERSION_TAGS = ("schema_version", "pipeline_version", "threshold_version")
_UNKNOWN_VERSION_VALUES = {"", "unknown", "unset", "none", "null", "n/a", "na"}
_RANGE_PATTERN = re.compile(r"^[1-9][0-9]*[smhdw]$")


def _coverage(total: int, complete: int, present: Mapping[str, int]) -> dict:
    return {
        "records": total,
        "complete_records": complete,
        "complete_pct": (100.0 * complete / total) if total else None,
        "tag_coverage": {
            tag: {
                "present": present.get(tag, 0),
                "pct": (100.0 * present.get(tag, 0) / total) if total else None,
            }
            for tag in REQUIRED_TAGS
        },
    }


def audit_rows(rows: Iterable[Mapping[str, object]], source: str) -> dict:
    """Return aggregate tag coverage; never retain any observed tag value."""

    totals: dict[str, int] = defaultdict(int)
    complete: dict[str, int] = defaultdict(int)
    present: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    transport_totals: dict[str, int] = defaultdict(int)
    transport_complete: dict[str, int] = defaultdict(int)
    transport_present: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    transport_measurements: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    version_values: dict[str, set[str]] = {tag: set() for tag in VERSION_TAGS}
    unknown_versions: dict[str, int] = defaultdict(int)
    ignored = 0
    for row in rows:
        measurement = str(row.get("_measurement") or row.get("measurement") or "unknown")
        if measurement not in ALLOWED_MEASUREMENTS:
            ignored += 1
            continue
        totals[measurement] += 1
        flags = {}
        for tag in REQUIRED_TAGS:
            value = row.get(tag)
            flags[tag] = value is not None and bool(str(value).strip())
            if tag in VERSION_TAGS and str(value or "").strip().lower() in _UNKNOWN_VERSION_VALUES:
                flags[tag] = False
            present[measurement][tag] += int(flags[tag])
        raw_transport = str(row.get("transport") or "").strip().lower()
        transport = raw_transport if raw_transport in ALLOWED_TRANSPORTS else "unknown"
        transport_totals[transport] += 1
        transport_measurements[transport][measurement] += 1
        for tag in REQUIRED_TAGS:
            transport_present[transport][tag] += int(flags[tag])
        transport_complete[transport] += int(all(flags.values()))
        for tag in VERSION_TAGS:
            value = str(row.get(tag) or "").strip()
            if value.lower() in _UNKNOWN_VERSION_VALUES:
                unknown_versions[tag] += 1
            else:
                version_values[tag].add(value)
        complete[measurement] += int(all(flags.values()))

    by_measurement = {}
    for measurement in sorted(ALLOWED_MEASUREMENTS):
        total = totals[measurement]
        by_measurement[measurement] = _coverage(total, complete[measurement], present[measurement])
    by_transport = {}
    for transport in sorted(transport_totals):
        summary = _coverage(
            transport_totals[transport], transport_complete[transport], transport_present[transport]
        )
        summary["measurements"] = {
            measurement: transport_measurements[transport][measurement]
            for measurement in sorted(ALLOWED_MEASUREMENTS)
        }
        by_transport[transport] = summary
    total_records = sum(totals.values())
    total_complete = sum(complete.values())
    overall_present = {
        tag: sum(present[measurement][tag] for measurement in ALLOWED_MEASUREMENTS)
        for tag in REQUIRED_TAGS
    }
    if not total_records:
        status = "unexecuted"
    elif total_complete == total_records:
        status = "passed"
    else:
        status = "incomplete"
    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_classification": "aggregate tag-presence coverage; no tag values or measured values",
        "source": source,
        "status": status,
        "records": total_records,
        "complete_records": total_complete,
        "complete_pct": (100.0 * total_complete / total_records) if total_records else None,
        "tag_coverage": _coverage(total_records, total_complete, overall_present)["tag_coverage"],
        "ignored_records": ignored,
        "required_tags": list(REQUIRED_TAGS),
        "by_measurement": by_measurement,
        "by_transport": by_transport,
        "versions": {
            tag: {
                "distinct_known_values": len(version_values[tag]),
                "unknown_records": unknown_versions[tag],
                "mixed_known_values": len(version_values[tag]) > 1,
            }
            for tag in VERSION_TAGS
        },
        "has_unknown_versions": any(unknown_versions.values()),
        "has_mixed_versions": any(len(values) > 1 for values in version_values.values()),
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        if not ({"_measurement", "measurement"} & fields):
            raise ValueError("input CSV must contain _measurement or measurement")
        return list(reader)


async def _live_rows(range_window: str) -> list[dict]:
    if not _RANGE_PATTERN.fullmatch(range_window):
        raise ValueError("range must be a positive Flux duration such as 1h or 7d")
    from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
    from config.settings import INFLUX_BUCKET, INFLUX_ORG, INFLUX_TOKEN, INFLUX_URL

    if not all((INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET)):
        raise RuntimeError("live audit requires INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, and INFLUX_BUCKET")
    query = f'''from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{range_window})
  |> filter(fn: (r) => r._measurement == "patient_vitals" or r._measurement == "alarms")
  |> keep(columns: ["_measurement", "patient_id", "schema_version", "pipeline_version", "threshold_version", "scoring_approach", "scenario_id", "transport"])'''
    async with InfluxDBClientAsync(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        tables = await client.query_api().query(query=query, org=INFLUX_ORG)
    return [record.values for table in tables for record in table.records]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-csv", type=Path, help="Influx CSV export; read-only and never copied")
    source.add_argument("--live", action="store_true", help="query the configured InfluxDB endpoint")
    parser.add_argument("--range", default="1h", help="live Flux range, for example 1h or 7d")
    parser.add_argument("--output", type=Path, default=Path("evidence/traceability_audit.json"))
    parser.add_argument("--require-complete", action="store_true", help="exit non-zero unless every audited record has every required tag")
    args = parser.parse_args()

    if args.live:
        rows = asyncio.run(_live_rows(args.range))
        source_name = f"live_influx:{args.range}"
    else:
        rows = _csv_rows(args.input_csv)
        source_name = "operator_supplied_influx_csv"
    result = audit_rows(rows, source_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Wrote aggregate traceability audit for {result['records']} records to {args.output}")
    if args.require_complete and result["status"] != "passed":
        parser.exit(2, f"Traceability audit failed closed: status={result['status']}\n")


if __name__ == "__main__":
    main()
