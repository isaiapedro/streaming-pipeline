# Implemented Work and Decisions Required

## Purpose

This document summarizes the implementation and audit work completed during the
dissertation-evidence review. It also identifies the decisions that still need
an accountable owner before final evidence can be generated or broader claims
can be made.

The current system is a synthetic software experiment. The completed work
supports claims about the declared generator, scoring algorithms, transports,
local persistence boundary, and measured environment. It does not establish
clinical effectiveness, diagnostic accuracy, production availability,
hospital-scale readiness, or suitability for real patient data.

## Work allocation

| Lane | Ownership | Current result |
| --- | --- | --- |
| Worker 1 — Transport and schema | Protobuf, NATS, MQTT/Kafka transport behavior, Schema Registry, broker provisioning, acknowledgement and offset tests | Offline transport contracts and regressions are implemented. Final live broker, restart, fault, persistence, and parity evidence remains due. |
| Worker 2 — Experimental evidence | Benchmark design, estimands, aggregation, statistical evidence, scale/latency results, manifests and release artifacts | The corrected development matrix and evidence integrity controls are implemented. Crash-safe provenance, dependence-aware inference, reference validation, sensitivity analysis, scale T2–T4, and clean final reproduction remain due. |
| Worker 3 — Telemetry, compliance and visualization | Runtime telemetry, durable outbox, Influx boundary, privacy-safe diagnostics, Grafana and dissertation-facing status views | All locally executable tasks from this review are implemented and unit-tested. Live Influx, rendered Grafana, alert-delivery, credential, and retention gates remain unexecuted or decision-gated. |
| Coordinator | Shared scoring semantics, architecture decisions, Registry integration, final release and claim approval | Worker boundaries, evidence levels, prior misses, release order, and fail-closed gates are documented in `IMPLEMENTATION_BLUEPRINT.md`. |

## Implemented system capabilities

### Synthetic generation and runtime controls

- Five parametric synthetic signal generators use independently seeded random
  state for reproducible experiments while retaining an unseeded live/demo
  mode.
- Six deterministic scenarios provide declared onset times and controlled
  deterioration or stability trajectories.
- Signal and noise variation are separated. The noise layer supports packet
  loss, spikes, dropout windows, and timestamp jitter.
- Cross-signal correlation and scenario effects are applied through reusable
  simulation components shared by the live and offline paths.
- Threshold configuration can be hot-reloaded through the governed NATS KV
  entry. A complete replacement is validated before the runtime snapshot and
  version are changed together.

### Scoring and experiment semantics

- Deterministic Approach A threshold scoring and Approach B/C NEWS2 scoring are
  implemented.
- NEWS2 uses the five measurements available to the prototype: respiratory
  rate, SpO2, systolic blood pressure, heart rate, and temperature.
- Supplemental oxygen and consciousness subscores remain explicitly fixed at
  zero.
- SpO2 Scale 1 is the default. Scale 2 is selected only through explicit
  scenario/profile metadata; COPD alone does not select it.
- Composite scoring requires a complete, fresh five-signal window. Missing or
  stale inputs produce no score.
- NEWS2 escalation includes both total-score thresholds and the
  single-parameter score-of-three rule.
- Alarm burden is expressed as debounced alarm episodes and time in alarm,
  rather than the number of scoring calls above a threshold.
- Detection is credited only when a new alarm episode opens at or after the
  declared event onset. An episode already active at onset is not counted as a
  detection.
- Run-level outcomes are named detection-run rate and false-alarm-run
  probability; they are not presented as clinical TPR/FPR.

### Benchmark and evidence integrity

- The development benchmark uses six scenarios crossed with five signal seeds,
  five noise seeds, and three approaches: 450 approach rows and 150 run
  records.
- Stable-baseline cells run for 86,400 simulated seconds.
- Signal and noise seeds are independently represented rather than coupled into
  ten seed pairs.
- Missing and inapplicable results remain missing instead of being coerced to
  zero.
- Probability intervals use the documented Wilson method; other development
  summaries use the documented bootstrap implementation.
- Distribution divergence is labelled in the implemented direction,
  `KL(P_synthetic || P_reference)`.
- The evidence manifest validates the expected design, binds source artifacts
  with hashes, records dependency and repository state, and rejects dirty
  final-mode evidence.
- Evidence status is generated from the manifest rather than being manually
  hardcoded.
- Checksums cover the dissertation-facing tables, reports, and figures.
- Repository-owned tools exist for offline scoring benchmarks, protocol
  comparison, live latency, distribution validation, scale tiers, aggregation,
  evidence status, manifests, and checksums.

### Transport and schema

- NATS and MQTT accept the canonical Protobuf vital-sign schema and perform
  structural validation before changing scoring state.
- The encoded patient and signal must match the source subject.
- Rejected NATS messages use a structured Protobuf dead-letter envelope and a
  separate DLQ stream.
- Kafka and Schema Registry are implemented as an isolated, opt-in comparison
  path; they do not replace the NATS MVP.
- Kafka runtime schema auto-registration is disabled, compatibility is
  `BACKWARD_TRANSITIVE`, and consumer offset commits occur only after the
  governed side effect or structured DLQ delivery.
- Kafka topic-description parsing now preserves comma-containing configuration
  values such as `cleanup.policy=compact,delete`. Regression coverage includes
  reordered, missing, and unexpected policies.
- Published development ports are Registry-owned and bound to loopback.

### Durable telemetry and acknowledgement

- Each accepted message commits its complete telemetry batch to a local SQLite
  WAL outbox before NATS or MQTT acknowledgement.
- A full outbox or local persistence failure leaves the broker message
  unacknowledged and restores tentative scoring state for redelivery.
- Content-derived event keys make local redelivery idempotent.
- Influx delivery is asynchronous and retried with bounded exponential backoff.
- Acknowledgement therefore means local durable handoff, not confirmed remote
  Influx storage.
- The outbox directory and database are assigned private filesystem
  permissions, symbolic-link database paths are rejected, and database
  integrity is checked when opened.
- Stored retry diagnostics contain only a bounded exception class and optional
  numeric HTTP status. Earlier arbitrary exception text is scrubbed when the
  outbox is opened.
- Startup logging no longer exposes the configured outbox filesystem path.

### Privacy, compliance and audit tooling

- Runtime rejection and failure logs were changed to exclude message subjects,
  patient identifiers, raw vital values, endpoints, and remote exception text.
- Runtime and AST-based regression tests enforce the current log boundary.
- `scripts/audit_traceability.py` audits required Influx tag presence from an
  approved CSV export or an explicitly authorized live query.
- Traceability audit output contains aggregate counts and percentages only; it
  excludes tag values, identifiers, timestamps, and measurements.
- The traceability audit distinguishes `passed`, `incomplete`, and
  `no_records`, and can fail closed with `--require-complete`.
- `scripts/audit_outbox.py` opens the SQLite database read-only and reports
  aggregate integrity, retry, age, size, due-record, and permissions status
  without exporting paths, payloads, identifiers, or error text.
- Neither audit is treated as live evidence until run against the final
  controlled environment and reconciled with broker inputs.

### Grafana and visualization

- Grafana's NEWS2 panel is explicitly labelled as Approaches B/C only.
- Alarm timing and alarming-observation panels union Approach A vital telemetry
  with Approach B/C alarm telemetry so A/B/C comparison labels match their
  queries.
- Dashboard tests enforce time, patient, scenario, and approach filters,
  datasource identity, environment placeholders, TLS verification, and the
  paused synthetic alert default.
- The representative trajectory now shows all five measured inputs, NEWS2
  scores, ground-truth onset, the first new post-onset episode, and explicit
  non-detection where no qualifying episode exists.
- The architecture-status figure distinguishes implemented core components,
  the supplemental Kafka path, unverified live components, and future
  suppression.
- Evidence and traceability status figures display missing live evidence as
  `unexecuted`, not as a zero result.
- Figure captions explain the evidence boundary and prevent unverified diagram
  elements from appearing implemented.

### Documentation and governance

- `IMPLEMENTATION_BLUEPRINT.md` contains the current three-worker allocation,
  prior-run misses, P0/P1/P2 remaining work, release order, and claim boundary.
- `TELEMETRY_CONTRACT.md` documents telemetry meanings, the durable
  acknowledgement boundary, privacy-safe audit commands, credential status,
  alert activation, and retention by storage layer.
- `DECISIONS.md` records the settled acknowledgement, NEWS2, experimental,
  NATS schema, and Kafka-scope decisions.
- The release and milestone reports distinguish offline verification from live
  technical evidence. Their non-duplicated conclusions have now been
  consolidated into this document and the superseded reports removed.

## Required documentation and system files

The documentation set has been reduced to the following authorities:

| File or directory | Required role |
| --- | --- |
| `README.md` | System overview, scope, architecture, and entry points |
| `BEHAVIOR.md` | Workspace/domain behavioral contract required by workspace governance |
| `DECISIONS.md` | Accepted architectural and scientific decisions |
| `IMPLEMENTED.md` | Consolidated implementation status, historical results, pending decisions, and unfinished work |
| `IMPLEMENTATION_BLUEPRINT.md` | Active ownership, sequencing, acceptance gates, and remaining plan |
| `OPERATIONS_AND_REPRODUCIBILITY.md` | Canonical setup, operation, testing, maintenance, and final evidence procedure |
| `TELEMETRY_CONTRACT.md` | Runtime telemetry, acknowledgement, privacy, retention, credential, and alert contract |
| `evidence/README.md` | Evidence-bundle reproduction entry point |
| `evidence/RESULTS.md` | Generated dissertation-facing result summaries |
| `evidence/LIMITATIONS.md` | Evidence and claim limitations |
| `evidence/FIGURE_CAPTIONS.md` | Governed interpretation of generated figures |
| `manifest.yaml` | Local workspace manifest required by Registry governance |
| `docker-compose.yml`, `requirements.txt`, `pytest.ini` | Runtime, dependency, and test configuration |

Implementation source, schemas, tests, scripts, provisioned dashboards, and
machine-readable evidence remain required even when their features are
implemented: they are the reproducible basis for verification and dissertation
claims. Generated raw benchmark input also remains locally available because
the current tests and manifest bind it.

## Verification completed

At the time this document was last verified:

- the isolated test suite reports **207 passed and 5 skipped** in the recorded
  sandboxed run;
- skipped cases are explicit live-infrastructure tests, not silent passes;
- Docker Compose configuration renders successfully;
- the Grafana dashboard and evidence manifest are valid JSON;
- every entry in `evidence/SHA256SUMS` verifies; and
- `git diff --check` reports no whitespace errors.

The existing evidence is development evidence because the repository is not yet
at a reviewed clean final commit and the active environment has recorded
dependency drift. It must not be relabelled as final dissertation evidence.

### Live release-gate and exploratory checks

The following checks were executed during the integrated release audit. They
must be repeated only when a later source commit changes their path:

- required live NATS integration passed, including the declared ALARMS stream;
- required authenticated TLS NATS integration passed, while anonymous access,
  wrong credentials, and an untrusted CA were rejected;
- NATS provisioning was repeated and repaired pre-existing consumer drift;
- required live Kafka integration passed the valid commit and structured
  wrong-key, malformed-frame, and unknown-schema rejection paths;
- Kafka topic and schema provisioning was idempotent, enforced
  `BACKWARD_TRANSITIVE`, accepted the compatible candidate, and rejected the
  breaking candidate;
- one live parity run accepted 20/20 identical synthetic messages through each
  NATS and Kafka path;
- required MQTT integration passed its QoS 1 and
  confirmed-DLQ-before-source-ack path;
- a fresh isolated environment resolved every direct pin and passed `pip
  check`; the original pytest pin was corrected because it conflicted with the
  declared lower bound of `pytest-asyncio==1.4.0`;
- an early local T1 scale exploration reached its 30 messages/second target
  after correcting a pull-timeout measurement artifact; and
- an early local T2 exploration reached approximately 5,246 of a requested
  12,000 messages/second and indicated a single-process producer bottleneck.
  This T2 result is exploratory and is not accepted scale evidence because the
  current hardware and protocol were not frozen.

## Decisions already made

These decisions are settled in `DECISIONS.md` and should not be reopened
implicitly:

1. Broker acknowledgement follows the local SQLite WAL commit, not remote
   Influx confirmation.
2. NEWS2 scale selection, completeness, freshness, and escalation behavior are
   explicit.
3. The main dissertation claim is a synthetic detection-speed versus
   nuisance-burden trade-off based on alarm episodes.
4. The NATS/MQTT path uses the canonical Protobuf contract at ingress.
5. Kafka is an isolated research comparison, not the MVP transport or evidence
   of production readiness.
6. Cloud suppression, clinical effectiveness, 500-patient readiness, and real
   patient-data use are outside the currently supported claim.

## Decisions still required

Each item below needs an explicit owner and a recorded outcome. Until then, the
associated evidence or feature remains blocked.

### D1 — Final evidence baseline

**Owner:** repository owner/coordinator
**Decision:** Select and review the exact clean Academic commit, environment,
dependency lock, run identifier, and evidence directory that will constitute
the final dissertation baseline.
**Required before:** any artifact is labelled final or release-ready.
**Recommended default:** one immutable clean commit, a freshly recreated pinned
environment, and a complete rerun of tests, benchmarks, audits, manifests,
figures, and checksums.

### D2 — Statistical analysis contract

**Owner:** dissertation author/methodology reviewer
**Decision:** Approve the dependence-aware analysis for the crossed 5×5
signal/noise design, the paired A−B/A−C/B−C estimands, Monte Carlo error
reporting, confidence interval method, and treatment of non-detection.
**Required before:** inferential comparison language is used in the
dissertation.
**Recommended default:** preserve pairing, account for both seed dimensions,
report non-detection separately, and avoid assigning an artificial zero or
maximum latency.

### D3 — Independent reference source

**Owner:** dissertation author/data-governance owner
**Decision:** Approve the reference dataset or published source, licence,
allowed transformations, provenance fields, and temporal/distribution
comparison protocol.
**Required before:** V3 distribution or realism claims.
**Recommended default:** use a reproducible, lawfully licensed, non-Personal
source and store only governed aggregate evidence in this repository.

### D4 — Live transport test scope

**Owner:** infrastructure owner/Worker 1
**Decision:** Choose the controlled environment, credentials/certificates,
broker versions, fault-injection limits, and required NATS/MQTT/Kafka parity
matrix. Decide whether TLS and multi-broker Kafka are required for the
dissertation or explicitly excluded.
**Required before:** V2 transport reliability claims.
**Recommended default:** execute the declared local live matrix and keep TLS,
hosted deployment, and multi-broker durability excluded unless the dissertation
specifically depends on them.

### D5 — Scale target and hardware

**Owner:** dissertation author/infrastructure owner
**Decision:** Approve the hardware, resource limits, duration, repetitions, and
T2–T4 patient-load targets. Decide whether a 500-patient claim is necessary.
**Required before:** performance or capacity claims beyond T1.
**Recommended default:** report only measured tiers and retain
`500-patient readiness unverified` unless the approved T4 run is completed.

### D6 — Retention by storage layer

**Owner:** privacy/data-retention owner
**Decision:** Approve retention separately for NATS streams, Kafka topics,
Influx raw vitals, Influx alarms, DLQ payloads, logs, and aggregate evidence.
Resolve the active one-day broker DLQ policy versus the proposed seven-day
triage period, and define deletion verification and access responsibility.
**Required before:** hosted/live retention is configured or claimed compliant.
**Recommended default:** choose the shortest period that supports the declared
experiment; do not lengthen DLQ retention silently because rejected payloads
may contain sensitive input.

### D7 — Influx environment and credential rotation

**Owner:** service/credential owner
**Decision:** Select the final Influx organisation, bucket, retention policy,
and access boundary, and confirm that the historically exposed token has been
rotated. Record only the confirmation date and responsible role, never either
token.
**Required before:** final live storage, reconciliation, or credential-safety
claims.

### D8 — Live storage reconciliation

**Owner:** Worker 3/operator
**Decision:** Approve the final audit window and reconciliation rule between
accepted broker inputs, pending outbox records, successful writes, and stored
Influx points. Define the acceptable discrepancy, if any.
**Required before:** publish-to-storage latency or confirmed-storage claims.
**Recommended default:** require complete tag coverage and exact accounting for
accepted inputs, durable pending records, and confirmed points; report failures
or omissions rather than imputing them.

### D9 — Grafana alert destination

**Owner:** notification/privacy owner
**Decision:** Choose an approved synthetic-only notification destination,
authorized recipients, activation window, evidence to retain, and teardown
procedure.
**Required before:** unpausing the provisioned alert or claiming notification
delivery.
**Recommended default:** keep the rule paused until a non-Personal test
destination is approved; retain only a non-sensitive timestamp, rule version,
and delivery outcome.

### D10 — Sensitivity-analysis bounds

**Owner:** dissertation author/methodology reviewer
**Decision:** Freeze the parameter ranges and priority order for clear hold,
thresholds, signal cadence, stale-window length, profiles, random-walk drift,
noise, and SpO2 scale.
**Required before:** robustness claims.
**Recommended default:** predeclare ranges before execution and clearly
separate confirmatory settings from exploratory analysis.

### D11 — Cloud suppression

**Owner:** safety/architecture owner
**Decision:** Either keep cloud feedback suppression outside scope or authorize
a separate safety design covering authority, stale feedback, ordering,
conflicts, failure behavior, auditability, and evaluation.
**Required before:** implementing any cloud-to-local suppression path or
describing it as an implemented capability.
**Recommended default:** retain it as future work for this dissertation phase.

### D12 — Final claim and publication wording

**Owner:** dissertation author/supervisor
**Decision:** Approve the maximum evidence level for every headline result and
the exact limitations accompanying it.
**Required before:** dissertation submission, demonstration, or public
release.
**Recommended default:** limit current offline results to V0/V1 as applicable,
add V2 only after the corresponding live gates pass, and make no V3/V4 claim
without independent validation or a separately approved clinical study.

## Work still not completed

The following are implementation or execution tasks, not evidence that can be
inferred from the completed offline suite:

- crash-safe append-and-flush provenance with interruption recovery;
- frozen ADEMP/STRESS protocol and dependence-aware paired inference;
- approved-reference validation and temporal comparison;
- final live NATS/Kafka provisioning, parity, restart, redelivery, persistence,
  packet-loss, replay, DLQ-deduplication, and memory evidence;
- publish-to-confirmed-storage and alarm-delivery latency;
- scale tiers T2–T4 on approved hardware;
- sensitivity analyses using predeclared ranges;
- live traceability and outbox reconciliation for the final run;
- rendered Grafana screenshots and synthetic alert receipt;
- credential-rotation and retention confirmation;
- tracked-secret/ignored-path scanning and clean-clone reproduction; and
- suppression, unless D11 authorizes a separate safety phase.

These items remain open even though their interfaces, status representation, or
offline tests may already exist.
