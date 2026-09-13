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
_RANGE_PATTERN = re.compile(r"^[1-9][0-9]*[smhdw]$")


def audit_rows(rows: Iterable[Mapping[str, object]], source: str) -> dict:
    """Return aggregate tag coverage; never retain any observed tag value."""

    totals: dict[str, int] = defaultdict(int)
    complete: dict[str, int] = defaultdict(int)
    present: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
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
            present[measurement][tag] += int(flags[tag])
        complete[measurement] += int(all(flags.values()))

    by_measurement = {}
    for measurement in sorted(ALLOWED_MEASUREMENTS):
        total = totals[measurement]
        by_measurement[measurement] = {
            "records": total,
            "complete_records": complete[measurement],
            "complete_pct": (100.0 * complete[measurement] / total) if total else None,
            "tag_coverage": {
                tag: {
                    "present": present[measurement][tag],
                    "pct": (100.0 * present[measurement][tag] / total) if total else None,
                }
                for tag in REQUIRED_TAGS
            },
        }
    total_records = sum(totals.values())
    total_complete = sum(complete.values())
    if not total_records:
        status = "no_records"
    elif total_complete == total_records:
        status = "passed"
    else:
        status = "incomplete"
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy_classification": "aggregate tag-presence coverage; no tag values or measured values",
        "source": source,
        "status": status,
        "records": total_records,
        "complete_records": total_complete,
        "complete_pct": (100.0 * total_complete / total_records) if total_records else None,
        "ignored_records": ignored,
        "required_tags": list(REQUIRED_TAGS),
        "by_measurement": by_measurement,
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
