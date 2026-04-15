# Patient Monitoring Streaming Pipeline — Architecture Plan

## Context

Building a real-time patient vitals monitoring system in two scopes:
- **MVP (6 patients)**: Lean distributed pipeline — NATS JetStream edge buffer + async Python processing + InfluxDB Cloud + Grafana Cloud
- **Research scope (500 patients)**: Full hospital-scale with Kafka, Spark, compression — documented as future work only, not implemented

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
- Kafka (AWS MSK / Confluent Cloud)
- PySpark / stream processing frameworks
- ZSTD batch compression
- Raw ECG waveform at 250Hz (too many writes for free tier; use heart_rate scalar instead)
- Mobile application

---

## Why this is still "distributed"

NATS JetStream is a proper distributed messaging system. Producer and consumer are fully decoupled — the generator scripts have no knowledge of the Brain service. Storage is remote (InfluxDB Cloud). This is a legitimate distributed pipeline; Kafka/Spark are deferred because they add operational complexity that isn't justified at 6 patients.

---

## Project Structure

```
tcc/
├── docker-compose.yml          # NATS JetStream only
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
│
├── grafana/
│   └── provisioning/
│       ├── datasources/influxdb.yml
│       └── dashboards/
│           ├── dashboard.yml
│           └── vitals.json     # State timeline + per-signal panels
│
└── scripts/
    └── create_streams.sh       # NATS JetStream stream/consumer init
```

---

## Data Architecture

### Signal generation — parametric synthetic (not random uniform)

| Signal | Method | Publish rate |
|---|---|---|
| Heart Rate | Gaussian random walk around patient baseline | 1/2s |
| SpO2 | Beta-distributed, rare desaturations | 1/2s |
| Blood Pressure | Correlated systolic/diastolic pair | 1/5s |
| Respiratory Rate | Poisson-like integer | 1/4s |
| Temperature | Slow walk, circadian variation | 1/10s |

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
```

Kafka message format (JSON):
```json
{"patient_id": "P-001", "signal_type": "heart_rate", "value": 104.3, "timestamp": 1744123456789}
```

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
3. Record appended to in-memory write buffer
4. Buffer flushed to InfluxDB Cloud every 1s (or when buffer hits 500 records)

### Grafana alerting

- **State timeline panel**: one per patient, shows `alarm_level` tag over time — visually compelling for demo
- **Threshold lines**: drawn on each signal panel as static visual reference
- **Alert rules**: Flux query counts `alarm_level = "critical"` in last 30s → fires webhook or email

---

## Infrastructure

| Component | Hosting | Cost |
|---|---|---|
| NATS JetStream + all Python services | Hetzner CX21 (2 vCPU, 4GB RAM) | €4.50/month |
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

- [docker-compose.yml](docker-compose.yml) — NATS JetStream only (remove Kafka/Zookeeper)
- [producer.py](producer.py) → `producer/patient_producer.py` — async NATS publisher
- [spark_processor.py](spark_processor.py) → `brain/` — evaluator + influx_writer (no Spark)
- **New**: `config/settings.py`, `config/thresholds.py`, `data/generators/`, `data/profiles/`, `grafana/provisioning/`

## Verification

1. `docker compose up` → NATS JetStream healthy
2. `python producer/main.py` → 6 patients publishing (`nats sub 'vitals.>'` shows messages)
3. `python brain/main.py` → alarm_level appearing in InfluxDB Cloud
4. Grafana Cloud dashboard auto-provisioned, state timeline shows alarm transitions
5. Force a critical reading (set baseline above threshold in a profile) → Grafana alert fires
