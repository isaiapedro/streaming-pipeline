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
- The bounded offline evidence bundle has a clean, portable final attestation.
  This closes the offline package gate only; the operational, external-data,
  scale, storage, retention, and notification gates below remain open.
- The bounded offline package is released. Broader operational and public-claim
  expansion remains governed by the Agent 1–3 and coordinator gates below.

## Parallel worker queues

### Agent 1 — Transport and schema

The core transport/schema paths and their offline regression gates are
implemented. Remaining work:

1. After owner decision D13, give the MQTT Brain consumer a governed stable
   client identity, persistent broker session, and bounded application queue.
   Add a live crash-before-source-ACK test that proves QoS 1 redelivery after
   process restart without claiming durable DLQ archival.
2. Bind the implemented transport-neutral NATS/MQTT fault harness to an
   owner-approved live adapter, then execute restart, disconnect, offline
   durable recovery, replay, maximum-delivery, persistence, and DLQ
   de-duplication cases. The governed runner fails closed without `--live` and
   an approved adapter; keep each unavailable case explicitly `unexecuted`.
3. Bind the implemented Kafka restart/consumer-restart/group-rebalance and
   Schema Registry fault APIs to a governed live writer. No Kafka fault CLI or
   retained result is currently claimed.

The schema descriptor drift gate, source-sequence-aware NATS DLQ identity,
complete NATS consumer delivery/replay drift enforcement, MQTT DLQ provenance,
Kafka idle/poison distinction, delivery failure gates, and provisioning
regressions are complete. Future production TLS, multi-broker Kafka
durability, hosted Kafka, durable MQTT DLQ archival, and a notification
consumer remain explicitly out of scope.

### Agent 2 — Experimental evidence

Work only in benchmark, aggregation, distribution, scale/latency, and
`evidence/` paths unless a shared semantic change is coordinated.

The manifest inventory, two-commit attestation model, exact pinned environment,
clean full-matrix regeneration, and crash-recoverable per-cell provenance
journal are complete. The bounded offline package does not need another clean
rerun. Remaining work and claim extensions are:

1. Execute the implemented paired clean/noise/dropout scoring matrix from a
   clean frozen commit and retain `evidence/noise_scoring_experiment.csv`.
   Implementation tests do not change its current `unexecuted` evidence state.
2. Implement only the owner-approved dependence-aware paired estimands, Monte
   Carlo error, non-detection treatment, and sensitivity analysis. The current
   final descriptive benchmark remains valid within its stated scope.
3. Add publish-to-successful-storage latency evidence or explicitly retain it
   as `unexecuted`; do not infer it from local outbox acknowledgement.
4. Extend protocol evidence beyond current throughput/latency coverage to the
   declared restart and recovery dimensions, with isolated broker control.
5. Execute scale tiers T2–T4 or retain each tier as `unexecuted`. T1 is retired
   from latency/stress evidence and must not appear in active claims or gates.
6. Run distribution validation only against an approved external source and
   retain non-sensitive source ID, license/DUA status, transformation version,
   direction `KL(P_synthetic || P_reference)`, and hashes—never source rows.
7. Produce the Agent 2/M5 acceptance report with exact commands, results,
   skipped gates, commit identity, limitations, and evidence-level ceiling.

#### Original-scope T2 transport execution plan

T2 is the original L2 transport experiment, not a full-pipeline capacity test.
It drives **24 synthetic patients × five signals × 100 Hz = 12,000 messages/s**
through the producer, NATS JetStream, and an isolated lightweight pull
consumer.  The runner uses its own `scale.>` stream.  Brain/NEWS2 scoring,
SQLite outbox persistence, InfluxDB, Grafana, external notification, and
Kafka are excluded.  A separate NATS-versus-MQTT protocol comparison may use
the same workload, but is separate evidence and must not be merged with this
NATS scale result.

**D5 run-freeze gate.** Before an evidence run, the author and infrastructure
owner record the approved host class and CPU/RAM/disk limits, operating system,
container/image and Python versions, NATS configuration, implementation
commit, `--duration`, repetition count, and `--pull-timeout`.  The plan does
not prescribe a rate that the host must attain: the target is 12,000 messages/s
and the experiment identifies the measured ceiling.  Configuration changes
after a run begin create a new run rather than being tuned into its result.

**Execution.**

1. From a clean nested-repository candidate, validate the selected Compose
   profile and provision the governed NATS streams.  Capture the selected
   non-secret configuration and machine context before publishing messages.
2. Run `scripts/run_scale_tier.py --tier T2` with the D5-frozen duration and
   pull timeout, writing distinct CSV and JSON result paths for every
   repetition.  Begin a final series in a new result directory; never edit or
   truncate a prior result CSV.
3. For each run, retain requested, attempted, published, received, decoded,
   acknowledged, failed, and peak-backlog counts when the runner provides
   them, plus achieved rate and P50/P99 publish-to-fetch latency.  Record the
   first saturated component using measured process/broker observations, not
   inference from the target rate alone.
4. Treat P99 above one second as the observed transport ceiling.  If the
   target is not sustained, report the achieved rate, backlog, and bottleneck;
   this is a valid T2 finding, not a reason to extrapolate or silently tune the
   run.
5. Publish only aggregate, synthetic, non-identifying evidence with the exact
   command, commit, environment summary, status, and limitation that this
   result covers producer-to-NATS-to-pull-consumer transport only.  Mark a
   run that cannot execute on the approved hardware as `unexecuted` with its
   reason.

**Acceptance statement.** A completed T2 result establishes the measured
transport behavior of the governed workload on its recorded environment.  It
does not establish Brain/NEWS2 throughput, local or remote persistence,
InfluxDB capacity, dashboard freshness, notification delivery, reliability
under faults, clinical suitability, or 25-patient full-system readiness.

### Agent 3 — Telemetry, recovery, and visualization

Work only in runtime persistence, telemetry, Grafana, alerting, and associated
tests unless a shared semantic change is coordinated.

Stable hashed source receipts for NATS and MQTT, duplicate-state rollback,
maximum-attempt and HTTP failure classification, private terminal quarantine,
aggregate advisories/counters, reconciliation tooling, governed Grafana bucket
rendering, and their offline tests are complete. Remaining work:

1. Execute the approved live crash-before-ACK/redelivery matrix across a
   threshold change for both NATS and MQTT, then retain sanitized results. The
   offline writer-restart test is complete; it is not live broker evidence.
2. Execute `scripts/reconcile_storage.py` against the final outbox lifetime and
   matching Influx logical-record count. Do not make a remote-storage
   completeness claim from the tool's existence or an incomplete result.
3. Obtain owner approval for Influx, broker, DLQ, alarm, log, source-receipt,
   and quarantine retention;
   configure and test only the approved policies and deletion controls.
4. Record owner confirmation that the historically exposed Influx token was
   rotated; never record either credential value.
5. Coordinate a runtime schema/telemetry decision that supplies stable
   experiment-run identity, absolute onset, and newly opened alarm-episode
   identity; then add a genuine Grafana onset-to-detection view. The existing
   static timeline and alarm-observation view do not satisfy this gate.
6. Run live datasource/query/render validation against final telemetry using
   the rendered governed bucket assets.
7. Exercise the paused synthetic alert end to end only after an approved
   destination is configured; retain sanitized evidence and document that the
   local `ALARMS` stream alone is not external notification delivery.
8. After live gates, update only the maintained authorities and evidence
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
