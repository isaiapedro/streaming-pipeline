# Milestone 1 Report — Scenario Suite + NEWS2 A/B/C Scoring

**Date:** 2026-08-23
**Branch:** `proj-2`
**Plan reference:** `personal/academic_writting/plan.md`, `plan-detailed.md` (checklists updated alongside this report)

---

## 1. What Was Implemented

### 1.0 Cleanup
- Removed orphaned `producer.py` / `spark_processor.py` (legacy single-file Kafka MVP, fully superseded by `producer/` + `brain/`).
- Reverted an uncommitted Kafka service block in `docker-compose.yml` — out of scope until Milestone 2 (Kafka path), and contradicted the repo's own README ("NATS JetStream only").
- Added `.gitignore` (repo had `__pycache__/*.pyc` tracked in git).

### 1.1 L1 — Data Generation

| File | What it does |
|---|---|
| `data/generators/base_generator.py` | Each generator now owns a private `random.Random(signal_seed)` instead of using the global `random` module. Same `signal_seed` → byte-identical trajectory. `signal_seed=None` (default) preserves old non-reproducible live/demo behavior. |
| `data/generators/heart_rate.py`, `spo2.py`, `blood_pressure.py`, `respiratory_rate.py`, `temperature.py` | All 5 generators switched to `self._rng` — no other logic changed. |
| `data/generators/correlation.py` | `correlated_delta(signal_type, latest, baselines, copd_flag)` — additive nudge from sibling signals' deviation from baseline: HR↑→SpO2↓, RR↑→SpO2↓ (stronger if `copd_flag`), HR↑→Temp↑, HR↑→SysBP↓. Pure function, no state. |
| `data/generators/noise.py` | `NoiseInjector` (seeded by `noise_seed`, independent of `signal_seed`) — packet loss, single-sample spikes, dropout windows, clock-drift jitter. `.apply(signal_type, value, timestamp_ms)` returns `(None, ts)` when a reading should be dropped. |
| `data/scenarios/definitions.py` | 6 deterministic scenarios (`Scenario` dataclass): `sepsis_progression`, `cardiac_deterioration`, `copd_exacerbation`, `false_positive_storm`, `hypertensive_crisis`, `stable_baseline`. Each has an exact `onset_offset_ms` (ground truth) and a `delta_at(elapsed_ms)` function shaping additive per-signal offsets (`ramp_sustained` / `step_sustained` / `spike_recover` / `none`). |
| `data/profiles/P-00{1..6}.json` | Added `copd_flag: false` to all 6 profiles. A scenario can override it per-run via `copd_flag_override` (used by `copd_exacerbation`). |

### 1.2 L5 — NEWS2 Composite Scoring (Approaches A / B / C)

| File | What it does |
|---|---|
| `brain/ews_scorer.py` | Pure, stateless NEWS2 lookup tables (RR, SpO2 dual-scale, SysBP, HR, Temp) → `compute_news2(values, copd_flag)` → aggregate int score. `alarm_level(score)`: `<5` ok, `5–6` warning, `≥7` critical. Values are rounded to clinical read-granularity before bucketing (integer for RR/SpO2/BP/HR, 0.1°C for Temp) to avoid gaps between table bands. |
| `brain/ews_window.py` | `PatientEWSState` — holds latest `(value, timestamp)` per signal per patient; `composite_score(now_ms)` returns `(score, window_complete)`, `None` if any of the 5 required signals has never been seen. |
| `brain/approaches.py` | Ties the three approaches together: **A** = existing `brain/evaluator.py` per-signal threshold (unchanged); **B** = `compute_news2` invoked on a fixed ~60s cadence via `BatchScheduler`; **C** = `compute_news2` invoked on every incoming message. B and C share the exact same scorer — cadence is the only difference, which is the thesis's own comparison axis. |
| `brain/main.py` | Rewired to run all three approaches per NATS message and write InfluxDB records tagged `scoring_approach="A"/"B"/"C"` and `scenario_id` (from the message payload, `"none"` if absent). |
| `brain/influx_writer.py` | Added `AlarmRecord` (measurement `alarms`, tags `patient_id/condition/alarm_level/scoring_approach/scenario_id`, field `news2_score`) alongside the existing `VitalRecord` (measurement `patient_vitals`), which now also carries `scoring_approach`/`scenario_id` tags. |
| `producer/patient_producer.py`, `producer/main.py` | New CLI flags: `--scenario {name}`, `--signal-seed`, `--noise-seed`, `--packet-loss`, `--spike-probability`, `--dropout-probability`, `--dropout-duration-s`, `--clock-drift-ms`. When a scenario is active, every published message carries `scenario_id` + `onset_offset_ms` so the brain can tag ground truth downstream. |

### 1.3 Benchmark Harness

`scripts/run_benchmark.py` — **in-process simulation**, no NATS/InfluxDB required. Re-uses the exact same generator/correlation/noise/scenario/scoring modules as the live pipeline. For each of the 6 scenarios × N seed pairs (default 10), runs approaches A/B/C concurrently over one representative synthetic patient and emits `benchmark_results.csv`:

```
scenario, signal_seed, noise_seed, approach, TPR, FPR, detection_latency_ms, alarm_rate_per_day, p99_pipeline_latency_ms
```

`p99_pipeline_latency_ms` is intentionally left blank — that's a live-pipeline metric (NATS→brain→InfluxDB), not something an offline simulation can produce honestly; see §2.3 for how to measure it for real.

### 1.4 Tests

`brain/tests/test_ews_scorer.py` — 58 boundary-value unit tests over every NEWS2 table cutoff, both SpO2 scales, aggregate scoring, and the alarm-level thresholds. All passing.

### 1.5 Not touched (still Milestone 2 scope)
Protobuf schema, Kafka path, Confluent Schema Registry, MQTT/Mosquitto, `config_watcher.py`, scale tiers T2–T4, Grafana A/B/C comparison dashboard.

---

## 2. How To Test

### 2.1 Setup
```bash
cd workspace/academic
./tcc_env/bin/python -m pip install -r requirements.txt   # pytest is now included
```

### 2.2 Unit tests
```bash
./tcc_env/bin/python -m pytest brain/tests/ -q
# expect: 58 passed
```

### 2.3 Benchmark harness (offline, no infra needed)
```bash
./tcc_env/bin/python scripts/run_benchmark.py --runs 10 --out benchmark_results.csv
```
Takes seconds. Open the CSV in a spreadsheet or:
```bash
./tcc_env/bin/python -c "
import csv
from collections import defaultdict
rows = list(csv.DictReader(open('benchmark_results.csv')))
agg = defaultdict(list)
for r in rows:
    agg[(r['scenario'], r['approach'])].append(r)
for k, v in sorted(agg.items()):
    print(k, len(v), 'rows')
"
```
For a proper mean ± std table (what the thesis needs), load into `pandas` and `groupby(['scenario','approach']).agg(['mean','std'])` on `TPR`, `FPR`, `detection_latency_ms`, `alarm_rate_per_day`.

**Caveat:** only smoke-tested at `--runs 2` so far during implementation. Run the full `--runs 10` before citing numbers in the paper — small-sample results (see §5.3) already show real signal but need the full seed sweep to report mean±std honestly.

### 2.4 Live manual scenario run (exercises the real NATS pipeline)
```bash
# 1. Start NATS
docker compose up -d nats

# 2. Create the JetStream stream + durable consumer
bash scripts/create_streams.sh

# 3. Start the brain service (subscribes, scores A/B/C, writes to InfluxDB Cloud)
./tcc_env/bin/python -m brain.main

# 4. In another terminal, run a scenario against all 6 patients
./tcc_env/bin/python -m producer.main --scenario cardiac_deterioration --signal-seed 42 --noise-seed 7

# 5. Watch brain logs for [A]/[B]/[C] alarm lines, or tail the subject directly:
nats sub 'vitals.>'
```
Expect: `[X][A]` lines fire almost immediately once HR/SpO2 cross single-signal thresholds; `[X][C]` composite lines fire shortly after (waits for all 5 signals to be fresh); `[X][B]` lines only fire on the ~60s tick, later and with fewer entries. Check InfluxDB Cloud (`patient_vitals` measurement for A, `alarms` measurement for B/C) — every point is now tagged `scoring_approach` and `scenario_id="cardiac_deterioration"`.

To exercise the noise/dropout layer: add `--packet-loss 0.05 --spike-probability 0.02 --dropout-probability 0.01 --dropout-duration-s 5`.

---

## 3. How To Visualize the Layers

### 3.1 Existing Grafana dashboard (`grafana/provisioning/dashboards/vitals.json`)
Currently shows raw per-signal state timeline + per-signal panels from `patient_vitals`, 5s refresh. It does **not yet** split by `scoring_approach` — that's the Milestone 2 L10 deliverable (side-by-side A/B/C comparison panel). It will still render today, just without approach separation.

### 3.2 Interim Flux queries (usable today — no dashboard changes needed)
Since every point/alarm is now tagged `scoring_approach` and `scenario_id`, you can already compare approaches ad hoc in Grafana Explore or the InfluxDB UI:

```flux
// Alarm rate per approach for a given scenario run
from(bucket: "vitals")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "alarms" and r.scenario_id == "cardiac_deterioration")
  |> filter(fn: (r) => r._field == "news2_score")
  |> group(columns: ["scoring_approach"])
  |> count()
```

```flux
// NEWS2 score trajectory, all 3 approaches overlaid, one patient
from(bucket: "vitals")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "alarms" and r.patient_id == "P-001")
  |> filter(fn: (r) => r._field == "news2_score")
```
Plot this as a state-timeline or line panel grouped by `scoring_approach` → visually reproduces the "detection latency difference" figure the thesis wants (L10), manually, ahead of the provisioned dashboard.

### 3.3 Benchmark CSV visualization
Quick local plot (matplotlib) for detection-latency-by-approach, per scenario:
```python
import pandas as pd
df = pd.read_csv("benchmark_results.csv")
df.groupby(["scenario", "approach"])["detection_latency_ms"].mean().unstack().plot(kind="bar")
```
This is the fastest path to the thesis's core comparison figure — no infra required.

### 3.4 Architecture / pipeline diagram
`diagram.png` at repo root is the existing high-level diagram — still accurate for the MVP data flow (producer → NATS → brain → InfluxDB → Grafana). It does not yet show the A/B/C fan-out inside `brain/`; worth a redraw once Milestone 2 also adds the Kafka path, so it's done once rather than twice.

---

## 4. Progress Status — Full Project (L1–L10)

| Layer | Status | Notes |
|---|---|---|
| **L1** Data generation | 🟡 Mostly done | Correlation, noise/dropout, scenarios, seeds, `copd_flag` all done. Missing: PhysioNet distribution-validation figure (~1 day, not pipeline-blocking). |
| **L2** Edge / Protocol | 🔴 Not started | NATS JetStream (MVP) works; no MQTT, no `config_watcher.py`, no scale-tier runner. Milestone 2. |
| **L3** Message schema | 🔴 Not started | Still plain JSON. No `.proto`, no Kafka path, no Schema Registry. Milestone 2. |
| **L4** Ingestion backbone | 🟢 Done (NATS only) | `VITALS` stream + durable `BRAIN` consumer, pull batch 50/1s — matches MVP spec. Kafka side not started. |
| **L5** Stream processing | 🟢 Done for this milestone | NEWS2 A/B/C fully implemented and wired live + in offline harness. |
| **L6** Storage | 🟡 Partial | `patient_vitals` (A + raw vitals) and `alarms` (B/C) measurements now separated with approach/scenario tags — close to the plan's two-write-path design, minus `threshold_version`/`schema_version` tags (need L3 first). |
| **L7** Security | 🔴 Not addressed | ⚠️ Live InfluxDB Cloud token hardcoded as a default in `config/settings.py:8`, committed to a **public** GitHub repo. Recommend rotating the token and removing the fallback. Not touched this milestone — flagged, not fixed, since rotating a credential/rewriting history isn't a call to make silently. |
| **L8** Compliance/traceability | 🔴 Not started | No `threshold_version`/`schema_version` tags yet (blocked on L3). |
| **L9** Observability & testing | 🟡 Partial | Unit tests exist now (58, `ews_scorer` only). Benchmark harness exists and runs. Missing: `evaluator.py` unit tests, NATS→brain integration test. |
| **L10** Visualization | 🔴 Not started (dashboard) / 🟡 workaround exists | No provisioned A/B/C comparison dashboard yet; ad hoc Flux queries (§3.2) cover the gap for now. |

**Overall:** the thesis's core comparison (A vs B vs C, ground-truth scenarios, reproducible seeds) is now runnable end-to-end, both offline (fast iteration) and live (real pipeline demo). Everything broker/schema/scale-related is still ahead.

---

## 5. What Can Be Written for the Paper Now

### 5.1 Methodology — ready to write
- **Synthetic data generation rationale** (§ "Why Synthetic Data Is the Right Primary Tool" in `plan-detailed.md`) — no changes needed, still accurate, can go in as-is.
- **Generator design** — random-walk/mean-reversion models per signal, now with the actual implementation to cite (file + line references above). Include the correlation model (§1.1) as a subsection — this is a real, implemented contribution, not just a design intent anymore.
- **Seed architecture** (`signal_seed` / `noise_seed`, independent dimensions, fair-comparison rule) — implemented exactly as specced; can describe it in past tense now.
- **Scenario suite** — all 6 scenarios, their trajectory shapes and onset semantics, are implemented and can be described precisely, including the `expect_alarm` ground-truth label used for FPR scenarios.
- **NEWS2 scoring methodology** — the lookup tables, dual SpO2 scale rationale (with the SpO2=90 Scale1-vs-Scale2 divergence as a concrete worked example — it's already a unit test, makes a good paper example), and the A/B/C cadence-only distinction between B and C.

### 5.2 System architecture — ready to write
- Two-tier scoring architecture description, now grounded in actual code structure (`brain/ews_scorer.py`, `ews_window.py`, `approaches.py`) rather than only planned.
- Note honestly in the write-up that B's ~60s cadence is currently *approximated by message arrival* rather than a wall-clock timer (documented in `brain/main.py`) — acceptable at v1 message rates, but worth one sentence acknowledging the simplification if reviewers might probe implementation fidelity.

### 5.3 Preliminary results — write the *shape* now, fill numbers after the full run
A 2-seed-pair smoke test (not the full 10) already shows a plausible, useful pattern worth describing qualitatively while the full run is pending:
- Approach A: fast detection, but FPR = 1.0 on both no-alarm scenarios (false-positive-storm, stable-baseline) — matches the hypothesis that per-signal thresholds over-fire on transient noise.
- Approach B: FPR = 0.0 on both no-alarm scenarios (correctly quiet), but very slow detection latency on gradual-onset scenarios (sepsis ~3 min lag, COPD similar) — the 60s batch tick cost is directly visible and quantifiable.
- Approach C: faster than B, but the smoke test showed nonzero FPR on the false-positive-storm/stable-baseline scenarios too — likely because continuous per-message evaluation gets far more "rolls of the dice" per run than B's ~10 ticks, so it occasionally catches a transient multi-signal noise alignment B would miss entirely. **This is itself a legitimate, citable finding** (a continuous/streaming design trades some false-positive robustness for detection speed relative to fixed-interval batch scoring) — but needs the full 10-seed run and a std-dev band before stating it as a result rather than an observation.
- **Action before writing numbers into the thesis:** run `scripts/run_benchmark.py --runs 10`, aggregate mean±std per (scenario, approach), and only then write the results table/figure.

### 5.4 Limitations section — material to add
- PhysioNet distribution-validation figure still outstanding — flag as "in progress" rather than omit.
- `p99_pipeline_latency_ms` is not yet measured (offline harness can't produce it honestly) — needs a dedicated live-pipeline timing run (§2.4) before the results table can include it.
- Approach B's 60s cadence is message-arrival-approximated, not a true wall-clock scheduler — minor implementation note if asked.
- Security: hardcoded cloud credential in a public repo — worth a sentence in the compliance/security section (L7) as a known MVP shortcut, alongside the already-planned HIPAA/LUKS discussion.

### 5.5 Not yet writeable
Anything about Kafka vs NATS, protobuf/Schema Registry, MQTT comparison, scale tiers (T2–T4), or the Grafana side-by-side dashboard — none of that exists yet (Milestone 2).
