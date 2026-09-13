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

The manifest inventory, two-commit attestation model, exact pinned environment,
and clean full-matrix regeneration gates are implemented. Remaining work:

1. Add publish-to-successful-storage latency evidence or explicitly retain it
   as `unexecuted`; do not infer it from local outbox acknowledgement.
2. Extend protocol evidence beyond current throughput/latency coverage to the
   declared restart and recovery dimensions, with isolated broker control.
3. Execute scale tiers T2–T4 or mark each tier `unexecuted`; do not generalize
   T1 transport evidence into a 500-patient scoring/storage claim.
4. Run distribution validation only against an approved external source and
   retain non-sensitive source ID, license/DUA status, transformation version,
   direction `KL(P_synthetic || P_reference)`, and hashes—never source rows.
5. Produce the Agent 2/M5 acceptance report with exact commands, results,
    skipped gates, commit identity, limitations, and evidence-level ceiling.

### Agent 3 — Telemetry, recovery, and visualization

Work only in runtime persistence, telemetry, Grafana, alerting, and associated
tests unless a shared semantic change is coordinated.

1. Replace exact-derived-record hashes with stable source-message identity
   propagated from NATS/MQTT. Test redelivery and process crash across threshold
   or configuration changes; writer restart for identical records already has
   offline coverage.
2. Define maximum-attempt/failure classification and implement privacy-safe
   terminal quarantine plus an advisory/operational signal and tests. The
   aggregate read-only outbox-health tool is already complete.
3. Produce one reconciliation result joining accepted broker input counts,
   outbox pending/delivered state, and stored Influx counts; execute it against
   final telemetry before making any remote-storage completeness claim.
4. Obtain owner approval for Influx, broker, DLQ, alarm, and log retention;
   configure and test only the approved policies and deletion controls.
5. Record owner confirmation that the historically exposed Influx token was
   rotated; never record either credential value.
6. Add a genuine Grafana onset-to-detection view based on an explicit onset
   source or annotation. The existing static evidence timeline does not satisfy
   this live-dashboard gate.
7. Replace the hardcoded `vitals` bucket in dashboard and alert queries with
   governed configuration, strengthen tests for both, and run live
   datasource/query/render validation against final telemetry.
8. Exercise the paused synthetic alert end to end only after an approved
   destination is configured; retain sanitized evidence and document that the
   local `ALARMS` stream alone is not external notification delivery.
9. After live gates, update only the maintained authorities and evidence
   artifacts with actual outcomes; the repository has intentionally
   consolidated and removed milestone reports.

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
