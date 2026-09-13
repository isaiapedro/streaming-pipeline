# Academic Streaming — Remaining Implementation Blueprint

## Purpose

This is the remaining-only roadmap for the synthetic medical streaming
experiment. Completed work is removed from the worker queues. Historical
results remain in `IMPLEMENTED.md`; this file contains only actionable
implementation, test, evidence, documentation, and release gates.

The Academic folder is an independent nested repository. Root Registry changes
remain governed and committed at the workspace root. Real patient data,
Personal-domain observations, credentials, certificates, broker volumes, and
row-level external reference data are prohibited from repository artifacts.

## Audited implementation boundary

- Agent 1 transport/schema implementation is complete at the development-tree
  level: NATS stream/consumer drift enforcement, repeat-safe live DLQ and
  durable handoff tests, disposable secure-TLS verification, fixed Kafka topic
  contracts, validation-only Kafka scope, valid/poison parity, file-backed
  `ALARMS`, bounded MQTT topics with PUBACK/DLQ ordering, infrastructure
  preflight, health checks, persistent NATS storage, and digest-pinned images.
- Kafka is a validation-only comparison. It does not run Brain scoring, commit
  to the SQLite outbox, write InfluxDB, emit alarms, or establish application,
  storage, alarm, or outcome parity.
- MQTT PUBACK proves local broker receipt, not durable DLQ archive. The local
  scorer's NEWS2 state is memory-only and no notification consumer exists.
- The existing evidence bundle is development evidence: it was generated from
  a dirty tree and the active `python-dotenv` version differs from its pin.
  Current development-bundle checksums verify, but they are not final evidence.
- Release is still blocked by Agent 2, Agent 3, and coordinator gates below.

## Parallel worker queues

### Agent 1 — Transport and schema

No implementation tasks remain in this queue. The clean-commit rerun and
cross-lane release checks are coordinator-owned because they depend on all
workers finishing. Future production TLS, multi-broker Kafka durability,
hosted Kafka, durable MQTT DLQ archival, and a notification consumer are
explicitly out of current scope, not unfinished Agent 1 work.

### Agent 2 — Experimental evidence

Work only in benchmark, aggregation, distribution, scale/latency, and
`evidence/` paths unless a shared semantic change is coordinated.

1. Fix the evidence manifest so every raw input, run log, aggregate, figure,
   caption, and provenance record has an explicit role and content hash.
2. Resolve the final-mode workflow so a clean implementation commit can
   generate inspectable evidence and a later clean evidence commit can be
   attested without contradictory dirty-tree requirements.
3. Recreate the exact pinned Python environment; eliminate the observed
   `python-dotenv` version drift and record tool identities.
4. Regenerate the full 450-row crossed A/B/C benchmark and 150-record run log
   from a clean identified commit, preserving 86,400-second stable cells.
5. Regenerate aggregates, figures, captions, manifest, and `SHA256SUMS`
   together; verify every checksum and prohibit manual CSV edits.
6. Add publish-to-successful-storage latency evidence or explicitly retain it
   as `unexecuted`; do not infer it from local outbox acknowledgement.
7. Extend protocol evidence beyond current throughput/latency coverage to the
   declared restart and recovery dimensions, with isolated broker control.
8. Execute scale tiers T2–T4 or mark each tier `unexecuted`; do not generalize
   T1 transport evidence into a 500-patient scoring/storage claim.
9. Run distribution validation only against an approved external source and
   retain non-sensitive source ID, license/DUA status, transformation version,
   direction `KL(P_synthetic || P_reference)`, and hashes—never source rows.
10. Produce the Agent 2/M5 acceptance report with exact commands, results,
    skipped gates, commit identity, limitations, and evidence-level ceiling.

### Agent 3 — Telemetry, recovery, and visualization

Work only in runtime persistence, telemetry, Grafana, alerting, and associated
tests unless a shared semantic change is coordinated.

1. Derive outbox idempotency from stable source-message identity and test
   redelivery, process crash, writer restart, and duplicate suppression.
2. Implement and verify terminal-failure quarantine/advisory handling plus
   privacy-safe operational outbox health reporting.
3. Reconcile accepted broker inputs, outbox state, and successful Influx writes
   before making any remote-storage completeness claim.
4. Obtain owner approval for Influx, broker, DLQ, alarm, and log retention;
   configure and test only the approved policies and deletion controls.
5. Record owner confirmation that the historically exposed Influx token was
   rotated; never record either credential value.
6. Correct Grafana comparison queries so Approach A from `patient_vitals` and
   B/C from `alarms` are compared honestly, and add genuine onset-to-detection
   timing rather than relabelling an alarm timeline.
7. Parameterize the Influx bucket in dashboard and alert provisioning, then run
   live datasource/query validation against final telemetry.
8. Exercise the paused synthetic alert end to end only after an approved
   destination is configured; retain sanitized evidence and document that the
   local `ALARMS` stream alone is not external notification delivery.
9. Update architecture, behavior, telemetry, Grafana, Agent 3/M6, and M7
   reports so persistence and alert claims match the verified implementation.

### Coordinator — Integration and release

Begin these steps only after both active worker queues are complete.

1. Review the combined diff for ownership, privacy, secrets, scientific
   semantics, and agreement between Registry, manifests, decisions, behavior
   contracts, README, operator guide, reports, and diagrams.
2. Run Registry validation, Compose rendering for every profile, shell syntax,
   Python compilation, dependency conformance, the complete offline suite, and
   `git diff --check` from the clean candidate.
3. Repeat required live NATS, secure-NATS, MQTT, Kafka, poison parity, outbox
   recovery, Influx reconciliation, and dashboard/alert gates. A skipped live
   gate is `unexecuted`, never passed.
4. Verify all evidence indexes and checksums, reproduce the bundle in another
   clean environment, and confirm every public claim stays at or below its
   demonstrated evidence level.
5. Commit and tag only after the nested repository is clean and every remaining
   blocker is either passed or explicitly excluded from the release claim.

## Integration order

Agent 2 and Agent 3 may proceed concurrently. They must not regenerate or
mutate the same evidence bundle during a run. Shared schema, scoring, retention,
or public-claim changes require a `DECISIONS.md` update before final evidence is
regenerated. The coordinator freezes implementation first, then evidence, then
performs the independent clean-environment reproduction.

## Release gate

Release is allowed only when all applicable statements are true:

- the nested repository is clean and identifies the implementation/evidence
  commits and tag;
- the installed environment exactly matches pinned requirements;
- offline and explicitly required live tests pass with no required skips;
- ports match Registry, selected Compose profiles are healthy, and image
  digests/configuration hashes are recorded without secret-derived material;
- acknowledgement and commit tests prove only the documented local boundaries;
- every raw input and generated output is indexed and hashed;
- benchmark, protocol, distribution, scale, storage, dashboard, and alert
  artifacts are reproducible or explicitly `unexecuted`;
- retention and credential-rotation decisions have owner confirmation;
- another clean environment reproduces the offline outputs; and
- public wording does not exceed the verified V0 unit, V1 simulation, or V2
  live technical evidence. V3 external and V4 clinical validation remain
  unavailable unless separately approved and executed.

If any gate fails, final-mode evidence generation must fail without overwriting
the last inspectable development manifest.
