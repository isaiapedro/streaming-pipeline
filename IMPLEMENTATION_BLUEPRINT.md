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
- The complete offline suite passes with 185 tests and three optional live
  infrastructure skips.
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
