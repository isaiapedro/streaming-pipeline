# Milestone 2 Report — Edge/Protocol Layer (L2)

**Date:** 2026-08-25
**Branch:** `milestone-1-scenario-suite-news2-scoring` (Milestone 1 already merged onto this branch's history)
**Plan reference:** `personal/academic_writting/plan-detailed.md` L2 checklist (updated alongside this report)

---

## 1. What Was Implemented

### 1.0 Housekeeping
- `config/settings.py` — no more hardcoded InfluxDB token; loads from `.env` via `python-dotenv` (see Milestone 1's commit for why `.env` exists — same token, now sourced from environment only).
- `brain/influx_writer.py` — `InfluxWriter.start()` now raises immediately with a clear message if any of `INFLUX_URL/INFLUX_TOKEN/INFLUX_ORG/INFLUX_BUCKET` is unset, instead of failing confusingly deep inside the InfluxDB client.
- `brain/tests/test_evaluator.py` — 46 new boundary-value tests for Approach A's per-signal thresholds (all 5 signals, blood-pressure expansion, unknown-signal fallback). Two of my own initial test expectations were wrong (SpO2 warning boundary, temperature's critical band) — caught and fixed by running them, not just written and trusted.
- `brain/tests/test_integration_nats.py` — real NATS JetStream round-trip test (publish → durable pull-consume → score), skips cleanly if no local NATS is reachable. Deliberately does **not** write to InfluxDB (avoids polluting the real cloud bucket from an automated test) — verifies transport + scoring only.
- Test suite: **105 passing** (58 NEWS2 + 46 evaluator + 1 integration).

### 1.1 NATS vs MQTT protocol comparison
- `docker-compose.yml` + `mosquitto/mosquitto.conf` — Mosquitto 2.x alongside NATS, anonymous/no-TLS (matches NATS's current local-dev posture).
- `producer/mqtt_producer.py` — `MqttPublisher`, thin async-safe wrapper over paho-mqtt.
- `producer/patient_producer.py` + `producer/main.py` — `--dual-mqtt [--mqtt-host --mqtt-port]` publishes every message to both brokers from the same producer, unchanged NATS behavior when the flag is absent.
- `brain/mqtt_consumer.py` — second consumer mode (`python -m brain.mqtt_consumer`), same Approach A/C scoring as the NATS consumer. **Design note:** the producer publishes MQTT topics using the same literal dotted string as the NATS subject (`vitals.P-001.heart_rate`) rather than translating to MQTT's `/`-hierarchy — so this consumer subscribes to `#` (everything) instead of a `vitals/+` filter. Documented in the module docstring; a real MQTT deployment would use `/`-delimited topics.
- `scripts/benchmark_protocol.py` — measures all 8 comparison dimensions from `plan-detailed.md`, live against the actual containers:

  | Dimension | NATS | MQTT | Note |
  |---|---|---|---|
  | Latency P50/P99 (n=100 @ 200Hz) | 1.3ms / 2.4ms | 1.1ms / 1.9ms | both trivial on loopback |
  | Wire overhead (95-byte JSON payload) | 34 bytes/msg | 29 bytes (QoS1) / 27 bytes (QoS0) | **analytical**, not packet-captured — `tcpdump` unavailable in this environment |
  | Delivery under a dropped connection (n=100, proxy for packet loss — no `tc`/`netem` here) | 100/100 | 100/100 | both redeliver correctly after a forced reconnect |
  | Reconnect recovery (container restart) | ~2.0s | ~1.6s | comparable; NATS's own auto-reconnect loop was found to wedge on repeated EOF errors during the restart window — worked around by polling with fresh connections instead (see code comment) |
  | Persistence across restart (n=100) | 100/100 survived (file-backed stream) | 100/100 survived (persistent session + `persistence true`) | both configured for durability in this setup |
  | Memory footprint | via `docker stats` | via `docker stats` | captured per-run, not fixed numbers worth quoting here |

  Full run: `python scripts/benchmark_protocol.py --n 500` (or `--skip-restarts` to omit the container-restart-dependent rows).

### 1.2 Bidirectional config push
- `brain/config_watcher.py` — JetStream KV bucket `CONFIG`, key `thresholds`. `watch_thresholds()` mutates `config.thresholds.SIGNAL_THRESHOLDS` **in place** (not rebound), so `brain/evaluator.py`'s already-imported reference picks up changes immediately, no restart.
- `brain/main.py` now runs `watch_thresholds()` as a background task alongside the pull-consumer loop.
- `scripts/push_threshold_update.py` — operator-side CLI (`--signal heart_rate --warning-high 110 ...`).
- **Verified live:** ran `brain.main`, pushed two separate threshold updates while it was running — hot-reload confirmed in logs, propagation latency measured at ~1-2ms both times. The very first KV entry a freshly-started watcher sees is JetStream's replay of whatever was last written (from a *previous* run) — that entry's embedded push-timestamp is stale, so it's now labeled "startup/replayed value" instead of reporting a meaningless multi-hour "propagation latency" (an early version of this did exactly that; caught and fixed before writing this report).
- Scope note: only threshold hot-reload is implemented. Per-alarm cloud *suppression* (`brain/suppress.{patient_id}`) belongs to the two-tier local/cloud brain split from `plan.md`, which doesn't exist in this single-service brain — correctly out of scope here.

### 1.3 Scale-tier runner
- `scripts/run_scale_tier.py` — generates N on-the-fly patient profiles, drives all 5 signals at a uniform target Hz (overriding the realistic staggered intervals used elsewhere — intentional, a scale test cares about raw throughput), publishes onto an isolated `scale.>` subject/stream (never touches the real `VITALS` stream), and reports achieved msg/s, P50/P99 publish→fetch latency, and consumer backlog.
- **Ran T1 and T2 in this environment** (T3/T4 not run here — script supports them, left as follow-up given this sandbox's available compute; not claiming coverage I didn't run):
  - **T1** (6 patients @ 1Hz, ~30 msg/s): achieved 30/30 msg/s exactly, consumer backlog 0. Initial run showed P50 latency of ~984ms, which looked like a real bottleneck — it wasn't. The pull-consumer's `fetch(batch, timeout)` was waiting nearly the full 1.0s timeout trying to fill a 500-message batch that, at 30 msg/s, never fills — an artifact of the polling parameters, not the pipeline. Re-run with `--pull-timeout 0.1` dropped it to P50=19ms/P99=22ms. This is a **real, citable finding**: it empirically confirms `plan-detailed.md`'s own flagged v1 concern ("large batch = latency spike; small batch = CPU spin") rather than just restating it theoretically.
  - **T2** (24 patients @ 100Hz, target ~12,000 msg/s): achieved only ~5,246 msg/s. Consumer backlog stayed low (85 pending, keeping up) — meaning the bottleneck is the **producer side**, not NATS or the consumer: a single Python process running 120 concurrent per-signal publish loops (asyncio + GIL) can't sustain the target rate. This matches `plan-detailed.md`'s own hypothesis that "asyncio event loop becomes the binding constraint before NIC" at scale — found here already at T2 in this sandbox (likely lower CPU allocation than the target Hetzner CX21; the qualitative finding — producer CPU is the first thing to saturate, not the broker — should still hold there).

---

## 2. How To Test

### 2.1 Bring up both brokers
```bash
cd workspace/academic
docker compose up -d nats mosquitto
bash scripts/create_streams.sh   # creates VITALS stream + BRAIN durable consumer, if not already present
```

### 2.2 Unit + integration tests
```bash
./tcc_env/bin/python -m pip install -r requirements.txt
./tcc_env/bin/python -m pytest brain/tests/ -q
# expect: 105 passed (skips the integration test cleanly if NATS isn't reachable)
```

### 2.3 NATS vs MQTT protocol benchmark
```bash
./tcc_env/bin/python scripts/benchmark_protocol.py --n 500 --out protocol_benchmark.csv
# add --skip-restarts to omit the container-restart-dependent rows (reconnect/persistence/memory)
```
This restarts the `nats`/`mosquitto` containers as part of the reconnect and persistence tests — expected and safe (same container, same volume), but worth knowing before running it against anything you don't want briefly interrupted.

### 2.4 Live config-push demo
```bash
./tcc_env/bin/python -m brain.main &
./tcc_env/bin/python scripts/push_threshold_update.py --signal heart_rate --warning-high 110 --critical-high 130
# watch the brain process's stdout for the "Thresholds hot-reloaded ... propagation Xms" line
```

### 2.5 Scale-tier runner
```bash
./tcc_env/bin/python scripts/run_scale_tier.py --tier T1 --duration 10 --pull-timeout 0.1
./tcc_env/bin/python scripts/run_scale_tier.py --tier T2 --duration 15 --pull-timeout 0.1
# T3/T4 not verified in this environment — run them here if you have more headroom:
./tcc_env/bin/python scripts/run_scale_tier.py --tier T3 --duration 20
./tcc_env/bin/python scripts/run_scale_tier.py --tier T4 --duration 20
```

### 2.6 MQTT dual-publish + second consumer mode
```bash
./tcc_env/bin/python -m brain.mqtt_consumer &
./tcc_env/bin/python -m producer.main --dual-mqtt
```

---

## 3. How To Visualize

- `protocol_benchmark.csv` from §2.3 is a flat `{dimension, nats, mqtt}` table — drop straight into a spreadsheet or a small pandas/matplotlib bar chart per dimension, same pattern as `benchmark_visualization.ipynb` from Milestone 1.
- Scale-tier output (§2.5) is currently console-only — worth adding rows to a CSV (`{tier, target_msg_s, achieved_msg_s, p50_ms, p99_ms, backlog}`) once T3/T4 are run somewhere with more headroom, for a tier-vs-throughput chart.
- No Grafana changes this milestone — L10 (side-by-side A/B/C dashboard) is still Milestone 3 scope; the existing dashboard is unaffected by any of this milestone's changes.

---

## 4. Progress Status — Full Project (L1–L10)

| Layer | Status | Notes |
|---|---|---|
| **L1** Data generation | 🟡 Mostly done | Unchanged this milestone. Still missing: PhysioNet distribution-validation figure. |
| **L2** Edge / Protocol | 🟢 Done for this milestone | MQTT comparison, `config_watcher.py`, scale-tier runner (T1/T2 verified, T3/T4 scripted but not run) all implemented and tested live. TLS not done (local dev only). |
| **L3** Message schema | 🔴 Not started | Still plain JSON, no protobuf, no Kafka, no Schema Registry. Milestone 3. |
| **L4** Ingestion backbone | 🟢 Done (NATS) | Unchanged. |
| **L5** Stream processing | 🟢 Done | Unchanged from Milestone 1. |
| **L6** Storage | 🟡 Partial | Unchanged from Milestone 1. |
| **L7** Security | 🟡 Improved | Hardcoded token removed from source (Milestone 1); fail-fast on missing env vars added this milestone. Token itself still needs manual rotation in the InfluxDB Cloud console — not something I can do. |
| **L8** Compliance/traceability | 🔴 Not started | Still blocked on L3 (`schema_version`/`pipeline_version` tags). |
| **L9** Observability & testing | 🟢 Much improved | `test_evaluator.py` + a real NATS integration test added; 105 tests total. Missing: automated tests for the MQTT path and config_watcher (both verified manually/live in this milestone, not under pytest). |
| **L10** Visualization | 🔴 Not started (dashboard) | Unchanged — still Milestone 3. |

---

## 5. What Can Be Written for the Paper Now

- **NATS vs MQTT comparison section** — the theoretical comparison table already in `plan-detailed.md` now has real numbers behind 6 of its 8 dimensions (wire overhead is analytical by necessity, documented as such rather than silently presented as measured).
- **Pull-consumer tuning as a concrete finding** — the T1 latency artifact (§1.3) is a good worked example: theory said "pull batch tuning matters," this milestone shows exactly how much (984ms → 19ms from one parameter), with the root cause explained rather than asserted.
- **Scale-tier bottleneck attribution** — T2's finding (producer asyncio loop saturates before the broker does) is citable evidence for `plan-detailed.md`'s own claim that a single-process Python producer, not NATS, is the first thing to break at scale — supports the future case for a multi-process or Flink-based producer at T3/T4.
- **Config-push demo** — the live-verified hot-reload with measured propagation latency (~1-2ms) is a concrete number for the "bidirectional channel" section, plus a good illustration of a real subtlety worth a sentence in the paper: a freshly-started watcher replays the last-written KV value on connect, which needs to be told apart from a genuinely new push when reporting latency.
- **Still not writeable:** protobuf/Kafka/Schema Registry (L3), the Grafana A/B/C dashboard (L10), and any TLS/production-hardening claims for L2 (deliberately still local/anonymous in this milestone).
