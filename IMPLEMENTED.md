# Implemented Work

## Purpose and scope

This document is the authoritative summary of completed implementation and
verification work in the Academic synthetic patient-vitals project. Decisions,
unresolved gaps, owners, and claim limitations are maintained separately in
`DECISIONS.md`. Remaining task ownership and sequencing are maintained in
`IMPLEMENTATION_BLUEPRINT.md`.

The software supports controlled synthetic research claims only. It does not
establish clinical effectiveness, diagnostic accuracy, production readiness,
hospital-scale capacity, or suitability for real patient data.

## Delivery summary

| Lane | Completed delivery |
| --- | --- |
| Worker 1 — Transport and schema | Canonical Protobuf ingress, NATS/MQTT/Kafka validation, NATS stream and consumer contracts, Kafka Schema Registry compatibility, acknowledgement/commit ordering, structured dead-letter paths, repeat-safe provisioning, and live transport tests |
| Worker 2 — Experimental evidence | Deterministic scenario benchmark, crossed seed design, A/B/C aggregation, evidence figures, run provenance, artifact inventory, checksums, exact dependency capture, clean two-commit attestation, and portable raw evidence |
| Worker 3 — Telemetry and visualization | Atomic SQLite WAL outbox, retry and recovery behavior, privacy-safe diagnostics, traceability/outbox auditors, Influx handoff boundary, Grafana semantics, and evidence-status visualizations |
| Coordinator — Governance and release gates | Registry port allocation, infrastructure preflight, pinned containers, TLS negative tests, full offline/live gate execution, documentation consolidation, clean-clone reproduction, and final evidence attestation |

## Synthetic generation and scoring

- Five parametric signal generators use independently seeded random state for
  reproducible experiments and retain an unseeded live/demo mode.
- Six deterministic scenarios declare onset, duration, deterioration, and
  stability behavior.
- Signal and noise seeds are independent. The noise model supports packet
  loss, spikes, dropout windows, timestamp jitter, and clock drift.
- Approach A performs deterministic per-signal threshold scoring.
- Approaches B and C implement the scoped NEWS2 calculation over respiratory
  rate, SpO2, systolic pressure, heart rate, and temperature.
- Supplemental oxygen and consciousness scores are explicitly fixed at zero.
- SpO2 Scale 1 is the default; Scale 2 requires explicit scenario/profile
  metadata and is never inferred solely from a COPD label.
- Composite scoring requires a complete, fresh five-signal window.
- NEWS2 escalation implements total-score thresholds and the individual
  parameter score-of-three rule.
- Threshold hot reload validates a complete replacement before atomically
  changing the active snapshot and threshold version.
- Detection requires a newly opened alarm episode at or after ground-truth
  onset. Existing alarms at onset are not credited as detections.
- Alarm burden is measured through debounced episodes and time in alarm rather
  than raw counts of scoring calls.

## Benchmark and scientific evidence

- The main benchmark crosses six scenarios, five signal seeds, five noise
  seeds, and three approaches, producing 450 approach rows and 150 run records.
- Stable-baseline cells simulate 86,400 seconds.
- A/B/C receive identical observations within each paired seed cell.
- Missing and inapplicable metrics remain unavailable rather than becoming
  artificial zeroes.
- Probability intervals use Wilson intervals; other current descriptive means
  use the documented deterministic bootstrap implementation.
- Distribution divergence is explicitly labelled
  `KL(P_synthetic || P_reference)`.
- The aggregation pipeline validates matrix completeness before producing 18
  scenario/approach rows and five dissertation figures.
- The raw benchmark, run log, aggregates, figures, captions, and supporting
  evidence are content-addressed and indexed by role, media type, byte size,
  generator, tracking status, and SHA-256 digest.
- Final mode validates exact dependency versions, clean run provenance,
  artifact shape, source hashes, Git tracking, commit ancestry, and the
  evidence-only change boundary before writing an attestation.
- The two-commit workflow separates the measured implementation commit from
  the reviewed evidence commit. Intervening changes outside `evidence/` and
  the governed root `benchmark_results.csv` fail closed.
- The small synthetic raw benchmark is versioned so tests and evidence checks
  work from a fresh clone without hidden local inputs.

## Transport and schema

- NATS and MQTT consume the canonical Protobuf vital-sign schema and validate
  structural content plus payload/topic identity before changing state.
- NATS provisions file-backed `VITALS`, `VITALS_DLQ`, and `ALARMS` streams.
- `BRAIN` and `LOCAL_SCORER` consumers use explicit acknowledgement, a
  30-second `AckWait`, three maximum deliveries, and 500 maximum pending ACKs.
- Provisioning is repeat-safe, non-interactive, working-directory independent,
  and verifies the complete live contract after creating or repairing it.
- Invalid NATS records are acknowledged only after confirmed publication of a
  structured Protobuf dead-letter envelope.
- The local scorer waits for the `ALARMS` JetStream publish acknowledgement
  before acknowledging its triggering vital.
- MQTT uses the bounded `vitals/#` hierarchy, QoS 1 publishing, manual source
  acknowledgement, and confirmed DLQ PUBACK ordering.
- Kafka is an isolated validation-only comparison using fixed topics,
  canonical Protobuf framing, patient-key validation, manual commits, and a
  structured DLQ.
- Schema Registry is provisioned with `BACKWARD_TRANSITIVE` compatibility;
  compatible schemas are accepted and breaking schemas are rejected.
- Kafka polling distinguishes idle polls from consumed poison records, and
  commits only after the governed handler or confirmed DLQ side effect.
- Topic parsing supports comma-containing policies such as
  `cleanup.policy=compact,delete` and rejects contract drift.

## Durable telemetry and recovery

- Every accepted NATS or MQTT message commits its complete derived telemetry
  batch to a private SQLite WAL outbox before broker acknowledgement.
- SQLite uses `synchronous=FULL`, integrity checking, private filesystem modes,
  bounded capacity, and symbolic-link path rejection.
- Persistence or capacity failure leaves the source unacknowledged and rolls
  back tentative scoring state for redelivery.
- Influx delivery is asynchronous. Failed writes remain locally durable with
  attempt counts, next-attempt timestamps, and bounded exponential delay.
- Retry state survives process restart.
- Content-derived identifiers suppress exact duplicate derived records.
- Acknowledgement is consistently documented as local durable handoff, not
  confirmed remote Influx storage.

## Privacy, security, and auditability

- Only synthetic inputs are allowed in brokers, DLQs, storage, dashboards,
  logs, and repository evidence.
- Runtime logs exclude patient identifiers, raw values, subjects, endpoints,
  credentials, and arbitrary remote exception text.
- Stored retry errors retain only a bounded exception class and optional
  numeric HTTP status; legacy arbitrary error text is scrubbed on open.
- AST and behavioral tests enforce the logging boundary.
- Traceability audits expose aggregate tag-presence counts and percentages,
  not tag values or rows.
- Outbox audits open SQLite read-only and report aggregate integrity, retry,
  age, capacity, and permission status without paths or payloads.
- Broker ports bind to Registry-owned loopback allocations.
- NATS, Mosquitto, Kafka, and Schema Registry images are pinned by digest and
  have health checks.
- The infrastructure doctor checks required tools, Compose configuration,
  governed ports, selected service health, image identity, and provisioning.
- Secure-NATS verification uses disposable credentials and certificates,
  proves authenticated trusted TLS, rejects anonymous/wrong-password/
  untrusted-CA access, and removes its isolated containers and volumes.

## Dashboards and research communication

- Grafana NEWS2 panels are explicitly scoped to Approaches B/C.
- A/B/C alarm views combine Approach A vital telemetry with B/C alarm
  telemetry so labels match their actual sources.
- Dashboard tests cover datasource identity, filters, TLS verification,
  environment placeholders, and the paused alert default.
- The representative trajectory displays all five scoped signals, B/C NEWS2,
  ground-truth onset, qualifying post-onset detection, and non-detection.
- Architecture, evidence, scale, protocol, and traceability status figures
  visually distinguish executed, partial, unexecuted, and future work.
- Figure captions state the evidence and claim boundary.

## Infrastructure and reproducibility

- Academic ports `19092` and `18081` are allocated in the root Registry for
  Kafka and Schema Registry; all published development ports are loopback-only.
- Compose profiles render successfully and support isolated NATS, secure NATS,
  MQTT, Kafka, Schema Registry, Influx, and Grafana workflows.
- Direct Python dependencies are exactly pinned and resolve without conflicts.
- Scripts are project-root aware and avoid caller-working-directory
  assumptions.
- Evidence generators are non-interactive and deterministic for fixed inputs
  and seeds.
- `OPERATIONS_AND_REPRODUCIBILITY.md` provides setup, execution, maintenance,
  recovery, live-gate, and evidence-freeze commands.
- `DISSERTATION_EVIDENCE_ONBOARDING.md` explains benchmark fields, figures,
  interpretation, and acceptable dissertation use.
- `TRUST_AND_ASSURANCE.md` maps claims to controls, verification, and limits.

## Verification completed

- Isolated pinned-environment suite: **211 passed, 5 explicitly skipped**.
- Fresh-clone pinned-environment suite: **211 passed, 5 explicitly skipped**.
- The skipped tests are opt-in live-infrastructure tests, not silent passes.
- Required live NATS tests passed, including durable outbox handoff, current-run
  DLQ handling, and `ALARMS` publication.
- Required live MQTT and Kafka integration tests passed.
- NATS provisioning and drift repair passed repeatedly.
- Schema compatibility accepted the compatible candidate and rejected the
  breaking candidate.
- Secure NATS accepted authenticated trusted TLS and rejected anonymous access,
  wrong credentials, and an untrusted CA.
- Validation-only NATS/Kafka parity accepted the governed valid inputs and
  rejected the intentional poison record on both paths.
- The full 450-row/150-run benchmark completed from a clean implementation
  commit with every run record marked complete and clean.
- Every file in `evidence/SHA256SUMS` verifies from a fresh clone.
- The tracked raw benchmark hash matches the final manifest.
- Final evidence mode passed with exact dependencies, no evidence-package
  blockers, and all publishable artifacts tracked.

## Frozen evidence identity

| Role | Commit |
| --- | --- |
| Measured implementation | `70ff39ffe0725f4d89d663c5bcbef6d3c2beaefb` |
| Reviewed evidence base | `044f8eb8050ce44452fc22dea3dd3b89005d10a5` |
| Portable final attestation | `edadcc6c8a1cad23311b8c6fdb804dcac94b4c58` |

The manifest's `eligible_for_final_release=true` applies to the frozen offline
evidence package. It does not close the broader project, operational,
external-data, retention, or clinical claim gates recorded in `DECISIONS.md`
and `IMPLEMENTATION_BLUEPRINT.md`.

## Maintained authorities

| Authority | Purpose |
| --- | --- |
| `README.md` | Project overview and entry points |
| `BEHAVIOR.md` | Mandatory privacy and runtime behavior |
| `IMPLEMENTED.md` | Completed implementation and verification |
| `DECISIONS.md` | Accepted decisions, open owner decisions, and gap register |
| `IMPLEMENTATION_BLUEPRINT.md` | Remaining tasks, owners, ordering, and release gates |
| `OPERATIONS_AND_REPRODUCIBILITY.md` | Setup, operation, maintenance, and reproduction |
| `TELEMETRY_CONTRACT.md` | Telemetry, persistence, retention, and alert boundaries |
| `TRUST_AND_ASSURANCE.md` | Assurance claims, controls, and limitations |
| `DISSERTATION_EVIDENCE_ONBOARDING.md` | Evidence and visualization interpretation |
| `evidence/manifest.json` | Machine-readable provenance and artifact index |
