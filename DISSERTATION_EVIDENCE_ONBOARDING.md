# Dissertation Evidence and Visualization Onboarding

## Purpose and evidence boundary

This guide explains how the experiment collects evidence, how to reproduce
each benchmark and visualization, and how to assess every artifact when writing
the dissertation.

The project is a controlled synthetic software experiment. It supports claims
about the declared generators, scenarios, scoring approaches, transports,
persistence boundaries, and measured environment. It does not establish
clinical effectiveness, diagnostic accuracy, production availability,
hospital-scale readiness, or suitability for real patient data.

The main experimental story is a trade-off among run-level detection
reliability, conditional scoring delay, and operational alarm-state burden. No
approach should be presented as a universal winner.

## Evidence reading order

1. Read `evidence/manifest.json` for code identity, worktree state,
   dependencies, inputs, commands, hashes, statuses, and release blockers.
2. Read `evidence/LIMITATIONS.md` before interpreting a number.
3. Read `evidence/RESULTS.md` for the bounded narrative.
4. Use `evidence/benchmark_aggregate.csv` for dissertation estimates.
5. Return to `benchmark_results.csv` for paired seed-cell observations.
6. Use `evidence/experiment_runs.jsonl` to verify run provenance.
7. Use `evidence/FIGURE_CAPTIONS.md` as the minimum interpretation attached
   to each figure.
8. Check `IMPLEMENTATION_BLUEPRINT.md` for remaining implementation and
   execution gates.

An empty value means unavailable or inapplicable, never zero. An unexecuted
gate is neither a pass nor a failure. Consult `release.requested_mode`,
`eligible_for_final_release`, and `blockers` in the manifest rather than
inferring bundle status from prose.

## Experiment design

The primary benchmark crosses six scenarios, five signal seeds, five
independent noise seeds, and three scoring approaches. This produces 25 seed
cells per scenario and approach, 450 approach rows, and 150 run records.
Approaches A/B/C receive the same observations within each seed cell.

Positive scenarios are sepsis progression, cardiac deterioration, COPD
exacerbation, and hypertensive crisis. Negative scenarios are false-positive
storm and stable baseline. Stable-baseline cells simulate 86,400 seconds;
event cells simulate 300 or 600 seconds.

- **A:** independent per-signal thresholds.
- **B:** NEWS2 on an approximately 60-second cadence.
- **C:** the same NEWS2 calculation after each reading.

The scoped NEWS2 inputs are respiratory rate, SpO2, systolic blood pressure,
heart rate, and temperature. Supplemental oxygen and consciousness are fixed
at zero. Composite scoring requires all five readings to be fresh.

An alarm episode opens on the first alarming observation and closes after ten
continuously clear seconds. Detection requires a newly opened episode at or
after the declared onset. An episode already active at onset is not credited.

## Environment setup

```bash
cd /home/pedrosouza/pessoal/master_manager/workspace/academic
python3 -m venv .venv
.venv/bin/python -m pip install --requirement requirements.txt
.venv/bin/python -m pip check
docker compose config --quiet
export MPLCONFIGDIR=/tmp/matplotlib-academic
```

Before a final run, `git status --short` must be empty and
`PIPELINE_VERSION` must identify the chosen implementation commit or tag.
Do not run two evidence generators concurrently.

## A/B/C benchmark and figures

### Collect the complete matrix

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG \
  .venv/bin/python scripts/run_benchmark.py \
  --signal-seeds 5 \
  --noise-seeds 5 \
  --stable-duration-s 86400 \
  --clear-hold-ms 10000 \
  --out benchmark_results.csv \
  --run-log evidence/experiment_runs.jsonl
```

This overwrites the result and run-log paths. Expected outputs are 450 rows in
`benchmark_results.csv` and 150 JSON-lines records in
`evidence/experiment_runs.jsonl`.

### Validate, aggregate, and draw

```bash
.venv/bin/python scripts/aggregate_benchmark.py \
  --input benchmark_results.csv \
  --output evidence/benchmark_aggregate.csv \
  --figures-dir evidence/figures \
  --expected-signal-seeds 5 \
  --expected-noise-seeds 5
```

This produces:

- `abc_detection_latency.png`;
- `abc_false_alarm_probability.png`;
- `abc_alarm_episode_rate.png`;
- `abc_tradeoff.png`;
- `abc_representative_timeline.png`.

Validate without changing figures:

```bash
.venv/bin/python scripts/aggregate_benchmark.py \
  --input benchmark_results.csv \
  --output /tmp/benchmark_aggregate_check.csv \
  --expected-signal-seeds 5 --expected-noise-seeds 5 \
  --no-figures
```

## How to assess benchmark fields

| Field | Interpretation |
| --- | --- |
| `run_id` | Stable seed-cell key for pairing A/B/C |
| `scenario` | Synthetic event or negative condition |
| `signal_seed` | Physiological trajectory variation |
| `noise_seed` | Independent loss/spike/dropout/timing variation |
| `approach` | A, B, or C |
| `duration_s` | Simulated duration |
| `detection_run_rate` | Binary detection outcome for positive scenarios |
| `false_alarm_run_probability` | Binary alarm occurrence for negative scenarios |
| `scoring_detection_latency_ms` | Onset to first new episode; blank if not detected/inapplicable |
| `alarm_observation_count` | Individual alarming scoring observations |
| `alarm_episode_count` | Debounced alarm-state episodes |
| `alarm_episode_rate_per_patient_day` | Episodes normalized by duration |
| `time_in_alarm_ms/pct` | Total time spent in alarm |
| `window_completeness_pct` | Complete/fresh B/C windows |

The aggregate provides non-missing `n`, mean, standard deviation, median,
quartiles, and 95% intervals. Wilson intervals are used for run probabilities;
other current means use deterministic bootstrap intervals. Crossed-seed
dependence is not yet fully modeled, so treat current intervals as descriptive
synthetic-run uncertainty, not patient-population inference.

Latency is conditional on detection. Always report detected runs beside
latency; otherwise a method that detects very few events can look artificially
fast.

## How to read each A/B/C figure

### Detection latency

`abc_detection_latency.png` uses a logarithmic seconds axis. Colored markers
and bars show median and IQR, grey lines show paired cells, and labels such as
`15/25` give the detection denominator.

The current accepted synthetic evidence shows B detecting 25/25 positive runs, with
roughly 30-second median delay for sudden events and 121 seconds for
sepsis/COPD. C detects 20/25 sepsis, cardiac, and hypertensive cells and 25/25
COPD cells. A detects 15/25 sepsis/COPD and 5/25 sudden-event cells. A's short
conditional latency is not superiority: it was often already alarming at
onset.

### False-alarm-run probability

`abc_false_alarm_probability.png` asks whether a negative run contained at
least one episode. Current false-positive-storm estimates are A=1.00, B=0.20,
C=1.00; all approaches equal 1.00 in stable baseline. Use
“false-alarm-run probability,” not clinical false-positive rate.

### Episode burden

`abc_alarm_episode_rate.png` measures episodes per synthetic patient-day.
Stable-baseline means are approximately A=522, B=40, and C=567. In the
false-positive storm they are approximately A=991, B=58, and C=737. These are
analysis-layer episodes, not delivered or acknowledged notifications.

### Joint trade-off

`abc_tradeoff.png` uses conditional median latency on x, negative-scenario
episode burden on y, and detection rate in marker size/label. Lower-left is
desirable, but no method dominates: A is fast only conditionally and highly
burdensome; B is reliable and least burdensome but slow; C is faster for
sudden events but noisier. This is descriptive, not a significance test.
Correct the current Approach A label overlap before final publication.

### Representative timeline

`abc_representative_timeline.png` shows one predeclared sepsis cell: all five
inputs, onset, B/C NEWS2, first new post-onset episodes, and explicit
non-detection. Use it to explain mechanism, not to make aggregate claims.

## NATS/MQTT protocol benchmark

Start the brokers:

```bash
docker compose up -d --wait nats mosquitto
bash scripts/create_streams.sh
```

Partial run without restart-dependent dimensions:

```bash
.venv/bin/python scripts/benchmark_protocol.py \
  --n 100 \
  --out evidence/protocol_benchmark.csv \
  --skip-restarts
```

Full isolated run:

```bash
.venv/bin/python scripts/benchmark_protocol.py \
  --n 500 \
  --out evidence/protocol_benchmark.csv
```

The full command restarts the named broker containers; never use it against
shared services. The forced-disconnect test is a reconnect/redelivery proxy,
not packet-level `tc/netem` loss.

Current partial results are NATS P50/P99 1.63/3.58 ms and MQTT 1.16/5.65 ms
over 100 messages. They describe this local run only and do not establish a
universal protocol ranking.

## Protocol and status figures

```bash
MPLCONFIGDIR=/tmp/matplotlib-academic \
  .venv/bin/python scripts/generate_evidence_status.py
```

The script has no CLI options and overwrites:

- `evidence_status.png`;
- `protocol_latency.png`;
- `scale_status.png`;
- `traceability_status.png`;
- `architecture_status.png`.

`protocol_latency.png` plots local P50/P99 only. `evidence_status.png`
uses green for executed, amber for partial/offline-tested, grey for
unexecuted, and magenta for pending/unimplemented. `traceability_status.png`
separates implemented/unit-tested fields from live stored coverage.
`architecture_status.png` separates implemented core, supplemental Kafka,
unverified live paths, and future suppression.

These are audit/communication figures, not scientific outcomes.

## Publish-to-consume and storage latency

Transport-only:

```bash
.venv/bin/python scripts/measure_live_latency.py \
  --count 100 --timeout 2 --skip-storage \
  --csv-out evidence/live_latency.csv \
  --json-out evidence/live_latency.json
```

Current publish-to-consume P50/P99 is approximately 1.23/1.82 ms. The boundary
is JetStream fetch plus Protobuf decode, not storage.

For confirmed Influx API completion, configure `INFLUX_URL`,
`INFLUX_TOKEN`, `INFLUX_ORG`, and `INFLUX_BUCKET`, then run:

```bash
.venv/bin/python scripts/measure_live_latency.py \
  --count 100 --timeout 5 \
  --csv-out evidence/live_latency.csv \
  --json-out evidence/live_latency.json
```

Record network location, service tier, clocks, machine, and bucket policy.
Reconcile broker input, outbox state, and stored points before claiming
end-to-end completeness.

## Scale benchmark and figure

```bash
docker compose up -d --wait nats
bash scripts/create_streams.sh

.venv/bin/python scripts/run_scale_tier.py \
  --tier T1 --duration 20 --pull-timeout 0.1 \
  --csv-out evidence/scale_results.csv \
  --json-out evidence/scale_T1.json
```

Repeat with `--tier T2/T3/T4` and distinct JSON names. The CSV appends, so a
final series must start in a fresh run directory. T2–T4 require approved
hardware and limits. This harness uses an isolated `scale.>` stream and a
lightweight consumer; it measures transport, not scoring plus storage.

Current T1: target 30 messages/s, achieved 29.98, P50 11.26 ms, P99 14.94 ms,
zero backlog. Generate `scale_status.png` with
`generate_evidence_status.py`. Target crosses for T2–T4 are not
measurements; do not interpolate to them or claim 500-patient readiness.

## Distribution validation and figure

The approved reference and synthetic CSVs must contain `heart_rate`,
`spo2`, `systolic_bp`, `respiratory_rate`, and `temperature`.

```bash
MPLCONFIGDIR=/tmp/matplotlib-academic \
  .venv/bin/python scripts/validate_distributions.py \
  --reference /approved/read-only/reference.csv \
  --synthetic /approved/read-only/synthetic.csv \
  --source-id APPROVED_SOURCE_ID \
  --transformation-method VERSIONED_METHOD_ID \
  --out-dir evidence/distribution
```

Outputs are `synthetic_vs_reference.png`, `kl_divergence.csv`, and
`provenance.json`. Source rows stay outside Git. Smaller KL means closer
histograms under the declared bins/smoothing, not clinical validity.

The implementation records `KL(P_synthetic || P_reference)`. Do not cite KL
until a methodology decision freezes direction, bins, smoothing,
transformation, and source approval.

## Traceability and outbox collection

Audit an approved Influx export:

```bash
.venv/bin/python scripts/audit_traceability.py \
  --input-csv /approved/read-only/influx_export.csv \
  --output evidence/traceability_audit.json \
  --require-complete
```

Or query the configured live bucket:

```bash
.venv/bin/python scripts/audit_traceability.py \
  --live --range 1h \
  --output evidence/traceability_audit.json \
  --require-complete
```

Audit local durable handoff:

```bash
.venv/bin/python scripts/audit_outbox.py \
  --database .runtime/influx_outbox.sqlite3 \
  --output evidence/outbox_health.json \
  --require-healthy
```

Both outputs are aggregate and privacy-safe. Neither establishes remote
storage completeness without reconciliation.

## Grafana visualizations

Offline validation:

```bash
.venv/bin/python -m json.tool \
  grafana/provisioning/dashboards/comparison.json >/dev/null
.venv/bin/python -m pytest -q brain/tests/test_telemetry.py
```

NEWS2 panels contain B/C only. A/B/C alarm views union A vital telemetry with
B/C alarm telemetry. The synthetic alert is paused and has no committed
destination.

Before dissertation screenshots: parameterize the governed bucket, add a real
onset source or annotation, validate live queries/rendering against final
telemetry, and exercise only an approved synthetic notification destination.
The local `ALARMS` stream is not evidence of external notification delivery.

## Manifest, visualization refresh, and checksums

Create an inspectable development manifest:

```bash
.venv/bin/python scripts/build_evidence_manifest.py \
  --mode development \
  --benchmark-input benchmark_results.csv \
  --run-log evidence/experiment_runs.jsonl
```

Generate status figures, then refresh and verify checksums:

```bash
MPLCONFIGDIR=/tmp/matplotlib-academic \
  .venv/bin/python scripts/generate_evidence_status.py
.venv/bin/python scripts/build_evidence_manifest.py --checksum-only
(cd evidence && sha256sum --check SHA256SUMS)
```

Final mode fails closed:

```bash
.venv/bin/python scripts/build_evidence_manifest.py \
  --mode final \
  --benchmark-input benchmark_results.csv \
  --run-log evidence/experiment_runs.jsonl
```

Follow the two-commit evidence/attestation procedure in
`OPERATIONS_AND_REPRODUCIBILITY.md`. Never edit manifests, logs, CSVs, or
checksums manually to bypass blockers.

## Dissertation placement

### Methodology

Describe generators, scenarios, independent seeds, crossed/paired design,
NEWS2 scope, freshness, clear hold, episode and detection definitions, metrics,
uncertainty, run provenance, manifest, and checksums.

### Results

1. Confirm the 450-row matrix and 150 run records.
2. Report detection denominators and conditional latency.
3. Report negative-run alarm occurrence.
4. Report episode burden and time in alarm.
5. Present the trade-off figure.
6. Use the timeline to explain mechanism.
7. Present protocol latency separately.
8. Present only executed scale tiers.
9. End with evidence/traceability completeness.

### Discussion

Explain that B trades delay for reliability and lower fragmentation, C reacts
quickly but more often to noise, and A's sustained alarm state undermines both
usability and conditional-latency interpretation. Stable-baseline behavior is
generator/threshold sensitivity until reference and sensitivity analyses pass.

### Limitations

State: synthetic inputs; no clinician-adjudicated outcomes; probabilities are
not clinical TPR/FPR; crossed-seed dependence remains incomplete; latency is
conditional on detection; episodes are not notifications; storage/Grafana
delivery and T2–T4 are unexecuted; and final evidence needs a clean rerun.

## Result-writing template

For every result: state the observation, denominator/uncertainty, comparable
approaches, plausible mechanism, and evidence boundary.

Example:

> In 25 synthetic sepsis seed cells, Approach B opened a new post-onset alarm
> episode in 25/25 runs (estimate 1.00; Wilson 95% CI 0.867–1.00), compared
> with 20/25 for C and 15/25 for A. Among detected runs, B's median scoring
> delay was approximately 121 seconds, consistent with its periodic cadence.
> These results characterize the declared synthetic scenarios and do not
> estimate clinical sensitivity.

## Claims

Permitted with a development/synthetic qualifier:

- B achieved the highest run-level detection reliability.
- B produced fewer alarm episodes.
- Continuous scoring reduced conditional latency for sudden events.
- The experiment shows a reliability–latency–burden trade-off.
- Local publish-to-consume latency was low-millisecond in the measured setup.

Do not claim clinical sensitivity, prevention of alarm fatigue, universal
protocol superiority, 500-patient readiness, confirmed 1.8-ms storage latency,
validated Grafana delivery, or clinical realism.

## Final closure order

1. Freeze dependence-aware inference and non-detection handling.
2. Implement crash-safe provenance and remaining telemetry recovery work.
3. Resolve the KL methodology.
4. Select the clean implementation commit and exact environment.
5. Rerun the full matrix and all approved live gates.
6. Regenerate aggregates and every figure.
7. Execute approved scale/reference/storage/Grafana work or mark it
   unexecuted.
8. Build and review the development bundle.
9. Complete the evidence-only commit and final attestation sequence.
10. Approve the maximum evidence level and limitations for every claim.
