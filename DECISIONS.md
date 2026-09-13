# Architectural Decisions

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
retryable across restart, content-derived keys make redelivery idempotent, and
outbox capacity failure applies broker backpressure. This supports a local
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
