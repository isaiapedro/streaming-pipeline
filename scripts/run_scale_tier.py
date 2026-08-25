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
import json
import sys
import time
from pathlib import Path

import nats

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import NATS_URL
from producer.patient_producer import PatientProducer

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


async def run(n_patients: int, hz: float, duration_s: float, pull_timeout: float = 0.1) -> None:
    target_msg_s = n_patients * hz * 5  # 5 signals per patient
    print(f"Tier: {n_patients} patients @ {hz}Hz -> target ~{target_msg_s:.0f} msg/s, "
          f"window {duration_s}s, pull_timeout={pull_timeout}s")
    print("Note: pull_timeout is the dominant latency source at low message rates — "
          "fetch() waits up to this long trying to fill the requested batch before "
          "returning whatever partial batch arrived (plan-detailed.md's own flagged "
          "v1 concern: 'large batch = latency spike; small batch = CPU spin'). Tune it "
          "down for low tiers, up for high tiers where CPU-spin from constant polling "
          "would otherwise dominate instead.")

    nc_pub = await nats.connect(NATS_URL)
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

    nc_sub = await nats.connect(NATS_URL)
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
                data = json.loads(msg.data)
                latencies.append((now - data["timestamp"] / 1000) * 1000)
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


async def _run_all_signals(producer: PatientProducer, interval: float, stream_name: str) -> None:
    """Publish all 5 signals for one patient at a uniform rate onto the
    scale-test stream (`scale.>` subjects, not `vitals.>` — kept isolated
    from the real VITALS stream so this never touches production data)."""
    start_ms = int(time.time() * 1000)
    while True:
        ts = int(time.time() * 1000)
        for signal_type, gen in producer._generators.items():
            value = gen.generate(ts)
            payload = json.dumps({
                "patient_id": producer.patient_id, "signal_type": signal_type,
                "value": value, "timestamp": ts,
            }).encode()
            try:
                await producer._js.publish(f"scale.{producer.patient_id}.{signal_type}", payload)
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
    args = parser.parse_args()

    if args.tier:
        n, hz = TIERS[args.tier]
    elif args.patients and args.hz:
        n, hz = args.patients, args.hz
    else:
        parser.error("Pass --tier or both --patients and --hz")

    asyncio.run(run(n, hz, args.duration, args.pull_timeout))
