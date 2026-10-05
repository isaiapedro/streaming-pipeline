#!/usr/bin/env python3
"""Replay governed benchmark rows to InfluxDB for a live Grafana demonstration.

This command does not execute or alter the benchmark and must not be used as
experimental evidence. It publishes the already-generated aggregate rows at a
human-visible cadence so an audience can watch Grafana update in real time.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import math
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path

from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import INFLUX_BUCKET, INFLUX_ORG, INFLUX_TOKEN, INFLUX_URL


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "benchmark_results.csv"
APPROACHES = {"A", "B", "C"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_FIELDS = {"run_id", "scenario", "signal_seed", "noise_seed", "approach"}
NON_NUMERIC_FIELDS = {"run_id", "scenario", "approach"}
INTEGER_FIELDS = {
    "signal_seed",
    "noise_seed",
    "duration_s",
    "scoring_detection_latency_ms",
    "alarm_observation_count",
    "alarm_episode_count",
    "time_in_alarm_ms",
}
BENCHMARK_MEASUREMENT = "benchmark_demo_v2"
PROGRESS_MEASUREMENT = "benchmark_demo_progress_v2"


def load_cells(path: Path) -> list[list[dict[str, str]]]:
    """Load and validate complete A/B/C cells while preserving CSV order."""

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED_FIELDS.issubset(reader.fieldnames):
            missing = sorted(REQUIRED_FIELDS.difference(reader.fieldnames or []))
            raise ValueError(f"benchmark CSV is missing required columns: {', '.join(missing)}")
        cells: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        for row in reader:
            run_id = row["run_id"].strip()
            if not run_id:
                raise ValueError("benchmark CSV contains an empty run_id")
            cells.setdefault(run_id, []).append(row)

    for run_id, rows in cells.items():
        approaches = {row["approach"] for row in rows}
        scenarios = {row["scenario"] for row in rows}
        if len(rows) != 3 or approaches != APPROACHES or len(scenarios) != 1:
            raise ValueError(f"benchmark cell {run_id} is not one complete A/B/C comparison")
    if not cells:
        raise ValueError("benchmark CSV contains no result rows")
    return list(cells.values())


def _numeric_fields(row: dict[str, str]) -> dict[str, float | int]:
    values: dict[str, float | int] = {}
    for name, raw in row.items():
        if name in NON_NUMERIC_FIELDS or raw is None or not raw.strip():
            continue
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"benchmark field {name} must be numeric") from exc
        if not math.isfinite(value):
            raise ValueError(f"benchmark field {name} must be finite")
        if name in INTEGER_FIELDS:
            if not value.is_integer():
                raise ValueError(f"benchmark integer field {name} contains a fractional value")
            values[name] = int(value)
        else:
            # InfluxDB fixes one type per measurement/field. Preserve every
            # rate, percentage, and continuous metric as float even when a
            # particular CSV value happens to be 0.0 or 1.0.
            values[name] = value
    return values


def points_for_cell(
    rows: list[dict[str, str]],
    *,
    session: str,
    source_sha256: str,
    completed_cells: int,
    total_cells: int,
    timestamp_ns: int,
) -> list[Point]:
    """Create presentation-only points for one completed comparison cell."""

    points = []
    for row in rows:
        point = (
            Point(BENCHMARK_MEASUREMENT)
            .tag("presentation_session", session)
            .tag("evidence_mode", "replay")
            .tag("source_sha256", source_sha256)
            .tag("run_id", row["run_id"])
            .tag("scenario", row["scenario"])
            .tag("approach", row["approach"])
        )
        for name, value in _numeric_fields(row).items():
            point = point.field(name, value)
        points.append(point.time(timestamp_ns))

    progress = (
        Point(PROGRESS_MEASUREMENT)
        .tag("presentation_session", session)
        .tag("evidence_mode", "replay")
        .tag("source_sha256", source_sha256)
        .tag("latest_scenario", rows[0]["scenario"])
        .field("completed_cells", completed_cells)
        .field("total_cells", total_cells)
        .field("completion_pct", 100.0 * completed_cells / total_cells)
        .time(timestamp_ns)
    )
    return [*points, progress]


async def replay(path: Path, session: str, interval_s: float, dry_run: bool) -> None:
    if interval_s < 0:
        raise ValueError("interval must be non-negative")
    if not IDENTIFIER.fullmatch(session):
        raise ValueError("session must use 1-128 letters, digits, dots, underscores, or hyphens")
    cells = load_cells(path)
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    if dry_run:
        for index, rows in enumerate(cells, 1):
            points_for_cell(
                rows,
                session=session,
                source_sha256=source_sha256,
                completed_cells=index,
                total_cells=len(cells),
                timestamp_ns=time.time_ns(),
            )
        print(f"Validated {len(cells)} complete A/B/C cells for session {session}")
        return

    if not all((INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET)):
        raise RuntimeError("INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, and INFLUX_BUCKET are required")

    async with InfluxDBClientAsync(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        write_api = client.write_api()
        for index, rows in enumerate(cells, 1):
            points = points_for_cell(
                rows,
                session=session,
                source_sha256=source_sha256,
                completed_cells=index,
                total_cells=len(cells),
                timestamp_ns=time.time_ns(),
            )
            await write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
            print(f"[{index}/{len(cells)}] {rows[0]['scenario']} — A/B/C displayed", flush=True)
            if index != len(cells) and interval_s:
                await asyncio.sleep(interval_s)

    print(f"Replay complete. Select presentation session '{session}' in Grafana.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between benchmark cells")
    parser.add_argument("--session", default=f"demo-{int(time.time())}")
    parser.add_argument("--dry-run", action="store_true", help="Validate locally without contacting InfluxDB")
    args = parser.parse_args()
    asyncio.run(replay(args.input, args.session, args.interval, args.dry_run))


if __name__ == "__main__":
    main()
