# Decisions and Open Gaps

This document is the authority for accepted scientific and architectural
decisions, decisions still requiring an accountable owner, and unresolved
implementation or execution gaps. Completed work belongs in `IMPLEMENTED.md`;
task sequencing belongs in `IMPLEMENTATION_BLUEPRINT.md`.

## 2026-09-13 — Documentation uses durable authorities, not milestone reports

The maintained documentation set is limited to the workspace behavior
contract, README, accepted decisions, consolidated implementation/decision
status, remaining-work blueprint, operator guide, telemetry contract, trust and
assurance case, dissertation evidence onboarding, and the governed evidence
documentation.

Milestone, worker, and point-in-time release reports are removed after their
unique findings are incorporated into those authorities. Obsolete notebooks,
diagrams, placeholders, and duplicated generated outputs are not retained as
parallel sources of truth. Implementation source, tests, schemas, runtime
configuration, manifests, and evidence artifacts remain even after a feature
is implemented because they are required to reproduce and verify the claims.

## 2026-09-13 — Broker acknowledgement follows local durable handoff

For the NATS and MQTT runtime paths, the acknowledgement boundary is the
atomic commit of every derived telemetry record to the private SQLite WAL
outbox. Remote InfluxDB delivery is asynchronous. Failed deliveries remain
retryable across restart, hashed source receipts make redelivery independent
of derived configuration, and outbox capacity failure applies broker
backpressure. Terminal failures move to private quarantine. This supports a local
durability claim only; successful remote storage requires separate measurement
and reconciliation evidence.

## 2026-09-13 — NEWS2 scale selection and escalation are explicit

The synthetic physiological condition and the NEWS2 SpO2 scale are separate
inputs. Scale 1 is the default. Scale 2 may be selected only by the explicit
`news2_spo2_scale` profile or scenario field representing a documented
prescription for confirmed hypercapnic respiratory failure; `copd_flag` never
selects the NEWS2 scale. The COPD scenario uses Scale 2 only because its
synthetic definition declares that additional prescription assumption.

A composite assessment is emitted only when all five scoped NEWS2 parameters
are present and no older than the declared window. An incomplete or stale
window has no score, rather than a score accompanied by a false completeness
flag. Escalation is `critical` for a total score of 7 or more and `warning` for
a total of 5 or more or any individual parameter scoring 3. This prototype
still fixes supplemental oxygen and consciousness subscores at zero, so its
claims remain limited to the declared synthetic comparison and are not claims
of clinical fitness.

## 2026-09-13 — Dissertation evidence uses alarm episodes and a trade-off claim

The primary dissertation experiment is the local deterministic A/B/C scoring
comparison. It uses a fully crossed 5×5 signal/noise-seed design, paired across
approaches, and a 24-hour stable-baseline run per cell. Run-level detection and
false-alarm occurrence are named explicitly rather than reported as clinical
TPR/FPR. Operational burden is derived from alarm-state episodes that close
after ten continuously clear seconds. A positive event is detected only when a
new episode opens at or after its configured onset; an already-active alarm is
not credited as detection.

The main claim is therefore a detection-speed versus nuisance-burden trade-off
under synthetic conditions. Cloud suppression, clinical effectiveness,
publish-to-storage latency, and 500-patient scale are excluded until separately
implemented and measured. Kafka remains an isolated supplemental transport
implementation, not the execution environment for the primary benchmark.

Seed-level provenance may be committed only when it contains synthetic
configuration, timing, status, and non-identifying runtime context. Raw vital
values, hostnames, credentials, clinical rows, and Personal-domain
interpretation remain prohibited from the objective evidence bundle.

## 2026-09-06 — NATS validates the canonical Protobuf contract at ingress

The NATS and MQTT prototype paths use `schema/proto/vitals.proto` as their
canonical binary contract. Each consumer structurally validates a decoded
`VitalSign` before changing EWS state or emitting a record. The patient and
signal encoded in the message must match the input subject. Rejected NATS
payloads are preserved as `DeadLetterEnvelope` messages on `dlq.vitals.nats`
in a separate `VITALS_DLQ` stream, keeping rejection traffic outside the vital
input namespace.

Kafka Schema Registry compatibility enforcement is isolated from the NATS
prototype and governed by the Milestone 4 decision below.

## 2026-09-13 — Rejected NATS identity follows the source stream sequence

JetStream de-duplication for a rejected NATS input is bound to the stable
source-stream sequence, subject, and payload. Redelivery of the same source
message therefore retains one rejection identity, while two distinct source
publications with identical bytes remain distinct. When a broker source
identity is unavailable, non-NATS callers retain the content-derived fallback.

This identity controls DLQ publication de-duplication only. It does not imply
exactly-once processing, durable MQTT rejection storage, or end-to-end
idempotency across the telemetry pipeline.

## 2026-09-13 — Kafka is an isolated validation-only comparison, not the MVP transport

Milestone 4 implements a local, opt-in Kafka and Confluent Schema Registry path
for transport comparison. It does not replace or wrap the NATS MVP, and it does
not claim production or 500-patient deployment readiness.

The shipped Kafka consumer's handler prints a validated record. It does not
run Brain scoring, commit to the SQLite outbox, write InfluxDB, or emit alarms.
Its parity harness therefore measures wire/schema acceptance, rejection, and
local delivery latency only; it is not application, storage, or outcome parity.

The comparison uses `vitals.protobuf.v1` and `vitals.dlq.protobuf.v1`. Values
use the canonical Protobuf messages with Schema Registry framing; patient ID is
the record key. Both value subjects enforce `BACKWARD_TRANSITIVE`
compatibility. Registration and evolution checks are provisioning operations,
while runtime producer and consumer processes fail rather than auto-register a
schema.

Consumers use `read_committed` with automatic commits and offset storage
disabled. A valid message is committed only after its handler succeeds. A
poison message is committed only after its structured DLQ record is delivered.
Handler failures and transient Schema Registry failures are retriable and are
therefore neither committed nor converted into poison-message DLQ records.

The local Compose profile binds its plaintext ports to Registry-allocated
loopback ports `19092` (Kafka) and `18081` (Schema Registry). Encryption,
authentication, multi-broker durability, transactions, hosted operation, and
the 500-patient scale claim remain outside this comparison and require a later
deployment decision.

## 2026-09-13 — MQTT and local alarms have explicit, limited broker boundaries

MQTT mirrors canonical payloads on `vitals/{patient_id}/{signal_type}` and the
consumer subscribes only to `vitals/#`. The slash topic is mapped to the shared
dotted identity validator. Valid QoS 1 input is manually acknowledged after the
atomic SQLite outbox handoff. Invalid input is acknowledged only after a QoS 1
publish to `dlq/vitals/mqtt` receives PUBACK. PUBACK proves broker receipt, not
durable archive or later consumption. NATS and MQTT dual-publish operations are
independent and are not atomic.

The local scorer publishes priority events to the file-backed `ALARMS` stream
on `alarms.>` with a seven-day maximum age. A JetStream publish acknowledgement
precedes acknowledgement of the triggering vital. Its NEWS2 window is
memory-only, no notification consumer is implemented, and no external alert
delivery or restart-continuity claim is made.

## Resolved release decisions

### 2026-09-13 — Runtime deduplication and terminal delivery are explicit states

Accepted NATS messages use stream sequence identity when available; MQTT uses
the validated topic plus canonical wire payload identity. Only a SHA-256 digest
is retained in `source_receipts`. The receipt is committed atomically with all
derived records and remains after delivery, making redelivery independent of
later threshold/configuration changes. MQTT byte-identical publications are
therefore the same logical source event under this prototype contract.

Influx HTTP 408, 409, 425, 429, and 5xx responses are retriable. Other 4xx
responses are terminal; failures without a status remain retriable. Retriable
records move to terminal quarantine after `INFLUX_OUTBOX_MAX_ATTEMPTS` (default
10). Quarantine preserves the synthetic payload for controlled diagnosis in
the private SQLite file, while logs and auditors expose only safe codes and
aggregate counts. D6 still governs receipt/quarantine retention and deletion.

The cumulative SQLite counters and source receipts are the local accounting
authority. An Influx completeness claim additionally requires a matching
logical-record query and a `complete` reconciliation result; an ambiguous
remote success surfaces as a mismatch rather than being hidden.

### 2026-09-13 — Offline evidence uses a two-commit attestation

The measured implementation is frozen before evidence generation. A reviewed
descendant commit may change only `evidence/` and the governed root
`benchmark_results.csv`. Final mode verifies ancestry, changed paths, exact
dependencies, run cleanliness, artifact tracking, hashes, and checksums before
writing the attestation. The accepted chain is:

- measured implementation: `70ff39ffe0725f4d89d663c5bcbef6d3c2beaefb`;
- reviewed evidence base: `044f8eb8050ce44452fc22dea3dd3b89005d10a5`;
- portable attestation: `edadcc6c8a1cad23311b8c6fdb804dcac94b4c58`.

The attestation releases the bounded offline evidence package only. It is not
approval for broader operational, external-validity, production, or clinical
claims.

The superseding crash-recoverable evidence chain is:

- measured implementation: `d71793c954ebc043a47a245b2f0ac21589fa6a2a`;
- reviewed evidence base: `d71f7d5a718171321c8ac756ca74e891c1f270bc`;
- portable attestation: `aa98b248726d30ae59d567b4e91ad2a61e6a4fe6`.

It reproduced the 450 raw metric rows and derived figures while upgrading the
run provenance to schema v2. The earlier chain remains historical evidence at
its own commits; it is no longer the current bounded package identity.

## Decisions requiring an owner

| ID | Owner | Decision required | Blocks |
| --- | --- | --- | --- |
| D2 | Dissertation author and methodology reviewer | Freeze dependence-aware paired estimands, Monte Carlo error, interval method, and treatment of non-detection | Inferential A/B/C comparison language |
| D3 | Author and data-governance owner | Approve an independent reference source, licence/DUA, allowed transformations, and retained provenance | External distribution or realism claims |
| D4 | Infrastructure owner | Approve the restart, interruption, replay, persistence, and fault-injection matrix; explicitly include or exclude production TLS and multi-broker Kafka | Broader V2 reliability claims |
| D5 | Author and infrastructure owner | Freeze hardware, limits, duration, repetitions, and T2–T4 targets | Capacity claims beyond T1 |
| D6 | Privacy and retention owner | Approve retention and verified deletion separately for streams, topics, Influx data, DLQs, alarms, logs, and aggregate evidence | Hosted retention/compliance claims |
| D7 | Service and credential owner | Select the final Influx organization/bucket/access boundary and confirm historical token rotation without recording either token | Live storage and credential-safety claims |
| D8 | Telemetry owner and operator | Freeze the reconciliation window, accounting rule, and acceptable discrepancy across broker input, outbox, writes, and stored points | Confirmed-storage and storage-latency claims |
| D9 | Notification and privacy owner | Approve a synthetic-only destination, recipients, activation window, retained evidence, and teardown | Unpausing alerts or claiming delivery |
| D10 | Author and methodology reviewer | Predeclare sensitivity ranges for clear hold, thresholds, cadence, freshness, profiles, drift, noise, and SpO2 scale | Robustness claims |
| D11 | Safety and architecture owner | Keep cloud-to-local suppression out of scope or authorize a separate safety design | Any suppression implementation or claim |
| D12 | Author and supervisor | Approve the evidence level and limitation wording for each headline result | Dissertation submission or public release |
| D13 | MQTT service owner | Select the stable Brain client identity, singleton/multi-instance session ownership, and bounded in-memory queue capacity | MQTT crash/restart redelivery implementation and evidence |

### 2026-09-13 — Benchmark recovery uses one durable per-cell journal

The benchmark appends one privacy-safe journal record after every completed or
failed seed cell, flushes it, and calls `fsync` before starting the next cell.
Each record binds the complete protocol fingerprint, attempt number, safe
failure class, provenance, and three A/B/C result rows. `--resume` is allowed
only when the current invocation matches that fingerprint. It discards only a
torn final append, preserves complete failures, skips completed cells, retries
failed cells, and atomically rebuilds the public CSV and run log. The previous
published outputs remain untouched until every cell completes.

This supports recovery of the evidence-generation process. It does not imply
broker, storage, operating-system, or hardware fault tolerance.

## Open implementation gaps

- The MQTT Brain consumer still uses a generated client identity, a clean
  broker session, and an unbounded application queue. Stable restart redelivery
  requires a governed client identity, persistent session, bounded queue, and
  a live crash-before-ACK test.
- The analysis does not yet implement the frozen ADEMP/STRESS protocol,
  crossed-seed dependence-aware paired inference, Monte Carlo error reporting,
  non-detection sensitivity treatment, or predeclared sensitivity analysis.
- Live broker evidence has not yet shown source-receipt de-duplication across a
  crash-before-ACK and threshold/configuration change for both NATS and MQTT.
- The reconciliation tool exists, but no final outbox-lifetime result has yet
  been joined to the matching Influx logical-record count.
- Grafana bucket parameterization is implemented; a genuine live
  onset-to-detection view still lacks stable run, absolute-onset, and newly
  opened episode telemetry.

## Open execution and evidence gaps

- Restart, interruption, replay, persistence, packet-loss, DLQ-deduplication,
  maximum-delivery, and memory behavior lack one frozen final fault matrix.
- Publish-to-successful-storage latency remains unexecuted.
- T2–T4 runs remain unexecuted on approved, recorded hardware.
- Independent external-reference validation remains unexecuted pending source
  approval.
- Final live traceability and broker/outbox/Influx reconciliation remain
  unexecuted.
- Grafana live query/render validation and approved notification delivery
  remain unexecuted.
- Retention/deletion verification and credential-rotation confirmation remain
  owner-blocked.
- The frozen `evidence/RESULTS.md` and `evidence/LIMITATIONS.md` still contain
  pre-attestation wording about a dirty development run. Reconcile those
  narratives with the final manifest during the next governed evidence
  regeneration; do not edit frozen evidence without refreshing its attestation.

## Claim boundary while gaps remain

The current evidence supports V0 unit correctness, V1 synthetic simulation,
and only the narrowly executed V2 local transport/security checks. It does not
support V3 independent realism or V4 clinical validation. Do not describe the
system as clinically safe, production ready, exactly once, end-to-end durable,
retention compliant, or proven for 500 patients.
