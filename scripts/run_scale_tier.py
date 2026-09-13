#!/usr/bin/env python3
"""Scale-tier throughput/bottleneck study (plan-detailed.md L2, T1->T4).

Generates N synthetic patients on the fly and drives every signal at a
uniform target frequency (overriding the clinically-staggered per-signal
intervals used elsewhere — a scale test cares about raw throughput, not
clinical realism), publishing through the real NATS producer/generator
code. A lightweight consumer (no scoring, no InfluxDB — this measures
transport, not the brain service) fetches for a fixed window and reports
achieved msg/s, P50/P99 publish->fetch latency, and JetStream consumer
backlog (a growing `num_pending` is the clearest signal that the pipeline
is falling behind the target rate).

Tiers (plan-detailed.md "Scale Expansion" table):
  T1:   6 patients @   1Hz  ~=     30 msg/s
  T2:  24 patients @ 100Hz  ~= 12,000 msg/s
  T3:  50 patients @ 250Hz  ~= 62,500 msg/s
  T4: 100 patients @ 250Hz  ~=125,000 msg/s

Usage:
    python scripts/run_scale_tier.py --tier T2 [--duration 20]
    python scripts/run_scale_tier.py --patients 40 --hz 50 --duration 15
"""

import argparse
import asyncio
import csv
import json
import math
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent.parent))

from producer.patient_producer import PatientProducer
from config.settings import PIPELINE_VERSION, SCHEMA_VERSION, nats_connection_options
from schema import vitals_pb2

TIERS = {
    "T1": (6, 1.0),
    "T2": (24, 100.0),
    "T3": (50, 250.0),
    "T4": (100, 250.0),
}

_BASELINES = {
    "heart_rate":       {"mean": 75,  "std": 8},
    "spo2":             {"mean": 97,  "std": 1.0},
    "systolic_bp":      {"mean": 120, "std": 10},
    "diastolic_bp":     {"mean": 78,  "std": 8},
    "respiratory_rate": {"mean": 16,  "std": 2},
    "temperature":      {"mean": 36.8, "std": 0.2},
}


def _make_profiles(n: int) -> list[dict]:
    return [
        {"patient_id": f"P-SCALE-{i:04d}", "condition": "scale_test", "copd_flag": False, "baselines": _BASELINES}
        for i in range(n)
    ]


def machine_context() -> dict:
    """Return useful, non-identifying execution context (never a hostname)."""
    memory_bytes = None
    try:
        memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "memory_bytes": memory_bytes,
        "python_version": platform.python_version(),
    }


async def run(
    n_patients: int,
    hz: float,
    duration_s: float,
    pull_timeout: float = 0.1,
    tier: str = "custom",
    connection_options: dict | None = None,
) -> dict:
    target_msg_s = n_patients * hz * 5  # 5 signals per patient
    print(f"Tier: {n_patients} patients @ {hz}Hz -> target ~{target_msg_s:.0f} msg/s, "
          f"window {duration_s}s, pull_timeout={pull_timeout}s")
    print("Note: pull_timeout is the dominant latency source at low message rates — "
          "fetch() waits up to this long trying to fill the requested batch before "
          "returning whatever partial batch arrived (plan-detailed.md's own flagged "
          "v1 concern: 'large batch = latency spike; small batch = CPU spin'). Tune it "
          "down for low tiers, up for high tiers where CPU-spin from constant polling "
          "would otherwise dominate instead.")

    options = dict(connection_options or nats_connection_options())
    options.setdefault("allow_reconnect", False)
    options.setdefault("connect_timeout", 2)
    nc_pub = await nats.connect(**options)
    js_pub = nc_pub.jetstream()

    stream_name = f"SCALE_{int(time.time())}"
    await js_pub.add_stream(name=stream_name, subjects=["scale.>"], storage="memory", max_msgs=2_000_000)

    profiles = _make_profiles(n_patients)
    interval = 1.0 / hz

    producers = [PatientProducer(profile, js_pub) for profile in profiles]

    producer_tasks = [
        asyncio.create_task(_run_all_signals(p, interval, stream_name), name=p.patient_id)
        for p in producers
    ]

    nc_sub = await nats.connect(**options)
    js_sub = nc_sub.jetstream()
    sub = await js_sub.pull_subscribe("scale.>", durable="SCALE_READER", stream=stream_name)

    latencies = []
    received = 0
    start = time.perf_counter()

    while time.perf_counter() - start < duration_s:
        try:
            msgs = await sub.fetch(500, timeout=pull_timeout)
        except Exception:
            continue
        now = time.time()
        for msg in msgs:
            try:
                data = vitals_pb2.VitalSign.FromString(msg.data)
                latencies.append((now - data.timestamp_ms / 1000) * 1000)
            except Exception:
                pass
            await msg.ack()
        received += len(msgs)

    elapsed = time.perf_counter() - start
    for t in producer_tasks:
        t.cancel()
    await asyncio.gather(*producer_tasks, return_exceptions=True)

    try:
        info = await js_sub.consumer_info(stream_name, "SCALE_READER")
        backlog = info.num_pending
    except Exception:
        backlog = None

    try:
        await sub.unsubscribe()
    except Exception:
        pass
    try:
        await js_pub.delete_stream(stream_name)
    except Exception:
        pass
    await nc_pub.close()
    await nc_sub.close()

    achieved_msg_s = received / elapsed
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else float("nan")
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else float("nan")

    print(f"Achieved: {achieved_msg_s:.0f} msg/s ({received} messages in {elapsed:.1f}s)")
    print(f"Latency: P50={p50:.1f}ms  P99={p99:.1f}ms")
    print(f"Consumer backlog at end: {backlog} pending messages "
          f"({'falling behind' if backlog and backlog > 100 else 'keeping up'})")
    if p99 > 1000:
        print("BOTTLENECK: P99 latency exceeded 1s at this tier.")
    if achieved_msg_s < target_msg_s * 0.9:
        print(f"BOTTLENECK: achieved throughput ({achieved_msg_s:.0f}/s) is well below "
              f"target ({target_msg_s:.0f}/s) — producer client (this process, asyncio/GIL-bound) "
              f"is the likely first saturation point at this scale, not the NATS broker itself.")
    return {
        "tier": tier,
        "status": "executed",
        "target_rate_msg_s": target_msg_s,
        "achieved_rate_msg_s": achieved_msg_s,
        "p50_latency_ms": None if math.isnan(p50) else p50,
        "p99_latency_ms": None if math.isnan(p99) else p99,
        "backlog_messages": backlog,
        "duration_s": elapsed,
        "patients": n_patients,
        "signal_rate_hz": hz,
        "pull_timeout_s": pull_timeout,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine": machine_context(),
    }


def write_result(result: dict, csv_path: Path | None, json_path: Path | None) -> None:
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        flat = {key: value for key, value in result.items() if key != "machine"}
        flat.update({f"machine_{key}": value for key, value in result["machine"].items()})
        exists = csv_path.exists() and csv_path.stat().st_size > 0
        with csv_path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(flat))
            if not exists:
                writer.writeheader()
            writer.writerow({key: "" if value is None else value for key, value in flat.items()})


async def _run_all_signals(producer: PatientProducer, interval: float, stream_name: str) -> None:
    """Publish all 5 signals for one patient at a uniform rate onto the
    scale-test stream (`scale.>` subjects, not `vitals.>` — kept isolated
    from the real VITALS stream so this never touches production data)."""
    start_ms = int(time.time() * 1000)
    while True:
        ts = int(time.time() * 1000)
        for signal_type, gen in producer._generators.items():
            value = gen.generate(ts)
            payload = vitals_pb2.VitalSign(
                patient_id=producer.patient_id,
                signal_type=signal_type,
                timestamp_ms=ts,
                schema_version=SCHEMA_VERSION,
                pipeline_version=PIPELINE_VERSION,
            )
            if signal_type == "blood_pressure":
                payload.bp.systolic = float(value["systolic"])
                payload.bp.diastolic = float(value["diastolic"])
            else:
                payload.scalar_value = float(value)
            try:
                await producer._js.publish(
                    f"scale.{producer.patient_id}.{signal_type}", payload.SerializeToString()
                )
            except Exception:
                pass
        await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=sorted(TIERS))
    parser.add_argument("--patients", type=int)
    parser.add_argument("--hz", type=float)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--pull-timeout", type=float, default=0.1,
                         help="Pull-consumer fetch() timeout in seconds — dominates latency at low tiers")
    parser.add_argument("--csv-out", type=Path, help="Append the result as a flat CSV row")
    parser.add_argument("--json-out", type=Path, help="Write the result and machine context as JSON")
    parser.add_argument("--nats-url",
                        help="Explicit broker URL for an isolated evidence run; bypasses env TLS/auth options")
    args = parser.parse_args()

    if args.tier:
        n, hz = TIERS[args.tier]
    elif args.patients and args.hz:
        n, hz = args.patients, args.hz
    else:
        parser.error("Pass --tier or both --patients and --hz")

    connection_options = {"servers": args.nats_url} if args.nats_url else None
    result = asyncio.run(
        run(n, hz, args.duration, args.pull_timeout, args.tier or "custom", connection_options)
    )
    write_result(result, args.csv_out, args.json_out)
