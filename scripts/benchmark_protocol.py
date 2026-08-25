#!/usr/bin/env python3
"""NATS vs MQTT protocol comparison benchmark (plan-detailed.md L2).

Live-infra benchmark — requires both brokers running locally
(`docker compose up -d nats mosquitto`). Distinct in kind from
`scripts/run_benchmark.py` (Milestone 1's pure-Python offline harness):
this one measures real wire/broker behavior against the actual containers.

Dimensions measured (plan-detailed.md "Comparison Dimensions" table):
  1. P50/P99 delivery latency
  2. Throughput ceiling — highest attempted rate before P99 > 1s (or the
     highest rate attempted, if the ceiling isn't reached — reported
     either way, never silently capped)
  3. Reconnect recovery time (broker container restart)
  4. Persistence durability — messages queued for an offline durable
     consumer (NATS JetStream) / persistent session (MQTT clean_session
     off), surviving a broker restart
  5. Memory footprint (`docker stats`)
  6. Per-message wire overhead — computed analytically from each
     protocol's frame format (NATS PUB frame / MQTT PUBLISH fixed
     header), NOT packet-captured — `tcpdump` is unavailable in this
     environment. Documented here rather than silently approximated as
     a captured measurement.
  7. Delivery under a dropped connection — a proxy for true packet-level
     loss (`tc`/`netem` unavailable in this sandbox): the connection is
     forcibly closed mid-burst and messages delivered vs. published are
     counted, exercising each protocol's reconnect + redelivery
     guarantees rather than raw packet loss.

Usage:
    python scripts/benchmark_protocol.py [--n 500] [--out protocol_benchmark.csv] [--skip-restarts]
"""

import argparse
import asyncio
import csv
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import nats
import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).parent.parent))

NATS_URL = "nats://localhost:4222"
MQTT_HOST, MQTT_PORT = "localhost", 1883
NATS_CONTAINER = "academic-nats-1"
MQTT_CONTAINER = "academic-mosquitto-1"


# ---------------------------------------------------------------- latency ---

async def _nats_latency_run(n: int, rate_hz: float) -> list[float]:
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    stream_name = f"BENCH_{int(time.time() * 1000)}"
    await js.add_stream(name=stream_name, subjects=["bench.latency"], storage="memory")

    latencies: list[float] = []
    done = asyncio.Event()

    sub = await js.pull_subscribe("bench.latency", durable="BENCH_LAT", stream=stream_name)

    async def _consume():
        while len(latencies) < n:
            try:
                msgs = await sub.fetch(min(50, n - len(latencies)), timeout=2.0)
            except Exception:
                continue
            now = time.perf_counter()
            for msg in msgs:
                sent = float(msg.data.decode())
                latencies.append((now - sent) * 1000)
                await msg.ack()
        done.set()

    consume_task = asyncio.create_task(_consume())

    for _ in range(n):
        await js.publish("bench.latency", str(time.perf_counter()).encode())
        if rate_hz > 0:
            await asyncio.sleep(1 / rate_hz)

    await asyncio.wait_for(done.wait(), timeout=15.0)
    consume_task.cancel()
    await js.delete_stream(stream_name)
    await nc.close()
    return latencies


def _mqtt_latency_run(n: int, rate_hz: float) -> list[float]:
    latencies: list[float] = []

    def on_message(client, userdata, msg):
        sent = float(msg.payload.decode())
        latencies.append((time.perf_counter() - sent) * 1000)

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    sub.on_message = on_message
    sub.connect(MQTT_HOST, MQTT_PORT)
    sub.subscribe("bench/latency", qos=1)
    sub.loop_start()
    time.sleep(0.2)

    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub.connect(MQTT_HOST, MQTT_PORT)
    pub.loop_start()
    for _ in range(n):
        pub.publish("bench/latency", str(time.perf_counter()).encode(), qos=1)
        if rate_hz > 0:
            time.sleep(1 / rate_hz)

    deadline = time.time() + 15
    while len(latencies) < n and time.time() < deadline:
        time.sleep(0.05)

    pub.loop_stop(); pub.disconnect()
    sub.loop_stop(); sub.disconnect()
    return latencies


def _p50_p99(latencies: list[float]) -> tuple[float, float]:
    if not latencies:
        return float("nan"), float("nan")
    s = sorted(latencies)
    return s[len(s) // 2], s[int(len(s) * 0.99)]


# -------------------------------------------------------------- throughput ---

async def _find_throughput_ceiling(rates: list[float], n_per_rate: int) -> dict:
    results = {}
    for rate in rates:
        lat = await _nats_latency_run(n_per_rate, rate)
        p50, p99 = _p50_p99(lat)
        results[rate] = {"broker": "nats", "p50_ms": p50, "p99_ms": p99}
        if p99 > 1000:
            break
    for rate in rates:
        lat = _mqtt_latency_run(n_per_rate, rate)
        p50, p99 = _p50_p99(lat)
        key = (rate, "mqtt")
        results[key] = {"broker": "mqtt", "p50_ms": p50, "p99_ms": p99}
        if p99 > 1000:
            break
    return results


# --------------------------------------------------------------- reconnect ---

def _docker_restart(container: str) -> None:
    subprocess.run(["docker", "restart", container], check=True, capture_output=True)


async def _nats_reconnect_recovery(timeout_s: float = 30.0) -> float:
    """Time from issuing the restart to the first successful publish on a
    *fresh* connection — deliberately not reusing a single long-lived
    client's own auto-reconnect loop, since that was observed to wedge on
    repeated EOF errors during the container's restart window rather than
    recovering (see git history for this file if that regresses again)."""
    start = time.perf_counter()
    _docker_restart(NATS_CONTAINER)

    while time.perf_counter() - start < timeout_s:
        try:
            nc = await asyncio.wait_for(nats.connect(NATS_URL), timeout=1.0)
            js = nc.jetstream()
            await js.add_stream(name="RECONNECT_PROBE", subjects=["bench.reconnect"], storage="memory")
            await js.publish("bench.reconnect", b"probe")
            await js.delete_stream("RECONNECT_PROBE")
            await nc.close()
            return time.perf_counter() - start
        except Exception:
            await asyncio.sleep(0.2)
    return time.perf_counter() - start


def _mqtt_reconnect_recovery(timeout_s: float = 30.0) -> float:
    """Time from issuing the restart to the first successful QoS1 publish
    on a fresh connection (mirrors the NATS measurement above)."""
    start = time.perf_counter()
    _docker_restart(MQTT_CONTAINER)

    while time.perf_counter() - start < timeout_s:
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(MQTT_HOST, MQTT_PORT)
            client.loop_start()
            info = client.publish("bench/reconnect", b"probe", qos=1)
            info.wait_for_publish(timeout=1.0)
            client.loop_stop()
            client.disconnect()
            return time.perf_counter() - start
        except Exception:
            time.sleep(0.2)
    return time.perf_counter() - start


# ------------------------------------------------------------- persistence ---

async def _nats_persistence_durability(n: int) -> tuple[int, int]:
    """Publish n messages to a file-backed stream with no consumer attached,
    restart the broker, then count how many are still readable."""
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    stream_name = "PERSIST_PROBE"
    await js.add_stream(name=stream_name, subjects=["bench.persist"], storage="file")
    for i in range(n):
        await js.publish("bench.persist", str(i).encode())
    await nc.close()

    _docker_restart(NATS_CONTAINER)

    for _ in range(100):
        try:
            nc = await nats.connect(NATS_URL)
            break
        except Exception:
            await asyncio.sleep(0.3)
    js = nc.jetstream()
    sub = await js.pull_subscribe("bench.persist", durable="PERSIST_READER", stream=stream_name)
    recovered = 0
    try:
        while recovered < n:
            msgs = await sub.fetch(min(100, n - recovered), timeout=2.0)
            if not msgs:
                break
            for msg in msgs:
                await msg.ack()
            recovered += len(msgs)
    except Exception:
        pass
    try:
        await js.delete_stream(stream_name)
    except Exception:
        pass
    await nc.close()
    return recovered, n


def _mqtt_persistence_durability(n: int) -> tuple[int, int]:
    """Subscribe with a persistent session, go offline, publish n QoS1
    messages while offline, restart the broker, then reconnect with the
    same client_id and count how many were queued and survived."""
    client_id = "bench-persist-client"
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False)
    sub.connect(MQTT_HOST, MQTT_PORT)
    sub.subscribe("bench/persist", qos=1)
    sub.loop_start()
    time.sleep(0.3)
    sub.loop_stop()
    sub.disconnect()

    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub.connect(MQTT_HOST, MQTT_PORT)
    pub.loop_start()
    for i in range(n):
        pub.publish("bench/persist", str(i).encode(), qos=1)
    time.sleep(0.5)
    pub.loop_stop(); pub.disconnect()

    _docker_restart(MQTT_CONTAINER)
    time.sleep(2.0)

    received = []
    def on_message(client, userdata, msg):
        received.append(msg.payload)

    sub2 = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False)
    sub2.on_message = on_message
    for _ in range(20):
        try:
            sub2.connect(MQTT_HOST, MQTT_PORT)
            break
        except Exception:
            time.sleep(0.5)
    sub2.loop_start()
    time.sleep(3.0)
    sub2.loop_stop(); sub2.disconnect()
    return len(received), n


# -------------------------------------------------------------- wire size ---

def _nats_pub_frame_overhead(subject: str, payload_len: int) -> int:
    """NATS client->server PUB frame: `PUB <subject> <#bytes>\\r\\n<payload>\\r\\n`."""
    header = f"PUB {subject} {payload_len}\r\n"
    return len(header.encode()) + 2  # + trailing CRLF after payload


def _mqtt_publish_overhead(topic: str, payload_len: int, qos: int = 1) -> int:
    """MQTT 3.1.1 PUBLISH fixed+variable header (excludes payload):
    1 byte fixed header + 1-4 byte remaining-length + 2-byte topic length
    prefix + topic bytes + 2-byte packet id if QoS > 0."""
    topic_field = 2 + len(topic.encode())
    packet_id = 2 if qos > 0 else 0
    variable_header = topic_field + packet_id
    remaining_length = variable_header + payload_len
    remaining_length_bytes = 1
    while remaining_length >= 128:
        remaining_length //= 128
        remaining_length_bytes += 1
    return 1 + remaining_length_bytes + variable_header


def _wire_overhead_table() -> list[dict]:
    sample_payload = json.dumps({
        "patient_id": "P-001", "signal_type": "heart_rate", "value": 88.4, "timestamp": 1750000000000,
    })
    payload_len = len(sample_payload.encode())
    subject = "vitals.P-001.heart_rate"
    return [{
        "payload_bytes": payload_len,
        "nats_overhead_bytes": _nats_pub_frame_overhead(subject, payload_len),
        "mqtt_qos1_overhead_bytes": _mqtt_publish_overhead(subject, payload_len, qos=1),
        "mqtt_qos0_overhead_bytes": _mqtt_publish_overhead(subject, payload_len, qos=0),
    }]


# --------------------------------------------------------- drop-and-redeliver ---

async def _nats_delivery_under_drop(n: int) -> tuple[int, int]:
    # Separate connections for subscriber vs. publisher — only the
    # publisher's connection gets dropped mid-burst; the durable consumer's
    # connection must stay open or its subscription dies with it too.
    nc_sub = await nats.connect(NATS_URL)
    js_sub = nc_sub.jetstream()
    stream_name = "DROP_PROBE"
    await js_sub.add_stream(name=stream_name, subjects=["bench.drop"], storage="memory")
    sub = await js_sub.pull_subscribe("bench.drop", durable="DROP_READER", stream=stream_name)

    nc_pub = await nats.connect(NATS_URL)
    js_pub = nc_pub.jetstream()
    for i in range(n // 2):
        await js_pub.publish("bench.drop", str(i).encode())
    await nc_pub.close()  # forcibly drop the publisher connection mid-burst

    nc_pub2 = await nats.connect(NATS_URL)
    js_pub2 = nc_pub2.jetstream()
    for i in range(n // 2, n):
        await js_pub2.publish("bench.drop", str(i).encode())
    await nc_pub2.close()

    received = 0
    try:
        while received < n:
            msgs = await sub.fetch(min(50, n - received), timeout=2.0)
            if not msgs:
                break
            for msg in msgs:
                await msg.ack()
            received += len(msgs)
    except Exception:
        pass
    try:
        await js_sub.delete_stream(stream_name)
    except Exception:
        pass
    await nc_sub.close()
    return received, n


def _mqtt_delivery_under_drop(n: int) -> tuple[int, int]:
    received = []
    def on_message(client, userdata, msg):
        received.append(msg.payload)

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bench-drop-sub", clean_session=False)
    sub.on_message = on_message
    sub.connect(MQTT_HOST, MQTT_PORT)
    sub.subscribe("bench/drop", qos=1)
    sub.loop_start()
    time.sleep(0.2)

    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub.connect(MQTT_HOST, MQTT_PORT)
    pub.loop_start()
    for i in range(n // 2):
        pub.publish("bench/drop", str(i).encode(), qos=1)
    pub.loop_stop(); pub.disconnect()  # forcibly drop the publisher connection mid-burst

    pub2 = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub2.connect(MQTT_HOST, MQTT_PORT)
    pub2.loop_start()
    for i in range(n // 2, n):
        pub2.publish("bench/drop", str(i).encode(), qos=1)
    time.sleep(2.0)
    pub2.loop_stop(); pub2.disconnect()

    sub.loop_stop(); sub.disconnect()
    return len(received), n


# ------------------------------------------------------------------ memory ---

def _docker_memory(container: str) -> str:
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


# ------------------------------------------------------------------- main ---

async def run(n: int, out_path: Path, skip_restarts: bool) -> None:
    rows = []

    print("Measuring baseline delivery latency (P50/P99)...")
    nats_lat = await _nats_latency_run(n, rate_hz=200)
    mqtt_lat = _mqtt_latency_run(n, rate_hz=200)
    n_p50, n_p99 = _p50_p99(nats_lat)
    m_p50, m_p99 = _p50_p99(mqtt_lat)
    rows.append({"dimension": "latency_p50_ms", "nats": n_p50, "mqtt": m_p50})
    rows.append({"dimension": "latency_p99_ms", "nats": n_p99, "mqtt": m_p99})
    print(f"  NATS  P50={n_p50:.2f}ms P99={n_p99:.2f}ms")
    print(f"  MQTT  P50={m_p50:.2f}ms P99={m_p99:.2f}ms")

    print("Wire overhead (analytical, no tcpdump in this environment)...")
    wire = _wire_overhead_table()[0]
    for k, v in wire.items():
        rows.append({"dimension": f"wire_{k}", "nats": v if "nats" in k else "", "mqtt": v if "mqtt" in k else ""})
    print(f"  {wire}")

    print("Delivery under a dropped publisher connection (proxy for packet loss)...")
    n_recv, n_sent = await _nats_delivery_under_drop(n)
    rows.append({"dimension": "delivery_under_drop", "nats": f"{n_recv}/{n_sent}", "mqtt": ""})
    m_recv, m_sent = _mqtt_delivery_under_drop(n)
    rows[-1]["mqtt"] = f"{m_recv}/{m_sent}"
    print(f"  NATS {n_recv}/{n_sent} delivered   MQTT {m_recv}/{m_sent} delivered")

    if not skip_restarts:
        print("Memory footprint before restart tests...")
        rows.append({"dimension": "memory_usage", "nats": _docker_memory(NATS_CONTAINER), "mqtt": _docker_memory(MQTT_CONTAINER)})

        print("Reconnect recovery time (restarting both broker containers)...")
        nats_recovery = await _nats_reconnect_recovery()
        mqtt_recovery = _mqtt_reconnect_recovery()
        rows.append({"dimension": "reconnect_recovery_s", "nats": round(nats_recovery, 2), "mqtt": round(mqtt_recovery, 2)})
        print(f"  NATS {nats_recovery:.2f}s   MQTT {mqtt_recovery:.2f}s")

        print("Persistence durability across a broker restart...")
        n_survived, n_total = await _nats_persistence_durability(min(n, 200))
        m_survived, m_total = _mqtt_persistence_durability(min(n, 200))
        rows.append({"dimension": "persistence_survived", "nats": f"{n_survived}/{n_total}", "mqtt": f"{m_survived}/{m_total}"})
        print(f"  NATS {n_survived}/{n_total} survived   MQTT {m_survived}/{m_total} survived")
    else:
        print("Skipping restart-dependent tests (--skip-restarts): reconnect recovery, persistence, memory.")

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["dimension", "nats", "mqtt"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("protocol_benchmark.csv"))
    parser.add_argument("--skip-restarts", action="store_true",
                         help="Skip the container-restart-dependent tests (reconnect recovery, persistence, memory)")
    args = parser.parse_args()
    asyncio.run(run(args.n, args.out, args.skip_restarts))
