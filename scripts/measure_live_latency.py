#!/usr/bin/env python3
"""Measure live publish-to-consume and publish-to-storage latency.

This harness uses the canonical Protobuf envelope and an isolated JetStream
subject. It emits aggregate statistics only. Storage latency is recorded only
after the InfluxDB write API confirms a successful write; use ``--skip-storage``
to record it explicitly as unavailable.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import nats
from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import (
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_TOKEN,
    INFLUX_URL,
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    nats_connection_options,
)
from schema import vitals_pb2
from scripts.run_scale_tier import machine_context


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def summarize(metric: str, values: list[float], status: str, notes: str) -> dict:
    return {
        "metric": metric,
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p99_ms": percentile(values, 0.99),
        "method": "live_measured" if status == "executed" else "unavailable",
        "status": status,
        "notes": notes,
    }


async def measure(count: int, skip_storage: bool, timeout_s: float) -> dict:
    if count < 1:
        raise ValueError("count must be positive")
    if not skip_storage and not all((INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET)):
        raise RuntimeError("InfluxDB configuration is required unless --skip-storage is used")

    run_id = f"latency-{time.time_ns()}"
    stream = f"EVIDENCE_{time.time_ns()}"
    subject = f"evidence.latency.{run_id}"
    consume_latencies: list[float] = []
    storage_latencies: list[float] = []
    nc = await nats.connect(**nats_connection_options())
    js = nc.jetstream()
    influx = None
    write_api = None
    try:
        await js.add_stream(name=stream, subjects=[subject], storage="memory", max_msgs=count + 10)
        sub = await js.pull_subscribe(subject, durable="EVIDENCE_LATENCY", stream=stream)
        if not skip_storage:
            influx = InfluxDBClientAsync(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
            write_api = influx.write_api()

        for sequence in range(count):
            sent_ms = time.time_ns() // 1_000_000
            payload = vitals_pb2.VitalSign(
                patient_id="P-EVIDENCE",
                signal_type="heart_rate",
                scalar_value=88.4,
                timestamp_ms=sent_ms,
                schema_version=SCHEMA_VERSION,
                pipeline_version=PIPELINE_VERSION,
                scenario_id="live_latency",
            )
            await js.publish(subject, payload.SerializeToString())
            messages = await sub.fetch(1, timeout=timeout_s)
            received = vitals_pb2.VitalSign.FromString(messages[0].data)
            consumed_ms = time.time_ns() / 1_000_000
            consume_latencies.append(consumed_ms - received.timestamp_ms)

            if write_api is not None:
                point = (
                    Point("evidence_latency_probe")
                    .tag("run_id", run_id)
                    .tag("schema_version", received.schema_version)
                    .tag("pipeline_version", received.pipeline_version)
                    .field("sequence", sequence)
                    .time(received.timestamp_ms * 1_000_000)
                )
                await write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
                storage_latencies.append(time.time_ns() / 1_000_000 - received.timestamp_ms)
            await messages[0].ack()
    finally:
        try:
            await js.delete_stream(stream)
        except Exception:
            pass
        await nc.close()
        if influx is not None:
            await influx.close()

    results = [
        summarize("publish_to_consume", consume_latencies, "executed", "JetStream fetch and Protobuf decode completed"),
        summarize(
            "publish_to_successful_storage",
            storage_latencies,
            "unexecuted" if skip_storage else "executed",
            "not requested (--skip-storage)" if skip_storage else "InfluxDB write API returned successfully",
        ),
    ]
    return {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "message_count": count,
        "clock_method": "system wall clock, Unix epoch milliseconds at application boundaries",
        "encoding": "schema/proto/vitals.proto VitalSign",
        "machine": machine_context(),
        "results": results,
    }


def write_outputs(result: dict, csv_path: Path, json_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "count", "p50_ms", "p99_ms", "method", "status", "notes"])
        writer.writeheader()
        for row in result["results"]:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})
    with json_path.open("w") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--skip-storage", action="store_true")
    parser.add_argument("--csv-out", type=Path, default=Path("evidence/live_latency.csv"))
    parser.add_argument("--json-out", type=Path, default=Path("evidence/live_latency.json"))
    args = parser.parse_args()
    result = asyncio.run(measure(args.count, args.skip_storage, args.timeout))
    write_outputs(result, args.csv_out, args.json_out)
    print(f"Wrote aggregate live-latency evidence for {args.count} messages")


if __name__ == "__main__":
    main()
