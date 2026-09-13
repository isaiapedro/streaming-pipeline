# Academic Streaming Implementation Blueprint

## Purpose and authority

This blueprint governs implementation and release of the synthetic medical
streaming experiment. It separates work into the same three lanes used for the
initial implementation, defines scientific and software evidence boundaries,
and names the gates that must pass before dissertation or demo claims are
released. `OPERATIONS_AND_REPRODUCIBILITY.md` is the executable operator guide;
`DECISIONS.md` records standards that must remain stable across lanes.

The Academic folder is an independent nested Git repository. Implementation
commits belong here. Root Registry changes, including host-port ownership, are
committed at the workspace root under its governance contract.

## Current baseline

- NATS/Protobuf validation, DLQ isolation, deterministic NEWS2 A/B/C scoring,
  versioned telemetry, durable local outbox, Kafka/Schema Registry comparison,
  Grafana provisioning, and evidence tooling are implemented.
- The complete isolated-environment suite passes with 207 tests and five
  explicit live-infrastructure skips in the recorded sandboxed run.
- Compose renders successfully and the workspace Registry validates 42
  components.
- The development benchmark contains the required 450 approach rows, 150 run
  records, and 86,400-second stable-baseline cells.
- Development evidence is not release evidence: it was produced from a dirty
  tree and the active environment differs from two pinned dependencies.
- Final live NATS/Kafka reruns, clean-commit evidence reproduction, credential
  rotation confirmation, hosted storage reconciliation, and final dashboard
  validation remain release gates.

## Scope and claim boundary

This is a synthetic software experiment. It can support claims about the
declared generator, algorithms, transport, persistence boundary, and measured
environment. It cannot support claims of clinical effectiveness, diagnostic
accuracy, production availability, hospital-scale readiness, or protection of
real patient data.

Evidence levels are cumulative:

| Level | Meaning | Required evidence |
| --- | --- | --- |
| V0 | Unit correctness | Deterministic boundary, missing-data, error, and property tests |
| V1 | Simulation verification | Frozen scenarios/seeds/estimands, paired runs, uncertainty, provenance |
| V2 | Live technical validation | Broker, persistence, restart, recovery, and fault evidence |
| V3 | Independent external validation | Approved independent reference inputs and governed transformations |
| V4 | Clinical validation | Separately approved clinical study; outside this repository's current scope |

Every public claim must name its maximum evidence level and must not infer a
higher level from a lower one.

## Ownership and active work

| Worker | Primary ownership | Active findings and closure evidence |
| --- | --- | --- |
| 1 — Transport and schema | `schema/`, `nats/`, `kafka_path/`, Compose, broker provisioning, transport tests | Govern ports; enforce schema compatibility, explicit acknowledgements, consumer drift checks, and commit ordering; produce bounded offline and live transport results |
| 2 — Experimental evidence | Benchmark, aggregation, distribution, scale/latency scripts, `evidence/` | Enforce 450-row design, 24-hour stable baseline, raw/run hashes, KL direction, missing-value semantics, dependency identity, and dirty-tree finalization failure |
| 3 — Telemetry and persistence | Runtime consumers, Influx writer, threshold snapshots, Grafana, telemetry tests | Commit before acknowledgement to a durable idempotent outbox; retry/replay safely; preserve provenance; validate dashboards and storage boundaries |
| Coordinator | Shared scoring semantics, decisions, README, blueprint, integration/release | Keep NEWS2 and claim boundaries consistent, audit worker results, run combined gates, and publish only verified status |

Workers do not edit another lane's owned files without coordination. Shared
schema or semantic changes require a decision record before final evidence is
regenerated.

## Updated three-worker backlog assignment

This allocation includes the defects discovered during the dissertation
evidence reruns. The coordinator owns shared scoring semantics, Registry
changes, clean commits/tags, and final claim approval.

| Worker | Assigned remaining work | External/dependency gate |
| --- | --- | --- |
| **1 — Transport and schema** | Rerun final NATS provisioning/configuration and secure rejection tests; rerun Kafka compatibility, DLQ, and commit-order tests; produce NATS/Kafka parity; execute restart/disconnect/redelivery, persistence, packet-loss, and DLQ-deduplication tests; audit Protobuf artifacts, loopback ports, and broker configuration; update the bounded transport report. Kafka TLS, multi-broker durability, and hosted deployment stay decision-gated. | Clean integrated commit, exact environment, Registry-owned ports, and operator-provided test certificates/credentials. Supplies broker/config hashes and live results to Worker 2. |
| **2 — Experimental evidence** | Make per-cell provenance crash-safe; freeze an ADEMP/STRESS protocol; account for dependence in the crossed 5×5 design; add paired A−B/A−C/B−C effects and principled non-detection estimands; add sensitivity analysis; complete approved-reference validation, latency evidence assembly, scale diagnostics/T1–T4, experimental figures, artifact lineage, and clean-clone reproduction. | Frozen coordinator scoring contract, Worker 1 live transport outputs, Worker 3 storage/alarm confirmation interfaces, approved reference data, and suitable scale hardware. |
| **3 — Telemetry, compliance, and visualization** | Enforce privacy-safe runtime and persisted-error diagnostics; test logging/secret boundaries; audit stored-tag coverage and outbox health without exporting values; reconcile retention layers; correct Grafana A/B/C semantics; validate dashboards/alerts offline; generate implemented-versus-planned, traceability, and complete alarm-timeline visuals; expose live storage/Grafana/alert/credential gates in the manifest. Suppression remains outside scope pending a new safety decision. | Offline work is locally executable. Live Influx reconciliation, bucket retention, token rotation, rendered Grafana screenshots, and notification receipt require operator credentials or approval. Supplies aggregate audits only to Worker 2. |

Cross-lane work is closed only after the consuming lane reruns its evidence
against the producing lane's final contract. Worker 1 owns transport behavior,
Worker 2 owns experimental inference and evidence artifacts, and Worker 3 owns
runtime telemetry, persistence, privacy controls, and operational views.

## Prior-run misses and resulting tasks

| Prior miss | Impact | Prevention owner and status |
| --- | --- | --- |
| Ten coupled signal/noise seed pairs | Could not separate the two variation sources | Worker 2: crossed 5×5 design implemented; dependence-aware inference and variance attribution remain due |
| Run booleans labelled TPR/FPR | Overstated clinical/event-level accuracy | Worker 2: renamed to detection-run rate and false-alarm-run probability |
| Above-threshold scoring calls counted as alarms | Measured computation frequency instead of operational burden | Worker 2: debounced episodes and time-in-alarm implemented; clinician notification counts remain unmeasured |
| First post-onset observation counted even when alarm was already active | Produced misleading near-zero detection latency | Worker 2: only a newly opened post-onset episode counts; plots show detected runs/25 |
| `stable-baseline`/`stable_baseline` ID mismatch | First intended 24-hour run remained 600 seconds | Worker 2: corrected and rerun at 86,400 seconds; old output is superseded |
| Benchmark was regenerated before concurrent NEWS2 API changes were reconciled | Intermediate results could mix SpO₂-scale and escalation semantics | Coordinator/Worker 2: scoring reconciled and complete development matrix rerun |
| Kafka topic descriptions were parsed by splitting every comma | A valid `cleanup.policy=compact,delete` value was split and failed the integrated suite | Worker 1: key-aware parsing and reordered/missing/unexpected-policy regression coverage implemented; final live provisioning rerun remains due |
| Flat normal intervals and mean-only bars | Invalid probability bounds and hidden pairing/non-detection | Worker 2: Wilson/descriptive bootstrap outputs and paired visualization implemented; crossed-design intervals remain due |
| Run logs written only after the full matrix | A process crash can erase completed/failed-cell provenance | Worker 2: append-and-flush per-cell records plus interruption recovery tests remain P0 |
| Manifest initially described 180 rows and did not bind the raw CSV or reject dirty release state | Stale evidence could appear releasable | Worker 2: manifest v3 validates/hashes inputs and final mode fails closed |
| Runtime logs exposed subject/identifier plus raw value; remote exception text was retained in the outbox | Privacy/credential material could enter operational records | Worker 3: logging was sanitized; persisted errors now retain only exception class/status; regression tests added |
| Traceability figure was hardcoded and no stored-record auditor existed | Implemented tags could be mistaken for verified live coverage | Worker 3: aggregate live/export auditor and manifest-derived status implemented; live audit remains unexecuted |
| Grafana “A/B/C” views queried only composite alarm records | Approach A was absent while panel titles implied inclusion | Worker 3: NEWS2 is explicitly B/C-only; alarm state/observation panels union A telemetry; semantic tests added |
| Representative timeline omitted systolic BP and explicit first A/B/C episodes | Figure did not explain all scoring inputs or detection definition | Worker 3: six-axis timeline and first-new-episode markers implemented |
| Retention proposals were not compared with active broker policies | One-day DLQ policies could be confused with proposed seven-day review retention | Worker 3: storage-layer matrix documented; owner decision remains required before changing retention |

## Remaining tasks and release blockers

P0 before any final dissertation run:

1. Create a reviewed clean commit, recreate the exact pinned environment, and
   rerun tests and all final evidence. The current manifest blocks release
   because the run log and repository are dirty and installed `pytest` and
   `python-dotenv` differ from their pins.
2. Worker 2 must make provenance crash-safe and freeze the full ADEMP/STRESS
   analysis, including crossed-design dependence, paired effects, Monte Carlo
   error, and non-detection handling.
3. Worker 1 must rerun required live NATS/Kafka and parity gates against that
   same clean commit.

P1 evidence still unexecuted:

- approved-reference distribution and temporal validation;
- alarm-delivery and confirmed-storage latency with reconciliation;
- NATS/MQTT/Kafka restart, persistence, packet-loss, replay, and memory tests;
- T2–T4 on approved hardware;
- live stored-tag coverage and outbox health from the final run;
- Grafana provisioning/render screenshots and an approved synthetic alert
  destination;
- owner confirmation of Influx token rotation and retention settings.

P2 hardening still due:

- formal sensitivity analyses for clear hold, thresholds, signal cadence,
  stale-window behavior, profiles, random-walk drift, and SpO₂ scale;
- a repository-owned `doctor/test/run/verify` experiment CLI with immutable
  run directories and locking;
- a tracked-secret/ignored-path release scanner and clean-clone reproduction;
- suppression design and evaluation only after a separate safety decision.

### Worker 3 completion recorded in this update

The locally executable Worker 3 remainder is implemented: safe persisted error
codes, aggregate traceability and outbox-health auditors, runtime/static privacy
tests, corrected Grafana comparison semantics, stronger offline dashboard and
alert checks, a manifest-derived compliance status view, an architecture-status
figure, and a complete five-input/first-episode timeline. These are V0/offline
controls until the corresponding live gates above are executed.

## Scientific contract

### NEWS2 scope

- The prototype measures respiratory rate, SpO2, systolic blood pressure,
  heart rate, and temperature.
- Supplemental oxygen and consciousness subscores are fixed at zero and must
  be stated in every interpretation.
- Scale 1 is the default SpO2 scale. Scale 2 is selected only through explicit
  `news2_spo2_scale=2` metadata representing a documented prescription for
  confirmed hypercapnic respiratory failure. COPD alone never selects Scale 2.
- Composite scoring occurs only when all five required readings exist and are
  fresh within the declared window. Missing or stale windows have no score.
- A total score of 7 or more is critical. A total of 5–6, or any individual
  parameter scoring 3, is warning/escalation.

Golden boundary, invalid scale, incomplete-window, stale-window, and
single-parameter escalation tests are mandatory after scoring changes.

### Experiment design

- Six declared scenarios are crossed with five signal seeds and five noise
  seeds and evaluated with approaches A/B/C: 450 approach rows total.
- Stable-baseline duration is 86,400 simulated seconds for each cell.
- Detection is credited only when a new alarm episode opens at or after the
  configured onset. An already-open alarm at onset is not a detection.
- Alarm burden is episode based with the declared clear-hold interval.
- Missing or inapplicable values remain missing; they are never coerced to
  zero.
- Probability intervals use the documented Wilson method. Other estimates use
  the documented bootstrap method and report distribution summaries.
- Distribution divergence is labelled `KL(P_synthetic || P_reference)` with
  its smoothing and transformation metadata.

## Transport, persistence, and security contract

### Ports and external infrastructure

Host ports are owned globally in `registry/PORTS.md`. Academic currently owns
1883, 4222, 8222, 18081, and 19092. Published services bind to loopback. A
fixed-port change updates Compose, the root registry, and the Academic decision
record together. Operators inspect existing listeners and never stop unrelated
services as an undocumented workaround.

External folders are inputs only when explicitly supplied. Raw clinical or
reference rows, Personal-domain observations, secrets, certificates, broker
volumes, `.runtime/`, and virtual environments remain outside Git. Publishable
evidence contains aggregate synthetic results and non-sensitive provenance.

### Delivery semantics

| Path | Success required before acknowledgement/commit |
| --- | --- |
| Valid NATS/MQTT input | Atomic local SQLite WAL outbox commit of all derived records |
| Invalid NATS input | Confirmed structured DLQ publication |
| Valid Kafka input | Successful handler completion/durable declared side effect |
| Invalid Kafka input | Confirmed Kafka DLQ delivery |

NATS consumers verify `AckExplicit`, `AckWait`, `MaxDeliver`, and
`MaxAckPending`. Kafka disables automatic commits and offset storage. Stable
content keys make outbox redelivery idempotent. Capacity failure applies
backpressure. Influx failures stay queued with bounded retry across restart.
Acknowledgement proves local durable handoff, not successful remote Influx
storage.

Credentials are injected by the operator and never printed, committed, or
stored in evidence. The ignored Influx token identified during review must be
rotated by its owner and only the confirmation date/status recorded.

## Auditability and indexing

Traceability follows:

`claim -> requirement/decision -> code -> test -> run -> aggregate -> figure`.

- The Registry indexes ownership and dependency boundaries.
- `manifest.yaml` declares the Academic component boundary.
- `evidence/manifest.json` indexes input/output roles, hashes, commands,
  versions, run status, dependency conformance, and release blockers.
- `evidence/SHA256SUMS` protects publishable bundle files but does not replace
  the manifest's raw-input hashes.
- Influx tags are bounded query dimensions: signal, approach, scenario,
  transport, and schema/pipeline/threshold versions. Values, hashes, run IDs,
  and other high-cardinality data remain fields unless a measured query need
  justifies indexing.
- Logs record counts, versions, duration, severity, and synthetic scenario
  context without combining a patient identifier and raw vital value.

## Milestone sequence

| Milestone | Exit condition |
| --- | --- |
| M3 — NATS closure | Clean baseline; offline and required live NATS tests; secure-profile rejection evidence |
| M4 — Transport comparison | Isolated Kafka schema, compatibility, DLQ, commit-order, and live parity evidence |
| M5 — Experimental evidence | Clean reproducible A/B/C, protocol, distribution, live-latency, and scale artifacts |
| M6 — Telemetry/compliance | Provenance tags, durable outbox/recovery, retention and credential controls |
| M7 — Visualization/release | Validated dashboards, alert exercise, final reports, clean tag, reproducibility audit |

M4–M6 may develop in parallel after the shared message/scoring contract is
frozen. M7 consumes their verified outputs.

## Release procedure

1. Review all worker diffs and privacy/secret boundaries.
2. Run Registry validation, Compose rendering, shell syntax, dependency checks,
   the full offline suite, and Git whitespace checks.
3. Commit the reviewed implementation in the nested Academic repository.
4. Recreate the exact pinned environment from `requirements.txt` and repeat
   the offline gate.
5. Start only the required loopback infrastructure; provision and verify NATS
   consumers, Kafka topics, and Schema Registry compatibility.
6. Run required live NATS and Kafka tests plus the parity harness. Stop the
   temporary infrastructure explicitly.
7. From the clean implementation commit, regenerate the 450-row benchmark and
   its run log, aggregate tables, figures, development manifest, and checksums.
8. Review generated evidence, commit it, then run final manifest mode from the
   clean evidence commit. Commit the final attestation/checksums.
9. Execute approved live storage latency, scale T1–T4, distribution validation,
   and Grafana alert/dashboard gates. Unavailable gates remain `unexecuted`.
10. Record credential rotation confirmation and complete a clean-clone
    reproduction before signing/tagging the release.

Exact commands, environment variables, backup/recovery procedures, and
troubleshooting are in `OPERATIONS_AND_REPRODUCIBILITY.md`.

## Final release gate

Release is allowed only when all applicable items are true:

- the nested repository is clean and its commit/tag is identified;
- the installed environment exactly matches pinned requirements;
- offline tests pass and required live NATS/Kafka tests pass;
- ports match Registry and Compose has no collision;
- no secret/privacy scan finds credentials or prohibited source rows;
- NEWS2 scale, escalation, and incomplete-window contracts pass;
- acknowledgement/offset tests prove the declared durable side effect precedes
  acknowledgement;
- raw inputs and every evidence output are indexed and hashed;
- benchmark, scale, protocol, distribution, storage-latency, and dashboard
  artifacts have reproducible manifests or are explicitly `unexecuted`;
- Influx records contain agreed provenance and remote storage claims are backed
  by reconciliation evidence;
- README, decisions, reports, diagrams, and behavior contracts describe the
  same implementation;
- another clean environment reproduces the offline outputs without an
  undocumented workaround;
- every public claim stays at or below its verified V0–V4 level;
- credential rotation is owner-confirmed without recording any secret value.

If any item fails, final-mode evidence generation must fail without overwriting
the last inspectable development manifest.
