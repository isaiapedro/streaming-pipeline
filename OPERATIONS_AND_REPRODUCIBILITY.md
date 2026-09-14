# Operations, maintenance, and reproducibility guide

## Purpose and safety boundary

This document is the canonical operator guide for the academic patient-vitals
streaming prototype. It explains what each feature does, how to run it, how to
maintain it, and how to produce evidence without relying on undocumented local
workarounds.

The system uses synthetic patients. It is research software, not a clinical
device and not a source of clinical advice. Do not send real patient data,
Personal-domain records, credentials, or row-level clinical reference data to
the repository, logs, evidence directory, DLQ, screenshots, or dashboards.

All commands in this guide are run from the nested repository root:

```bash
cd /home/pedrosouza/pessoal/master_manager/workspace/academic
```

The absolute path above is a workspace convenience, not a runtime dependency.
The repository must also work from an arbitrary clean-clone location.

## Feature catalog

| Feature | Entry point or location | What it does | Current assurance boundary |
| --- | --- | --- | --- |
| Synthetic profiles and generators | `data/profiles/`, `data/generators/` | Produces seeded or live synthetic HR, SpO2, BP, RR, and temperature | Synthetic behavior only; distribution validation is separate |
| Scenario suite | `data/scenarios/definitions.py` | Applies six deterministic deterioration/stability trajectories with declared onset | Designed ground truth, not clinician-adjudicated ground truth |
| Approach A | `brain/evaluator.py` | Scores each signal independently using a versioned threshold snapshot | Prototype threshold comparison |
| Approach B | `brain/approaches.py` | Computes the composite rule at an approximately 60-second cadence | Five measured NEWS2 inputs; oxygen/consciousness fixed to zero |
| Approach C | `brain/approaches.py` | Recomputes the same composite rule after each incoming reading | Same constrained NEWS2 scope as B |
| NATS transport | `producer/`, `brain/main.py`, `nats/` | Durable edge stream, explicit-ack consumer, schema validation, separate DLQ | Valid input is acknowledged after the local durable outbox commit, not remote Influx delivery |
| Local alarm stream | `brain/local_scorer.py` | Emits priority-preserving events to a seven-day file-backed `ALARMS` stream | Publish-confirmed before source ACK; scorer state is memory-only and no notification consumer exists |
| MQTT comparison | `producer/main.py --dual-mqtt`, `brain/mqtt_consumer.py` | Mirrors slash-hierarchy messages through Mosquitto with QoS 1, bounded subscription, and DLQ-before-source-ACK rejection | PUBACK proves broker receipt, not durable archive; NATS/MQTT publication is not atomic |
| Kafka validation comparison | `kafka_path/`, Compose `kafka` profile | Isolated Protobuf/Schema Registry producer, validator, manual-offset consumer, DLQ | Validation/acceptance/rejection/latency only; no Brain scoring, outbox, storage, or alarm parity |
| InfluxDB telemetry | `brain/influx_writer.py` | Persists records to a private SQLite WAL outbox, then delivers retryable batches with provenance tags | Local outbox durability and idempotent replay; remote Influx availability is asynchronous |
| Grafana comparison | `grafana/provisioning/` | Displays A/B/C results and version metadata; alert rule is paused | Validate against final telemetry before release |
| Offline benchmark | `scripts/run_benchmark.py` | Runs six scenarios across crossed signal/noise seeds for A/B/C, including the 24-hour stable baseline | Clean portable offline evidence is attested; broader scientific gaps remain separate |
| Aggregation and figures | `scripts/aggregate_benchmark.py` | Validates the 450-row result matrix and generates aggregates/figures | The tracked raw input and current aggregate conform to the frozen matrix contract |
| Protocol benchmark | `scripts/benchmark_protocol.py` | Compares local NATS and MQTT transport dimensions | Some dimensions require container restart access |
| Live latency | `scripts/measure_live_latency.py` | Measures publish-to-consume and optional successful-storage latency | Storage is unexecuted when `--skip-storage` is used |
| Scale tiers | `scripts/run_scale_tier.py` | Exercises isolated NATS transport from T1 through T4 | Transport-only; not full scoring/storage scale |
| Distribution validation | `scripts/validate_distributions.py` | Compares approved external and synthetic aggregates | Reference rows remain outside Git |
| Evidence bundle | `evidence/` | Holds privacy-safe aggregates, figures, manifest, limitations, checksums | A dirty worktree is development evidence only |

## Repository and external boundaries

This directory is an independently governed nested Git repository. Commit its
files here, not from the parent repository.

External resources are optional, explicit inputs:

- `knowledge/health/` supplies objective scientific source material. Runtime
  code must not import or traverse it.
- `docs/` is the parent workspace's on-demand technical library. It is not
  copied into experiment artifacts.
- `registry/PORTS.md` and `registry/repositories.yaml` are the parent workspace
  authorities for host ports and repository boundaries.
- `personal/academic_writting/` is private author storage. It is prohibited as
  a runtime, test, or evidence input.
- Approved reference datasets remain outside Git. Pass their paths explicitly,
  mount them read-only where possible, and record a non-sensitive source ID,
  license/DUA status, transformation method, and content hash.
- InfluxDB and Grafana Cloud are optional external services. Store their
  credentials only in the ignored local environment and label their results as
  hosted rather than local.

No final command may depend on `../` traversal, an author's home-directory
layout, notebook state, manually edited output, or pre-existing broker state.

## Prerequisites

Required for offline work:

- Python 3 with `venv` support;
- Git;
- enough disk space for the environment and generated figures.

Required for live local infrastructure:

- Docker Engine with Compose v2;
- NATS CLI for `scripts/create_streams.sh`;
- `curl` for host health checks and `openssl` for the disposable secure-NATS test;
- local permission to inspect listening ports.

Optional:

- InfluxDB Cloud account for storage and telemetry runs;
- Grafana for dashboard import/provisioning;
- approved external reference data for distribution validation.

For a final evidence run, record exact tool versions and pin container images
by digest. Mutable image tags such as `nats:2.10-alpine` are convenient for
development but insufficient for a frozen release.

## Environment setup

Create a fresh environment instead of reusing `tcc_env` for release evidence:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

Do not commit `.venv`, `tcc_env`, `.env`, certificates, tokens, broker volumes,
or caches.

The runtime accepts these environment variables:

| Variable | Required when | Meaning |
| --- | --- | --- |
| `PIPELINE_VERSION` | Final runs | Immutable build/release identifier; never leave as `dev` |
| `NATS_URL` | Non-default or secure NATS | NATS client URL; default is `nats://localhost:4222` |
| `NATS_USER`, `NATS_PASSWORD` | Authenticated NATS | Both must be provided together |
| `NATS_TLS` | TLS NATS | Set to `true` |
| `NATS_CA_FILE` | Private/development CA | CA certificate path |
| `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, `INFLUX_BUCKET` | Storage-backed Brain or latency run | InfluxDB connection and target |
| `INFLUX_OUTBOX_PATH` | Optional storage override | SQLite outbox path; default `.runtime/influx_outbox.sqlite3`, resolved from the project root |
| `INFLUX_OUTBOX_MAX_RECORDS` | Capacity policy | Maximum retained outbox records; capacity exhaustion applies broker backpressure |
| `INFLUX_OUTBOX_MAX_ATTEMPTS` | Failure policy | Retry attempts before private terminal quarantine; default `10` |
| `INFLUX_TIMEOUT_MS` | Influx delivery | Per-write timeout in milliseconds |
| `INFLUX_RETRY_BASE_S`, `INFLUX_RETRY_MAX_S` | Influx delivery | Bounds exponential retry delays for retained failures |
| `FLUSH_INTERVAL_S`, `FLUSH_BUFFER_SIZE` | Influx delivery | Delivery wake interval and maximum batch size |
| `KAFKA_BOOTSTRAP_SERVERS` | Non-default Kafka | Default `localhost:19092` |
| `SCHEMA_REGISTRY_URL` | Kafka path | Default `http://localhost:18081` |
| `KAFKA_GROUP_ID` | Kafka override | Isolated consumer group name; topic names are fixed by the provisioned research contract |
| `KAFKA_SCHEMA_COMPATIBILITY` | Kafka schema governance | Expected compatibility policy; default `BACKWARD_TRANSITIVE` |
| `REQUIRE_NATS_INTEGRATION` | Required live NATS test | Makes unavailable or insecure infrastructure fail rather than skip |
| `REQUIRE_KAFKA_INTEGRATION` | Required live Kafka test | Makes unavailable Kafka/Schema Registry fail rather than skip |
| `REQUIRE_MQTT_INTEGRATION` | Required live MQTT test | Makes unavailable Mosquitto fail rather than skip |

Use a local ignored `.env` only for development. A release run should inject
secrets from the operator environment and retain only a sanitized list of which
variables were configured, never their values.

## Port and infrastructure preflight

Current host mappings are:

| Port | Interface | Status |
| --- | --- | --- |
| 1883 | Mosquitto | Reserved for Academic; loopback-only |
| 4222 | NATS client | Reserved for Academic; loopback-only |
| 8222 | NATS monitoring | Reserved for Academic; loopback-only |
| 19092 | Kafka client | Academic research comparison; loopback-only |
| 18081 | Schema Registry | Academic research comparison; loopback-only |

Inspect without changing other services:

```bash
ss -ltnp | rg ':(1883|4222|8222|18081|19092)\b'
docker ps --format 'table {{.Names}}\t{{.Ports}}'
docker compose config --quiet
.venv/bin/python scripts/infrastructure_doctor.py --profile nats
```

If a port is occupied, identify its owner. Do not stop an unrelated service as
a workaround. Compose, the academic decision, and the workspace port registry
must continue to agree.

Internal Kafka ports 29092 and 29093 are Compose-network interfaces and do not
need host reservations unless they are published later.

## Fast path: offline verification

The offline suite is the default developer gate and does not require a broker
or cloud account:

```bash
.venv/bin/python -m pytest -q
```

Infrastructure tests may skip when their explicit `REQUIRE_*_INTEGRATION`
variable is absent. A skipped live test is neither a pass nor a failure of that
infrastructure; record it as unexecuted.

Additional static checks:

```bash
.venv/bin/python -m compileall -q brain config data kafka_path producer schema scripts
.venv/bin/python -m json.tool grafana/provisioning/dashboards/comparison.json >/dev/null
git diff --check
```

## Local NATS pipeline

Start only the services needed for the selected experiment:

```bash
docker compose up -d nats
docker compose ps
bash scripts/create_streams.sh
```

`create_streams.sh` creates or reconciles and then verifies file-backed
`VITALS` (24 hours), `VITALS_DLQ` (24 hours), and `ALARMS` (seven days), plus
the `BRAIN` and `LOCAL_SCORER` explicit-ack consumers. Configuration drift or a
CLI/authentication failure aborts provisioning.

Run each long-lived component in its own terminal so shutdown remains explicit.

Terminal 1, Brain plus InfluxDB writes:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python -m brain.main
```

Terminal 2, deterministic producer example:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python -m producer.main \
  --scenario sepsis_progression --signal-seed 1000 --noise-seed 2000
```

Optional alternative scorer:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python -m brain.local_scorer
```

Stop the producer and consumers with Ctrl+C and confirm clean shutdown. Inspect
state without deleting it:

```bash
nats --server "${NATS_URL:-nats://localhost:4222}" stream info VITALS
nats --server "${NATS_URL:-nats://localhost:4222}" stream info VITALS_DLQ
nats --server "${NATS_URL:-nats://localhost:4222}" stream info ALARMS
nats --server "${NATS_URL:-nats://localhost:4222}" consumer info VITALS BRAIN
nats --server "${NATS_URL:-nats://localhost:4222}" consumer info VITALS LOCAL_SCORER
docker compose ps
```

Use `docker compose stop nats` when finished. Do not use `down -v` in a routine
workflow because it deletes persistent volumes.

## Secure local NATS profile

Generate development certificates only when testing the secure profile:

```bash
bash scripts/generate_dev_tls.sh
docker compose --profile secure up -d nats-secure
docker compose ps
```

Set `NATS_USER`, `NATS_PASSWORD`, `NATS_TLS=true`, `NATS_CA_FILE`, and the
matching `NATS_URL` before provisioning or connecting. The insecure `nats` and
secure `nats-secure` services both claim ports 4222 and 8222; they are mutually
exclusive on one host.

Run the required integration gate:

```bash
REQUIRE_NATS_INTEGRATION=true .venv/bin/python -m pytest -q \
  brain/tests/test_integration_nats.py
```

For an isolated automated authentication/trust check, first stop insecure NATS
and run `.venv/bin/python scripts/verify_secure_nats.py`. It creates disposable
credentials and certificates in a uniquely named Compose project, verifies
authenticated TLS plus anonymous/wrong-password/untrusted-CA rejection, and
removes the test container afterward.

## MQTT comparison

Start NATS and Mosquitto, then provision NATS:

```bash
docker compose up -d nats mosquitto
bash scripts/create_streams.sh
```

Run the MQTT Brain in one terminal:

```bash
.venv/bin/python -m brain.mqtt_consumer
```

Run the dual publisher in another:

```bash
.venv/bin/python -m producer.main --dual-mqtt \
  --scenario stable_baseline --signal-seed 1000 --noise-seed 2000
```

This is a transport comparison. MQTT uses
`vitals/{patient_id}/{signal_type}` and subscribes only to `vitals/#`. Valid
input is manually acknowledged after its local durable outbox handoff. Invalid
input is acknowledged after a confirmed QoS 1 publication to
`dlq/vitals/mqtt`. PUBACK proves broker receipt, not durable archival or later
consumption. The dual publisher treats NATS and MQTT as independent writes.

Run `REQUIRE_MQTT_INTEGRATION=true .venv/bin/python -m pytest -q
brain/tests/test_integration_mqtt.py` for the live invalid-message gate.

Run the protocol harness only when its declared prerequisites are available:

```bash
.venv/bin/python scripts/benchmark_protocol.py --n 100 \
  --out evidence/protocol_benchmark.csv --skip-restarts
```

Omitting `--skip-restarts` authorizes the harness to restart its specifically
named local broker containers. Do not run that mode against shared or remote
infrastructure.

## Kafka validation comparison

The root Registry reserves loopback ports 19092 and 18081 for this isolated
profile. Start only its named services:

```bash
docker compose --profile kafka up -d kafka schema-registry
docker compose --profile kafka ps
bash scripts/create_kafka_topics.sh
.venv/bin/python -m kafka_path.provision
REQUIRE_KAFKA_INTEGRATION=true .venv/bin/python -m pytest -q \
  brain/tests/test_integration_kafka.py brain/tests/test_kafka_transport.py
```

Smoke-test with the consumer in one terminal:

```bash
.venv/bin/python -m kafka_path.consumer --max-messages 1
```

Then publish in another:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python -m kafka_path.producer \
  --patient-id P-001 --signal-type heart_rate --value 80 --count 1
```

The producer waits for broker delivery confirmation. The consumer disables
automatic offset commit/storage and commits synchronously only after a valid
synchronous handler completes, or after a rejected record is confirmed in the
DLQ. The shipped handler prints a validated record; it does not provide Brain
scoring, outbox persistence, Influx delivery, or alarms and must not be
described as runtime parity.

## Acknowledgement and durability semantics

NATS JetStream and Kafka provide at-least-once delivery in the configured
paths. Duplicate processing remains possible, so output writes must be
idempotent.

Current NATS Brain behavior:

1. Invalid input is acknowledged only after confirmed DLQ publication.
2. Valid input is decoded and scored without committing its in-memory state.
3. Every derived record is committed atomically to the local SQLite WAL
   outbox. Capacity or commit failure leaves the broker message unacknowledged
   and rolls back the tentative scoring state.
4. The NATS message is synchronously acknowledged after that local commit.
5. Influx delivery runs asynchronously. Retriable failures remain in the
   outbox with bounded exponential retry across restart; non-retriable or
   exhausted failures move to private terminal quarantine.

Therefore an acknowledgement means “committed to the local durable outbox,”
not “stored in remote InfluxDB.” Hashed source receipts suppress duplicate
derived batches on redelivery, including after configuration changes. Never call this remote end-to-end
durability. Monitor `AckWait`, `MaxDeliver`, `MaxAckPending`, outbox pending
count, retry attempts, last error, disk capacity, and maximum-delivery
advisories; quarantine terminal failures under an approved retention policy.

MQTT uses the same valid-record outbox boundary. Invalid input is source-ACKed
only after `dlq/vitals/mqtt` PUBACK. The local NATS scorer instead awaits an
`ALARMS` JetStream publish acknowledgement before source ACK; its scoring state
is memory-only, so no restart-continuity claim is made. Kafka commits a valid
record after its synchronous validation handler completes, or a poison record
after confirmed DLQ delivery; the shipped handler is not durable storage.

Official NATS consumer semantics:
<https://docs.nats.io/nats-concepts/jetstream/consumers>

## Reproduce the offline experiment

Final evidence must start from a clean, identified commit. Do not regenerate
release evidence while another worker is editing the worktree.

The frozen offline package contains the complete 450-row crossed-seed design
and a portable final attestation. The stable-baseline rows record 86,400
seconds. Metric semantics use debounced episodes, Wilson intervals for
probabilities, and bootstrap intervals plus quartiles for other outcomes. A new
implementation commit requires a new governed evidence chain; do not edit CSV
files manually.

Preflight:

```bash
git status --short
git rev-parse HEAD
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
```

`git status --short` must be empty. Set `PIPELINE_VERSION` to the clean commit
or signed tag. Once the evidence lane is corrected and tested, generate the raw
benchmark, checked aggregate, figures, manifest, and checksums in that order:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python scripts/run_benchmark.py \
  --signal-seeds 5 --noise-seeds 5 \
  --stable-duration-s 86400 --clear-hold-ms 10000 \
  --out benchmark_results.csv \
  --run-log evidence/experiment_runs.jsonl
.venv/bin/python scripts/aggregate_benchmark.py \
  --input benchmark_results.csv \
  --output evidence/benchmark_aggregate.csv \
  --figures-dir evidence/figures \
  --expected-signal-seeds 5 --expected-noise-seeds 5
.venv/bin/python scripts/build_evidence_manifest.py
(cd evidence && sha256sum --check SHA256SUMS)
```

Development mode records dirty-state, dependency, matrix, duration, run-log,
and input-hash blockers for inspection. Final mode refuses to overwrite the
manifest while any blocker remains. The manifest records the versioned raw
benchmark's hash even though `SHA256SUMS` is scoped to `evidence/`.

Review and commit the generated `evidence/` directory as an evidence-only
commit. From that clean commit, run `build_evidence_manifest.py --mode final`.
The gate proves that the run-log implementation commit is its ancestor and
rejects any intervening change outside `evidence/` and the exact governed root
artifact `benchmark_results.csv`; the manifest records both the measured
implementation and attestation-base commits. Commit the final
manifest and checksums as a second evidence-only attestation commit.

### Recover an interrupted benchmark

The runner writes a hidden journal beside the run log after every seed cell.
Each append is flushed and `fsync`ed before the next cell begins. Public output
files are replaced atomically only after all cells complete, so an interrupted
run does not partially overwrite the last reviewed package.

Resume with the identical commit, `PIPELINE_VERSION`, seeds, scenarios,
durations, clear-hold setting, and noise configuration:

```bash
PIPELINE_VERSION=CLEAN_COMMIT_OR_TAG .venv/bin/python scripts/run_benchmark.py \
  --signal-seeds 5 --noise-seeds 5 \
  --stable-duration-s 86400 --clear-hold-ms 10000 \
  --out benchmark_results.csv \
  --run-log evidence/experiment_runs.jsonl \
  --resume
```

Resume fails closed if the journal is missing, corrupt at a complete record,
contains an unknown cell, or has a different protocol fingerprint. It repairs
only an incomplete final append. To start a deliberately different run, retain
or archive the existing journal as governed evidence before selecting a new
journal path with `--journal`; never silently overwrite it.

The notebook may explore or display results, but it is not an authoritative
transformation. All release tables and figures must be reproducible through
versioned non-interactive scripts.

## Live evidence runs

### Publish-to-consume and publish-to-storage latency

Transport-only:

```bash
.venv/bin/python scripts/measure_live_latency.py --count 100 --skip-storage \
  --csv-out evidence/live_latency.csv \
  --json-out evidence/live_latency.json
```

End-to-storage requires all Influx variables and omits `--skip-storage`:

```bash
.venv/bin/python scripts/measure_live_latency.py --count 100 \
  --csv-out evidence/live_latency.csv \
  --json-out evidence/live_latency.json
```

Successful API return is the harness's storage boundary. Record clock method,
network location, service tier, and configuration with the result.

### Scale tiers

Run one tier at a time on approved hardware:

```bash
.venv/bin/python scripts/run_scale_tier.py --tier T1 --duration 20 \
  --pull-timeout 0.1 \
  --csv-out evidence/scale_results.csv \
  --json-out evidence/scale_T1.json
```

Repeat explicitly for T2, T3, and T4 with distinct JSON paths. The CSV appends,
so begin a final series from a newly created run directory rather than editing
or truncating a historical file. Record requested, attempted, published,
received, decoded, acknowledged, failed, and peak-backlog counts after the
harness is upgraded; current results lack some of these diagnostics.

Scale tests use an isolated `scale.>` stream and measure transport, not the
complete scoring and storage system.

### Approved-reference distribution validation

```bash
.venv/bin/python scripts/validate_distributions.py \
  --reference /approved/read-only/reference.csv \
  --synthetic /approved/read-only/synthetic.csv \
  --source-id APPROVED_SOURCE_ID \
  --transformation-method VERSIONED_METHOD_ID \
  --out-dir evidence/distribution
```

The path is operator-local and must not be persisted in portable manifests.
Review every generated artifact for row-level leakage before adding it to the
evidence bundle. The implemented direction is explicitly
`KL(P_synthetic || P_reference)`; source approval, transformation, bins, and
smoothing must still be frozen before scientific use.

## Indexing and storage design

### Evidence index

`evidence/manifest.json` is the authoritative artifact index. For each
publishable file it records:

- logical artifact ID and role (`input`, `raw_result`, `aggregate`, `figure`,
  `log`, or `provenance`);
- relative path and media type;
- SHA-256 hash and size;
- generating command/activity;
- source artifact IDs;
- evidence status (`executed`, `partial`, `unexecuted`, or `invalidated`).

Checksums detect accidental changes; signed attestations and independently
stored releases provide stronger tamper evidence.

### InfluxDB query index

InfluxDB indexes tags in the current Cloud/TSM data model. Keep bounded,
frequently filtered metadata as tags:

- patient ID for the six-patient synthetic prototype;
- signal type, condition, alarm level, scoring approach, scenario;
- schema, pipeline, threshold version, and transport.

Keep measured and unbounded values as fields:

- vital value, NEWS2 score, window completeness where aggregation is useful;
- event/run IDs, content hashes, free text, durations, and sequence numbers
  unless a demonstrated query requires indexing them.

Before T2–T4, calculate expected series cardinality from the cross-product of
tag values and verify actual cardinality. Do not add seed, timestamp, raw value,
or random UUID tags. InfluxData recommends tags for commonly queried metadata
and fields for unique or highly variable values because uncontrolled tag sets
can create excessive series cardinality:
<https://docs.influxdata.com/influxdb/cloud/write-data/best-practices/schema-design/>.

## Maintenance procedures

### Routine change

For every change:

1. Identify its owning worker lane and affected requirement/risk IDs.
2. Branch or create a worktree from the coordinator's exact baseline.
3. Add or update tests before generating evidence.
4. Run the offline gate and relevant live gate.
5. Commit only the owning lane's files.
6. Integrate in the worker and release order defined by
   `IMPLEMENTATION_BLUEPRINT.md`.
7. Regenerate final evidence only after the runtime and schema are frozen.

### Dependency update

1. Update the declared requirement and lock information together.
2. Build a fresh environment; do not validate using an environment with old
   transitive packages.
3. Run `pip check`, all offline tests, and affected live integrations.
4. Generate an SBOM and vulnerability report for the candidate release.
5. Record the reason and compatibility impact.

### Schema change

1. Add a coordinator-owned decision before editing the canonical schema.
2. Add compatible and incompatible evolution fixtures.
3. Regenerate Protobuf bindings deterministically.
4. Run NATS validation and Kafka Schema Registry compatibility tests.
5. Update telemetry/dashboard contracts and bump `SCHEMA_VERSION`.
6. Never reuse old evidence after a schema change.

### Threshold or scoring change

1. Link the change to its authoritative scientific source and intended-use
   scope.
2. Add golden boundary, missing-data, stale-data, and escalation tests.
3. Bump or recompute the threshold/rule version.
4. Run all A/B/C paired scenarios.
5. Treat previous comparative evidence as superseded, not silently comparable.

### Infrastructure or port change

1. Resolve host ownership in root `registry/PORTS.md`.
2. Update Compose, the academic decision record, and operator documentation in
   the same governed change.
3. Render and validate Compose configuration.
4. Test startup from empty disposable state and from declared persistent state.
5. Pin final images by digest and record configuration hashes.

### Retention, backup, and recovery

Retention values in `TELEMETRY_CONTRACT.md` are proposals until approved and
verified against the service. Record only non-secret confirmation. For each
persistent broker or store, maintain either a tested backup/restore procedure
or an explicit reconstruction-from-immutable-inputs procedure. Execute a
recovery exercise before a V2 claim.

The `.runtime/` outbox is operational state and is intentionally ignored by
Git. Restrict its directory/file permissions to `0700`/`0600`, monitor its row
count and filesystem capacity, and stop ingest or expand the governed capacity
before `INFLUX_OUTBOX_MAX_RECORDS` is reached. Back up the SQLite database with
a SQLite-aware online backup while the service is running, or stop the service
cleanly and copy the database plus its WAL state together. Test restoration in
an isolated directory and verify `PRAGMA integrity_check` and pending-record
replay before declaring recovery successful.

### Credential maintenance

Rotate credentials outside Git. Record credential class, owner, rotation date,
and verification result, never the value. A previously exposed credential is
not remediated merely because it was removed from the current file.

## Troubleshooting without hidden workarounds

- If `pytest` is not found, use `.venv/bin/python -m pytest`; do not depend on a
  globally installed command.
- If a live test skips, set the corresponding `REQUIRE_*_INTEGRATION=true` only
  after starting the governed infrastructure. Do not edit the skip condition.
- If a port is busy, identify the registered owner. Do not kill processes or
  remap ports without updating governance.
- If provisioning finds existing broker resources, compare their complete
  configuration. Do not accept existence as conformance.
- If an evidence command fails, retain its status and logs in an isolated run
  directory. Do not patch the CSV or figure manually.
- If a tier cannot execute on the available hardware, record `unexecuted` with
  the reason. Do not report it as passed, failed, or extrapolated.
- If InfluxDB is unavailable, use offline tests or explicitly `--skip-storage`.
  Do not relabel transport latency as storage latency.
- If external reference data are unavailable, leave distribution validation
  unexecuted. Do not substitute unapproved data.

## Release checklist

A dissertation/demo evidence release is ready only when:

- the nested worktree is clean and the commit/tag is identified;
- requirements match the fresh installed environment;
- offline tests pass and live tests have explicit pass/skip records;
- host ports match the root Registry;
- the Kafka decision, implementation, README, reports, and Compose agree;
- acknowledgements occur only after the declared local durability boundary,
  and remote storage is claimed only when separately reconciled;
- NEWS2 scope and scientific corrections recorded in `DECISIONS.md` and the
  remaining blueprint are complete;
- raw experiment inputs and every evidence output are indexed and hashed;
- no prohibited data or secrets are present;
- another clean environment reproduces the aggregate tables and figures;
- claims remain at or below their verified V0–V4 evidence level.

Completed implementation and verification are in `IMPLEMENTED.md`; accepted
decisions, owner decisions, and gaps are in `DECISIONS.md`; remaining work and
release gates are in `IMPLEMENTATION_BLUEPRINT.md`; runtime telemetry and retention
rules are in `TELEMETRY_CONTRACT.md`; evidence-specific limitations are in
`evidence/LIMITATIONS.md`.
