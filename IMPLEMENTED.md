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
| Worker 1 — Transport and schema | Protobuf, NATS, MQTT/Kafka transport behavior, Schema Registry, broker provisioning, acknowledgement and offset tests | Implementation is complete for the declared local scope. Offline and baseline live NATS/MQTT/Kafka/TLS/parity gates passed; only clean-final reruns and the broader restart/fault matrix remain execution work. |
| Worker 2 — Experimental evidence | Benchmark design, estimands, aggregation, statistical evidence, scale/latency results, manifests and release artifacts | The corrected development matrix and evidence integrity controls are implemented. Crash-safe provenance, dependence-aware inference, reference validation, sensitivity analysis, scale T2–T4, and clean final reproduction remain due. |
| Worker 3 — Telemetry, compliance and visualization | Runtime telemetry, durable outbox, Influx boundary, privacy-safe diagnostics, Grafana and dissertation-facing status views | Privacy-safe diagnostics, outbox tooling, and offline dashboard semantics are implemented. Source-message idempotency and terminal quarantine remain local implementation work; live Influx, Grafana, alert, credential, and retention gates remain unexecuted or decision-gated. |
| Coordinator | Shared scoring semantics, architecture decisions, Registry integration, final release and claim approval | Completed work and decisions are maintained here; remaining work and fail-closed gates are maintained in `IMPLEMENTATION_BLUEPRINT.md`. |

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
- NATS provisioning creates, reconciles, and verifies the file-backed `VITALS`
  and `VITALS_DLQ` streams with 24-hour maximum age and the file-backed
  `ALARMS` stream with seven-day maximum age. It also reconciles the `BRAIN`
  and `LOCAL_SCORER` pull consumers to explicit acknowledgement, 30-second
  `AckWait`, three maximum deliveries, and 500 maximum pending acknowledgements.
- Provisioning is non-interactive, repeat-safe, propagates CLI/authentication
  failures, validates the complete declared contracts, and works regardless of
  the caller's working directory.
- Rejected NATS messages use a structured Protobuf dead-letter envelope in the
  separate `VITALS_DLQ` stream. Stable rejection IDs suppress repeated storage
  of the same rejected payload within JetStream's duplicate window, and source
  acknowledgement follows confirmed DLQ publication.
- The live NATS test exercises the actual `_process` path and SQLite outbox,
  proves valid records receive durable Approach A/C output before source ACK,
  verifies malformed input reaches the current-run DLQ rather than retained
  history, and verifies local scorer publication into `ALARMS`.
- The local scorer waits for the `ALARMS` JetStream publish acknowledgement
  before acknowledging its triggering vital. Its NEWS2 state remains
  memory-only and no notification consumer or restart-continuity claim exists.
- MQTT uses `vitals/{patient_id}/{signal_type}` with a bounded `vitals/#`
  subscription and maps slash topics to the canonical dotted identity check.
  Both normal publishing and invalid-message DLQ publication wait for QoS 1
  PUBACK; invalid source input is manually acknowledged only after confirmed
  publication to `dlq/vitals/mqtt`. PUBACK proves broker receipt, not durable
  archive, and NATS/MQTT dual publication is not atomic.
- Kafka and Schema Registry are implemented as an isolated, opt-in,
  validation-only comparison path; they do not replace the NATS MVP or invoke
  Brain scoring, the SQLite outbox, InfluxDB, or alarm emission.
- Kafka runtime schema auto-registration is disabled, compatibility is
  `BACKWARD_TRANSITIVE`, and consumer offset commits occur only after the
  governed side effect or structured DLQ delivery.
- Kafka provisioning verifies fixed topic names, partition counts, replication,
  DLQ cleanup policy, and retention after every repeat-safe create. Unsupported
  topic environment overrides fail rather than bypass the provisioned contract.
- Kafka topic-description parsing now preserves comma-containing configuration
  values such as `cleanup.policy=compact,delete`. Regression coverage includes
  reordered, missing, and unexpected policies.
- Kafka polling distinguishes an idle poll from a consumed poison record. The
  parity runner requires confirmed delivery for its intentional poison payload,
  ignores unrelated concurrent records when accounting for its run, and
  reports valid acceptance separately from structured rejection.
- Published development ports are Registry-owned and bound to loopback.

### Transport infrastructure and security

- Compose images for NATS, Mosquitto, Kafka, and Schema Registry are pinned by
  digest. Insecure NATS uses a named persistent JetStream volume; all services
  have health checks and published ports remain loopback-only.
- `scripts/infrastructure_doctor.py` verifies required tools, the selected
  profile's actual Compose ports against the root Registry, selected services,
  image identities, and a secret-independent Compose configuration hash. It can
  inspect without contacting the Docker daemon for its client version, or
  explicitly start only the requested services and run live provisioning.
- The doctor refuses to start a profile when its governed port has an
  unidentified listener and refuses to overwrite an existing inventory unless
  explicitly authorized.
- `scripts/verify_secure_nats.py` generates disposable certificates and random
  credentials, uses an isolated Compose project, proves authenticated TLS
  access, rejects anonymous access, a wrong password, and an untrusted CA,
  rechecks authenticated health between negative probes, applies process
  timeouts, and removes its container and volume afterward.
- Secure verification does not establish production mutual TLS, cipher policy,
  multi-node durability, or hosted deployment. Those capabilities are outside
  the declared local research scope.

### Durable telemetry and acknowledgement

- Each accepted message commits its complete telemetry batch to a local SQLite
  WAL outbox before NATS or MQTT acknowledgement.
- A full outbox or local persistence failure leaves the broker message
  unacknowledged and restores tentative scoring state for redelivery.
- Content-derived event keys suppress exact derived-record duplicates. They do
  not yet guarantee source-message idempotency across threshold/config changes.
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

- `IMPLEMENTATION_BLUEPRINT.md` contains only remaining worker queues,
  acceptance gates, release order, and claim boundaries.
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
| `IMPLEMENTATION_BLUEPRINT.md` | Remaining ownership queues, sequencing, acceptance gates, and release plan |
| `TRUST_AND_ASSURANCE.md` | Evidence-backed assurance claims, control mapping, disclosure policy, and limitations |
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

- the isolated test suite reports **211 passed and 5 skipped** in the recorded
  sandboxed run;
- skipped cases are explicit live-infrastructure tests, not silent passes;
- Docker Compose configuration renders successfully;
- the Grafana dashboard and evidence manifest are valid JSON;
- every entry in `evidence/SHA256SUMS` verifies; and
- `git diff --check` reports no whitespace errors.

The evidence release gate uses a two-commit model: run records identify one
clean implementation commit, and final mode permits only `evidence/` changes in
its descendant attestation commit. Any intervening source or configuration
change fails closed.

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
- the current live parity run accepted 10/10 identical valid synthetic
  messages and rejected one intentional poison record through each NATS and
  Kafka path;
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

## Built capabilities that require additional runs

The implementation below already exists. The remaining work is execution,
approval, or final evidence generation; it must not be described as missing
software, and prior partial/development runs must not be promoted to final
evidence.

| Built capability | Evidence already available | Additional run or decision required |
| --- | --- | --- |
| Complete offline unit/integration suite | 211 passed; five broker-dependent tests skipped in the ordinary offline run | Repeat from the final clean commit in an exactly pinned environment; required live tests must run with `REQUIRE_*_INTEGRATION=true` |
| NATS stream/consumer provisioning and drift verification | Repeated successfully; live valid-outbox, current-run DLQ, and `ALARMS` paths passed | Repeat against the final candidate and add the approved restart/redelivery/max-delivery advisory fault matrix before broader V2 reliability claims |
| Disposable secure-NATS verifier | Authenticated TLS accepted; anonymous, wrong-password, and untrusted-CA probes rejected | Repeat from the final candidate; production mTLS/cipher policy remains excluded unless separately approved |
| MQTT QoS 1 publisher, bounded consumer, and invalid-input DLQ ordering | Live invalid-message test passed PUBACK-before-source-ACK | Repeat from the final candidate; broker restart/persistence and durable MQTT DLQ archival are not established |
| Kafka topic/schema provisioning, compatibility, commit ordering, and structured DLQ | Live schema round trip and valid/wrong-key/malformed/unknown-schema paths passed | Repeat from the final candidate and run approved broker/registry interruption, rebalance, redelivery, DLQ-failure, and persistence cases |
| NATS/Kafka validation-only parity harness | Current run accepted 10/10 valid messages and rejected one intentional poison record on each transport | Repeat under a frozen run configuration; it remains wire/schema acceptance and latency evidence, not scoring/storage/outcome parity |
| Deterministic A/B/C benchmark runner | Development artifacts contain 450 approach rows, 150 run records, and 86,400-second stable-baseline cells | Regenerate from the chosen clean commit after crash-safe provenance and the statistical contract are implemented and approved |
| Aggregate tables, figures, development manifest, and checksums | Current development checksum bundle verifies | Regenerate and attest the complete bundle from the clean evidence baseline; current manifest still identifies an older dirty run |
| Protocol benchmark | Throughput/latency artifact exists with restart-dependent dimensions explicitly skipped | Execute the restart, recovery, persistence, packet-loss, replay, and memory dimensions in an isolated authorized environment |
| Live latency tool | Publish-to-consume artifact exists; storage was explicitly skipped | Run publish-to-successful-storage latency with final Influx configuration and reconciliation |
| Scale-tier runner | T1 reached approximately 30 messages/second with no backlog; one T2 exploration exposed a producer bottleneck but is not accepted evidence | Freeze hardware/protocol and execute approved T2–T4 tiers or retain each as `unexecuted` |
| Distribution-validation tool | Offline validation and provenance tests exist | Run only with an approved licensed external source and governed transformation; keep source rows outside Git |
| Traceability and outbox-health auditors | Both aggregate, privacy-safe interfaces and offline tests exist | Execute on the final controlled outbox/Influx window and feed results into a combined reconciliation artifact |
| Grafana dashboards and paused synthetic alert | Dashboard semantics are offline-tested and A/B/C labels now match their data sources | Remove hardcoded bucket defaults, add genuine onset-to-detection data, validate live queries/rendering, then exercise an owner-approved synthetic-only destination |
| Evidence manifest final-mode guard | Dirty state, artifact shape, hashes, dependencies, and blockers are checked fail-closed | Resolve the two-stage implementation/evidence attestation workflow and run it from the final clean commits without overwriting inspectable development evidence |

The current `evidence/manifest.json` is therefore a development snapshot, not
the status of the latest source tree: it records commit `f3b6169` with a dirty
worktree and the superseded `python-dotenv==1.0.1` requirement. The active
tested environment and current requirement now agree on `python-dotenv==1.2.3`.
A fresh final environment and regenerated manifest are still required so its
commit, requirements hash, and dependency inventory describe the final source.

## Implementation still required before those runs can close

These are genuine code or analysis gaps rather than merely unexecuted tools:

- Worker 2: append-and-flush benchmark/run provenance with interruption
  recovery; a frozen ADEMP/STRESS protocol; dependence-aware paired inference,
  Monte Carlo error and non-detection handling; and predeclared sensitivity
  analysis.
- Worker 2: complete artifact-role/provenance indexing and a coherent
  two-commit final evidence/attestation workflow.
- Worker 3: stable source-message identity propagated through NATS/MQTT into
  outbox keys, including crash/redelivery tests across threshold changes.
- Worker 3: bounded terminal-failure classification, privacy-safe quarantine,
  and operational advisories instead of indefinite retry.
- Worker 3: one reconciliation result joining accepted broker inputs, outbox
  pending/delivered state, and stored Influx counts.
- Worker 3: governed dashboard/alert bucket configuration and a real
  onset-to-detection Grafana view.
- Coordinator: tracked-secret/ignored-path release scanning, final clean-clone
  reproduction, and final maintained-document/evidence reconciliation.

## Runs blocked on owner input or external resources

- Approve the independent reference source, licence/DUA, and transformation
  method before distribution/temporal validation.
- Approve hardware, resource limits, duration, repetitions, and targets before
  accepting T2–T4 capacity evidence.
- Approve retention and deletion policy separately for NATS, MQTT, Kafka,
  Influx, DLQ, logs, alarms, and aggregate evidence.
- Confirm historical Influx token rotation and provide final Influx access for
  storage latency, traceability, and reconciliation. Record no secret value.
- Approve a synthetic-only Grafana notification destination, recipients,
  activation window, evidence, and teardown before unpausing the alert.
- Keep suppression outside scope unless D11 authorizes a separate safety design.

Until these implementation, run, and owner gates close, the supported ceiling
is V0/V1 for the corresponding offline results plus the narrowly scoped V2
transport checks explicitly recorded above. No V3 realism or V4 clinical claim
is established.
