# Patient Monitoring Streaming Pipeline — Architecture Plan

## Context

Building a real-time patient vitals monitoring system in two scopes:
- **MVP (6 patients)**: Lean distributed pipeline — NATS JetStream edge buffer + async Python processing + InfluxDB Cloud + Grafana Cloud
- **Research comparison**: Isolated validation-only Kafka + Schema Registry path using the same Protobuf contract
- **Research scope (500 patients)**: Full hospital-scale deployment with Kafka, Spark, and compression — future work, not implemented

---

## MVP Architecture (6 Patients) — Ultra-Lean

```
Python generators (6 patients, scalar vitals)
        ↓ nats.py async publish
        subjects: vitals.{patient_id}.{signal_type}
NATS JetStream (Docker on Hetzner CX21)   ← edge buffer, survives WAN drop
        ↓ async subscribe (nats.py)
Python "Brain" service (async)
  - threshold evaluation → alarm_level (ok / warning / critical)
  - batched writes
        ↓ HTTPS batched writes
InfluxDB Cloud Serverless (free tier)
        ↓
Grafana Cloud (free tier)
  - real-time dashboards
  - webhook / email alerts on alarm_level = critical
```

### What's in scope
- Python synthetic data generation (scalar vitals: heart_rate, SpO2, blood_pressure, respiratory_rate, temperature)
- NATS JetStream as durable edge buffer
- Async Python consumer ("Brain") for threshold evaluation and InfluxDB writes
- InfluxDB Cloud + Grafana Cloud (both free tier)

### What's explicitly out of scope (deferred to research document)
- Production or hosted Kafka (AWS MSK / Confluent Cloud); the local comparison profile is not a production design
- PySpark / stream processing frameworks
- ZSTD batch compression
- Raw ECG waveform at 250Hz (too many writes for free tier; use heart_rate scalar instead)
- Mobile application

---

## Why this is still "distributed"

NATS JetStream is a proper distributed messaging system. Producer and consumer are fully decoupled — the generator scripts have no knowledge of the Brain service. Storage is remote (InfluxDB Cloud). This is a legitimate distributed pipeline. The isolated local Kafka/Schema Registry path exists only for research comparison; hosted Kafka and Spark remain deferred because their operational complexity is not justified for the six-patient MVP.

---

## Project Structure

```
tcc/
├── docker-compose.yml          # NATS plus opt-in secure and Kafka profiles
├── requirements.txt
├── README.md
│
├── config/
│   ├── settings.py             # NATS URL, InfluxDB URL/token/org/bucket
│   └── thresholds.py           # Per-signal alarm thresholds (warning / critical)
│
├── data/
│   ├── generators/
│   │   ├── base_generator.py   # Abstract base: generate(profile, timestamp) → float
│   │   ├── heart_rate.py       # Gaussian random walk
│   │   ├── spo2.py             # Beta-distributed, realistic desats
│   │   ├── blood_pressure.py   # Correlated systolic/diastolic pair
│   │   ├── respiratory_rate.py # Poisson-like integer variation
│   │   └── temperature.py      # Slow walk with circadian variation
│   └── profiles/
│       ├── P-001.json          # Baselines + clinical condition per patient
│       └── ... (P-002 to P-006)
│
├── producer/
│   ├── main.py                 # Spawns one async task per patient
│   └── patient_producer.py     # Async NATS publisher for one patient
│
├── brain/
│   ├── main.py                 # Entry point: subscribes to NATS, runs eval loop
│   ├── evaluator.py            # Threshold logic → alarm_level string
│   └── influx_writer.py        # Batched async writes to InfluxDB Cloud
├── kafka_path/                 # Isolated Protobuf Kafka producer/consumer/provisioning
│
├── grafana/
│   └── provisioning/
│       ├── datasources/influxdb.yml
│       └── dashboards/
│           ├── dashboard.yml
│           └── vitals.json     # State timeline + per-signal panels
│
└── scripts/
    ├── create_streams.sh       # NATS JetStream stream/consumer init
    └── create_kafka_topics.sh  # Idempotent research-topic provisioning
```

---

## Data Architecture

### Signal generation — parametric synthetic (not random uniform)

| Signal           | Method                                       | Publish rate |
| ---------------- | -------------------------------------------- | ------------ |
| Heart Rate       | Gaussian random walk around patient baseline | 1/2s         |
| SpO2             | Beta-distributed, rare desaturations         | 1/2s         |
| Blood Pressure   | Correlated systolic/diastolic pair           | 1/5s         |
| Respiratory Rate | Poisson-like integer                         | 1/4s         |
| Temperature      | Slow walk, circadian variation               | 1/10s        |

### Patient profiles (`data/profiles/P-00X.json`)

6 patients, distinct clinical conditions: `post_surgery`, `hypertensive`, `healthy_adult`, `pediatric`, `elderly`, `critical_icu`. Different baselines per patient makes alarms fire at different rates — important for demo credibility.

```json
{
  "patient_id": "P-001",
  "condition": "post_surgery",
  "baselines": {
    "heart_rate": { "mean": 88, "std": 10 },
    "spo2": { "mean": 96, "std": 1.5 },
    "systolic_bp": { "mean": 130, "std": 12 },
    "diastolic_bp": { "mean": 82, "std": 8 },
    "respiratory_rate": { "mean": 18, "std": 2 },
    "temperature": { "mean": 37.2, "std": 0.3 }
  }
}
```

### NATS subject hierarchy

```
vitals.{patient_id}.heart_rate
vitals.{patient_id}.spo2
vitals.{patient_id}.blood_pressure   → {systolic, diastolic} in payload
vitals.{patient_id}.respiratory_rate
vitals.{patient_id}.temperature
dlq.vitals.nats                       → rejected Protobuf envelopes (separate stream)
alarms.{patient_id}.medium|high        → local NEWS2 alarm events
```

### Message validation and local alarm path

All active producer and consumer paths use the canonical Protobuf contract in
`schema/proto/vitals.proto`. The brain validates each decoded message before
it can update an EWS window. Malformed or structurally invalid messages are
published as `DeadLetterEnvelope` records to `dlq.vitals.nats` in the separate
`VITALS_DLQ` stream, so rejection traffic cannot be consumed as vital input.

The optional MQTT mirror uses `vitals/{patient_id}/{signal_type}` and a bounded
`vitals/#` subscription. It maps that topic to the same dotted identity check.
Invalid MQTT input is published to `dlq/vitals/mqtt` with QoS 1 and receives a
PUBACK before the source message is acknowledged. PUBACK establishes broker
receipt only; no durable MQTT DLQ archive is claimed. NATS and MQTT publication
are independent rather than an atomic dual-write.

Run the local NEWS2 alarm path separately with:

```bash
python -m brain.local_scorer
```

It publishes NEWS2 scores 5–6, or a single parameter scoring 3, to
`alarms.{patient_id}.medium`; scores ≥7 go to `alarms.{patient_id}.high`.
Composite scores require all five scoped inputs to be fresh. SpO2 Scale 1 is
the default, and Scale 2 is selected only through an explicit
`news2_spo2_scale` profile field representing a documented prescription—not
from `copd_flag`. Generate a development TLS certificate before
a secured deployment with `bash scripts/generate_dev_tls.sh`; certificates and
credentials are intentionally not tracked.

`alarms.>` is retained in the file-backed `ALARMS` stream for seven days, and
its JetStream publish acknowledgement precedes source acknowledgement. The
scorer window is memory-only and there is no notification consumer, so this is
not a restart-continuity or external-delivery claim.

For the secure NATS profile, create a local `.env` containing unique `NATS_USER`,
`NATS_PASSWORD`, `NATS_TLS=true`, `NATS_CA_FILE=./nats/certs/nats-cert.pem`,
and `NATS_URL=nats://localhost:4222`; then run
`docker compose --profile secure up -d nats-secure`.

Set `REQUIRE_NATS_INTEGRATION=true` when running the NATS integration tests in
CI or an explicit live verification. Without that flag, an unavailable broker
is reported as a bounded skip; with it, connection, authentication, and trust
failures fail the test run.

For synthetic-distribution validation, supply approved reference and synthetic
CSVs with the five documented signal columns:

```bash
python scripts/validate_distributions.py --reference reference.csv \
  --synthetic synthetic.csv --source-id APPROVED_SOURCE_ID \
  --transformation-method VERSIONED_METHOD_ID \
  --out-dir distribution_validation
```

### Isolated Kafka/Schema Registry validation comparison

Kafka is an opt-in research transport and does not replace the NATS MVP entry
points. It uses Schema Registry-framed Protobuf on `vitals.protobuf.v1` and
`vitals.dlq.protobuf.v1`, with `BACKWARD_TRANSITIVE` compatibility, patient ID
keys, idempotent production, and explicit consumer commits. Runtime schema
auto-registration is disabled; provisioning owns registration and compatibility
checks.

The shipped consumer validates and prints records. It does not invoke Brain
scoring, the SQLite outbox, InfluxDB, or alarm emission. The parity command
compares valid/invalid transport acceptance and local latency only—not runtime,
storage, alarm, or clinical outcome parity. `--count 20` publishes 20 valid
records plus one intentional poison record per transport.

The fixed loopback ports `19092` (Kafka) and `18081` (Schema Registry) are
reserved to the Academic workspace in the root port registry.

```bash
docker compose --profile kafka up -d --wait kafka schema-registry
bash scripts/create_kafka_topics.sh
python -m kafka_path.provision
REQUIRE_KAFKA_INTEGRATION=true python -m pytest brain/tests/test_integration_kafka.py -q
python -m kafka_path.parity --live --count 20 --timeout 20 --format json
docker compose --profile kafka stop schema-registry kafka
```

For a manual smoke test, run `python -m kafka_path.consumer --max-messages 1`
and then `python -m kafka_path.producer` in another terminal.

### InfluxDB schema

```
measurement: patient_vitals
  tags:
    patient_id   → "P-001" .. "P-006"
    signal_type  → "heart_rate" | "spo2" | "systolic_bp" | ...
    condition    → "post_surgery" | "hypertensive" | ...
    alarm_level  → "ok" | "warning" | "critical"
  fields:
    value        → float
  timestamp: from generator (not ingest time)
```

---

## Alarm Architecture

### Thresholds (`config/thresholds.py`)

```python
SIGNAL_THRESHOLDS = {
    "heart_rate":       {"warning_high": 100, "critical_high": 120, "warning_low": 50,  "critical_low": 40},
    "spo2":             {"warning_low": 94,   "critical_low": 90},
    "systolic_bp":      {"warning_high": 140, "critical_high": 180, "warning_low": 90},
    "respiratory_rate": {"warning_high": 20,  "critical_high": 30,  "warning_low": 10},
    "temperature":      {"warning_high": 37.5,"critical_high": 38.5,"warning_low": 36.0},
}
```

### Brain service flow (`brain/`)

1. Async NATS subscriber receives message
2. `evaluator.py` compares value against thresholds → returns `alarm_level` string
3. All derived records are atomically committed to the local SQLite WAL outbox
4. The broker message is acknowledged after that durable local commit
5. Retryable batches are delivered to InfluxDB Cloud asynchronously; failures
   remain in the outbox across restart

### Grafana alerting

- **State timeline panel**: one per patient, shows `alarm_level` tag over time — visually compelling for demo
- **Threshold lines**: drawn on each signal panel as static visual reference
- **Alert rules**: Flux query counts `alarm_level = "critical"` in last 30s → fires webhook or email

---

## Infrastructure

| Component | Hosting | Cost |
|---|---|---|
| NATS JetStream + all Python services | Hetzner CX21 (2 vCPU, 4GB RAM) | €4.50/month |
| Local Kafka + Schema Registry | Docker Compose `kafka` profile (research only) | Local development only |
| Cloud Kafka | — (out of scope) | — |
| InfluxDB | InfluxDB Cloud free tier | $0 |
| Grafana | Grafana Cloud free tier | $0 |
| **Total** | | **€4.50/month** |

---

## Research Document Scope (500 Patients — not implemented)

| Layer | Technology | Notes |
|---|---|---|
| Edge | Hetzner 3-node NATS JetStream cluster | HA, 250k msg/s, leaf nodes per ward |
| ECG | Raw 250Hz + ZSTD batch compressor | Reduces 250 msg/s → 1 msg/s per patient |
| Cloud broker | AWS MSK Express or Confluent Cloud | Schema Registry mandatory |
| Stream processing | PySpark on EMR Serverless | Separate streaming (alarms) from batch (ML training) |
| Storage | InfluxDB Cloud paid or self-hosted HA | Separate buckets + retention per signal type |
| Mobile | FastAPI + WebSocket + FCM/APNS | Redis for WebSocket session state at scale |

---

## Implementation Phases

| Phase | Goal | Deliverable |
|---|---|---|
| 1 | Restructure | Clean directories, config extracted, same behavior as current MVP |
| 2 | Signal generators | 5 signals × parametric generators, 6 patient profiles |
| 3 | Async NATS producer | One async task per patient, publishes to NATS JetStream |
| 4 | Brain service | Async NATS consumer + threshold evaluator + batched InfluxDB writer |
| 5 | Grafana Cloud | Provisioned datasource + dashboard, state timeline, alert rules |

---

## Critical Files

- [docker-compose.yml](docker-compose.yml) — NATS/Mosquitto plus opt-in secure-NATS and local Kafka comparison profiles
- `producer/` and `brain/` — active NATS MVP producer, validation, scoring, and storage path
- `kafka_path/` and `schema/` — isolated Protobuf/Schema Registry research comparison
- `scripts/` and `evidence/` — non-interactive experiment tooling and privacy-safe derived evidence
- `config/`, `data/`, and `grafana/provisioning/` — configuration, synthetic inputs, and dashboards

## Verification

1. Run the fresh-environment and port preflight in the operator guide.
2. Run the complete offline test gate.
3. Run required live NATS tests against an explicitly started local broker.
4. Run storage, scale, protocol, Kafka, or Grafana gates only when their
   documented infrastructure and governance prerequisites are satisfied.
5. Generate release evidence only from a clean, frozen commit; never force an
   outcome by editing a tracked patient profile during a final run.

## Operator documentation

Use [OPERATIONS_AND_REPRODUCIBILITY.md](OPERATIONS_AND_REPRODUCIBILITY.md) as
the canonical guide for environment setup, feature behavior, ports,
acknowledgement semantics, infrastructure profiles, evidence reproduction, and
maintenance. Governance and remaining acceptance work are defined in
[IMPLEMENTATION_BLUEPRINT.md](IMPLEMENTATION_BLUEPRINT.md).

The complete implementation summary, historical verification context,
outstanding decisions, and unfinished work are consolidated in
[IMPLEMENTED.md](IMPLEMENTED.md). Accepted standards are recorded in
[DECISIONS.md](DECISIONS.md), and runtime telemetry/privacy requirements remain
in [TELEMETRY_CONTRACT.md](TELEMETRY_CONTRACT.md). Milestone and worker reports
are intentionally not retained after their unique findings have been folded
into these authorities.
