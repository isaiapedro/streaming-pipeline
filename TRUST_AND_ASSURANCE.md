# Trust, Reliability, and Assurance Case

## Purpose

This document explains why the Academic streaming project can be considered
trustworthy **within its declared research scope**. It maps each assurance
claim to an implemented control, a verification mechanism, and a limitation.
It is intended for dissertation review, technical demonstrations, governance
review, and project handover.

Trust here does not mean that the software is clinically validated, certified,
production-ready, or incapable of failure. It means that the project:

- defines what it is allowed to claim;
- validates inputs before they affect state;
- makes delivery and persistence boundaries explicit;
- protects secrets and limits disclosure;
- preserves provenance and reproducibility information;
- tests important success and failure paths;
- records decisions and assigns unresolved risks to accountable owners; and
- labels missing evidence as `unexecuted` instead of treating it as success.

## Assurance status vocabulary

| Status | Meaning |
| --- | --- |
| Implemented | The control exists in code or configuration |
| Verified offline | Automated tests exercise it without external infrastructure |
| Verified live | It was exercised against the named local service |
| Run pending | The tool exists, but final controlled evidence has not been collected |
| Decision pending | Execution depends on an accountable owner approving data, retention, credentials, hardware, or recipients |
| Out of scope | The project deliberately makes no claim about this capability |

These terms prevent three common errors: describing code as measured evidence,
describing a skipped test as passed, and extrapolating a local technical result
into a clinical or production claim.

## Executive assurance summary

| Area | Implemented assurance | Current boundary |
| --- | --- | --- |
| Input integrity | Canonical Protobuf schema, structural validation, and source-subject identity checks | Synthetic inputs only |
| Delivery integrity | Source ACK/offset commit occurs after the declared local handoff or confirmed DLQ publication | Does not prove remote Influx storage |
| Local persistence | Atomic SQLite WAL outbox, full synchronization, capacity backpressure, integrity checks, retry across restart | Source-message idempotency across configuration changes remains unfinished |
| Transport isolation | Separate vital, DLQ, and alarm namespaces; bounded MQTT subscription; validation-only Kafka profile | Local single-node research infrastructure |
| Security | Loopback ports, optional authenticated TLS NATS, disposable negative tests, ignored secrets/certificates, image digests | Not a production zero-trust or multi-node deployment |
| Privacy | Synthetic-only contract, no Personal-domain inputs, aggregate-only evidence/audits, sanitized logs/errors | DLQ payloads can preserve rejected input and require controlled access/retention |
| Traceability | Schema, pipeline, threshold, approach, scenario, and transport provenance; run IDs, commit IDs, hashes | Final live storage reconciliation is pending |
| Testing | Deterministic unit/property/failure tests plus explicit opt-in live broker tests | Ordinary offline skips are not live passes |
| Reproducibility | Pinned dependencies, deterministic seeds, crossed design, manifests, checksums, fail-closed final mode | Final artifacts must be regenerated from the selected clean baseline |
| Accountability | Behavior contract, decision log, worker ownership, Registry validation, release gates | Several external and retention decisions still require owners |

## 1. Scope and claim control

The first reliability control is the project boundary itself.

- The system processes generated synthetic patient profiles and signals.
- It is a software and transport experiment, not a medical device.
- It does not establish diagnostic accuracy, clinical effectiveness, patient
  safety, hospital-scale readiness, or compliance certification.
- The supported scientific claim is a synthetic comparison of detection speed
  and nuisance-alarm burden under the declared generator, scoring rules, seeds,
  and runtime environment.
- Kafka results cover schema/transport acceptance, rejection, and local
  latency. Kafka does not run the Brain scoring/outbox/Influx/alarm application
  path and is not application or outcome parity.
- Supplemental oxygen and consciousness components are fixed at zero in the
  constrained NEWS2 implementation and must remain disclosed.

The authoritative boundaries are `BEHAVIOR.md`, `DECISIONS.md`,
`TELEMETRY_CONTRACT.md`, and `IMPLEMENTATION_BLUEPRINT.md`.

## 2. Security controls

### Network and service exposure

- Published NATS, monitoring, MQTT, Kafka, and Schema Registry ports bind to
  loopback, limiting the declared Compose deployment to the local host.
- Host ports are allocated in the root Registry. The infrastructure doctor
  compares the selected Compose service's actual published ports with that
  Registry rather than trusting a duplicated informal list.
- The doctor refuses to start a selected profile when a governed port already
  has an unidentified listener.
- Services have health checks, and the doctor verifies that the specifically
  selected Compose services are running before live provisioning.
- NATS, Mosquitto, Kafka, and Schema Registry images are pinned by digest,
  reducing ambiguity from mutable image tags.

### Authentication and transport security

- NATS credentials must be supplied as a username/password pair; partial
  credential configuration fails closed.
- The secure NATS profile requires credentials and uses TLS with hostname and
  CA verification.
- `scripts/verify_secure_nats.py` creates temporary certificates and random
  credentials in an isolated Compose project. It verifies that authenticated
  trusted TLS succeeds and that anonymous, wrong-password, and untrusted-CA
  connections fail.
- The verifier rechecks the authenticated connection between negative probes,
  applies subprocess/connect timeouts, and removes its disposable container and
  volume so credentials are not retained in stopped-container metadata.

### Secret management

- `.env`, generated NATS certificates, runtime databases, and virtual
  environments are ignored by Git.
- Influx configuration has no committed fallback credential; secrets are
  injected through the operator environment.
- The sanitized infrastructure inventory hashes an uninterpolated selected
  service model, so its configuration fingerprint is not derived from secret
  values.
- Logs, evidence artifacts, and audit outputs must not include credentials or
  endpoints.
- A historically exposed Influx token has an explicit owner-confirmation gate.
  Repository state cannot prove rotation, and neither the old nor new token may
  be recorded as evidence.

### Local storage hardening

- The SQLite outbox parent directory and database are restricted to private
  filesystem modes where supported.
- Symbolic-link database paths are rejected to reduce accidental redirection.
- SQLite uses WAL mode, `synchronous=FULL`, a busy timeout, and an integrity
  check at open.
- Legacy arbitrary exception strings are scrubbed from existing outbox rows.

### Security limitations

The current controls support a local research deployment. They do not establish
production mutual TLS, secret-manager integration, broker authorization roles,
multi-node resilience, hardened host security, formal penetration testing, or
regulatory certification. Kafka and MQTT remain plaintext loopback services in
the declared comparison profiles.

## 3. Privacy and data-disclosure controls

### Data allowed by context

| Context | Allowed |
| --- | --- |
| Runtime brokers/outbox/Influx | Synthetic profiles, synthetic vital values, derived synthetic alarms, bounded provenance |
| Runtime logs | Counts, durations, severity, signal class, approach, scenario, versions, and safe error class/status |
| Repository evidence | Aggregate metrics, synthetic seed/configuration provenance, non-sensitive run IDs, commit IDs, hashes, statuses, figures |
| Traceability/outbox audits | Aggregate counts, percentages, integrity state, retry/age/size summaries |

### Data prohibited from disclosure

- Real patient or clinical rows.
- Personal-domain observations or author records.
- Credentials, tokens, passwords, private keys, or certificate secrets.
- Raw reference-dataset rows.
- Raw vital values paired with patient identifiers in logs or evidence.
- Message subjects, broker endpoints, filesystem paths, or arbitrary remote
  exception text in privacy-safe audit artifacts.

External reference datasets must remain outside Git and be supplied explicitly
under an approved licence or data-use basis. Only governed aggregate outputs,
a non-sensitive source identifier, transformation version, and content hashes
may enter the evidence bundle.

### Dead-letter disclosure risk

NATS, MQTT, and Kafka dead-letter envelopes intentionally retain the rejected
payload for diagnosis. This is useful for accountability but increases
disclosure risk if prohibited data is submitted. The project therefore relies
on the synthetic-only ingress rule, isolated DLQ namespaces, controlled access,
short retention, and owner-approved deletion policy. A DLQ is not a safe place
for real patient data.

## 4. Logging and diagnostic safety

Logging follows data minimization rather than recording entire events.

- Rejection logs report a bounded validation reason without the subject,
  patient identifier, or raw vital value.
- Influx failures retain only the exception class and optional numeric HTTP
  status. Exception messages—which can contain tokens, endpoints, or query
  text—are neither logged nor persisted.
- Startup logs do not print the outbox path.
- Runtime AST-based tests inspect logging calls for identifier, value, endpoint,
  and secret variables.
- Behavioral tests inject secret-looking exception text and confirm it does not
  appear in logs or the outbox.
- The outbox auditor reports aggregate health without exporting paths,
  payloads, identifiers, or error text.

Logging is not a substitute for operational monitoring. Maximum-attempt
classification, terminal quarantine, and privacy-safe advisories remain
unfinished; current Influx retry is bounded in delay but not in total attempts.

## 5. Traceability and auditability

The project uses this traceability chain:

`claim -> decision/requirement -> code -> test -> run -> aggregate -> figure`

Runtime telemetry carries bounded provenance:

- `schema_version`: accepted message contract;
- `pipeline_version`: producing software/build identity;
- `threshold_version`: exact scoring configuration;
- `scoring_approach`: A, B, or C;
- `scenario_id`: declared synthetic scenario;
- `transport`: NATS or MQTT; and
- synthetic patient/signal dimensions needed for controlled analysis.

Threshold hot reload validates a complete replacement before atomically
updating the active snapshot and version. Alarm events preserve schema and
pipeline identity in Protobuf and carry approach, scenario, and threshold
identity in NATS headers.

The benchmark records scenario, independent signal/noise seeds, run ID, timing,
status, commit identity, and dirty-tree state. The evidence manifest checks the
expected design, dependencies, source hashes, run/commit relationship, and
release blockers. `SHA256SUMS` detects changes to governed evidence files.

`scripts/audit_traceability.py` can inspect an approved CSV export or an
explicitly authorized live Influx query. Its result exposes only tag-presence
counts and percentages. This interface is implemented and tested; the final
live traceability/reconciliation run is pending.

## 6. Message integrity and delivery accountability

### Ingress validation

- NATS and MQTT decode the canonical Protobuf message before changing state.
- Required identifiers, signal type, value shape/range, schema version, and
  source identity are validated.
- The patient and signal in the payload must match the NATS subject or mapped
  MQTT topic.
- Invalid input cannot enter scoring or telemetry storage.
- Kafka uses Schema Registry framing, fixed value subjects, runtime
  auto-registration disabled, and `BACKWARD_TRANSITIVE` compatibility checks.

### Acknowledgement boundaries

| Path | Required before source acknowledgement/commit |
| --- | --- |
| Valid NATS input | Atomic commit of every derived record to the SQLite WAL outbox |
| Invalid NATS input | Confirmed structured publication to the isolated NATS DLQ |
| Valid MQTT input | Atomic commit of every derived record to the SQLite WAL outbox |
| Invalid MQTT input | QoS 1 PUBACK for `dlq/vitals/mqtt` |
| Local NATS alarm | JetStream publish acknowledgement from the `ALARMS` stream |
| Valid Kafka input | Completion of the supplied synchronous validation handler |
| Invalid Kafka input | Confirmed structured Kafka DLQ delivery |

Kafka auto commit and automatic offset storage are disabled. Registry outages
that are potentially transient remain retryable and are not misclassified as
poison input. MQTT source ACK is withheld when DLQ PUBACK fails. NATS source
ACK is withheld when its DLQ or alarm publication fails.

An acknowledgement proves only the boundary in this table. In particular,
outbox commit does not prove successful remote Influx storage, MQTT PUBACK does
not prove durable archival, and the Kafka command-line handler prints validated
records rather than storing application outcomes.

## 7. Persistence, recovery, and idempotency

- All records derived from one accepted NATS/MQTT message are inserted in one
  SQLite transaction before broker ACK.
- Capacity is checked before insertion. Exceeding the configured maximum fails
  the handoff and leaves the broker message unacknowledged, applying
  backpressure instead of dropping data.
- Influx delivery happens asynchronously after the local durable handoff.
- Failed writes remain in the outbox with attempt count, next-attempt time, and
  bounded exponential delay across process restart.
- Tentative scoring/batch state is rolled back when the durable handoff fails.
- Exact derived records have stable content hashes, and Influx point identity
  also uses stable tags and timestamp to suppress identical replay.

Current idempotency does not yet derive from the original broker message. If a
redelivery is evaluated under changed thresholds/configuration, it can create a
different derived record. Stable source-message identity and crash tests across
configuration changes remain open. Terminal failures also retry indefinitely
because quarantine/advisory policy is not yet implemented.

## 8. Stream and configuration governance

- `VITALS` and `VITALS_DLQ` are file-backed with 24-hour maximum age.
- `ALARMS` is file-backed with seven-day maximum age.
- `BRAIN` and `LOCAL_SCORER` consumers use explicit ACK, 30-second `AckWait`,
  three maximum deliveries, and 500 maximum pending acknowledgements.
- Provisioning reconciles mutable settings non-interactively, validates the
  full declared contract afterward, and propagates CLI/authentication errors.
- Kafka provisioning verifies fixed topic names, partitions, replication, DLQ
  cleanup policy, and retention. Unsupported environment topic overrides fail.
- The threshold snapshot is validated and versioned as one unit.

Broker retention is not the same as Influx or evidence retention. The current
one-day broker DLQ policies differ from the proposed seven-day review period;
changing them requires explicit privacy/operations approval.

## 9. Testing strategy and evidence

The test strategy uses several layers:

| Layer | Examples |
| --- | --- |
| Deterministic unit tests | Threshold boundaries, NEWS2 scale, complete/stale windows, alarm episodes, schema validation |
| Failure-ordering tests | DLQ failure prevents ACK/commit, outbox failure rolls back state, handler failure prevents Kafka commit |
| Security/privacy tests | Credential pairing, TLS hostname, no-clobber certificates, sanitized errors/logs, private outbox, symlink rejection |
| Contract-drift tests | NATS streams/consumers, Kafka topics/configuration, Schema Registry compatibility |
| Evidence tests | 5×5 crossed seeds, 450 rows, 150 runs, 24-hour stable cells, dirty final-mode refusal, hashes |
| Dashboard tests | Datasource identity, TLS verification, filters, A/B/C query semantics, paused alert default |
| Optional live tests | NATS valid/DLQ/ALARMS, MQTT PUBACK/DLQ, Kafka schema/DLQ, secure TLS, parity |

The latest recorded offline gate passed 210 tests with five optional live tests
skipped. Those skips mean “not executed in this offline command,” not “passed.”
Separate live checks passed the NATS valid/DLQ/ALARMS paths, MQTT invalid-DLQ
ordering, Kafka schema/DLQ paths, secure NATS positive/negative probes, and a
parity run with 10 valid acceptances plus one intentional rejection on each
transport.

Final evidence requires rerunning all applicable tests from the selected clean
commit and exact environment. Restart, broker interruption, replay,
max-delivery advisory, full persistence, and storage reconciliation matrices
remain incomplete.

## 10. Reproducibility and evidence integrity

- Direct Python dependencies are exactly pinned.
- Container images are digest-pinned.
- Synthetic runs use explicit independent signal/noise seeds.
- The declared experiment crosses six scenarios, five signal seeds, five noise
  seeds, and three approaches: 450 approach rows and 150 source runs.
- Stable-baseline cells use 86,400 simulated seconds.
- Missing/inapplicable values stay missing instead of becoming zero.
- Detection requires a newly opened post-onset episode; an alarm already open
  at onset is not credited.
- Probability intervals and bootstrap summaries are documented, and
  `KL(P_synthetic || P_reference)` is named directionally.
- Final manifest generation fails before overwriting evidence when cleanliness,
  dependency, artifact, or attestation blockers exist.

Current evidence is development evidence and must be regenerated from the
selected clean implementation/evidence chain. Protocol restart dimensions,
successful-storage latency, scale T2–T4, external-reference validation, live
traceability, and Grafana/alert evidence remain `unexecuted` or partial.

## 11. Accountability and governance

| Authority | Accountability function |
| --- | --- |
| `BEHAVIOR.md` | Defines mandatory privacy, runtime, and evidence behavior |
| `DECISIONS.md` | Records accepted architecture/scientific choices and limitations |
| `IMPLEMENTED.md` | Records completed work, historical verification, and owner decisions |
| `IMPLEMENTATION_BLUEPRINT.md` | Assigns remaining work and final release gates |
| `OPERATIONS_AND_REPRODUCIBILITY.md` | Provides canonical commands, maintenance, recovery, and evidence procedure |
| `TELEMETRY_CONTRACT.md` | Defines metadata, persistence, logging, retention, credential, and alert boundaries |
| Root Registry | Owns repository boundaries, ports, and cross-workspace dependencies |
| Evidence manifest/checksums | Bind runs and artifacts to commits, dependencies, hashes, and blockers |

Worker ownership separates transport/schema, experimental evidence, and
telemetry/visualization work. Shared semantic changes require a decision-log
update. The nested Academic repository is independently versioned, while root
Registry changes remain governed at the workspace root.

Unresolved choices are not silently encoded as defaults. Independent data,
scale hardware, retention, credential rotation, reconciliation tolerance, and
alert recipients require named owner decisions before their associated claims
can be released.

## 12. Evidence levels and acceptable wording

| Level | What may be said now |
| --- | --- |
| V0 — Unit correctness | “The declared algorithms and failure boundaries pass automated tests.” |
| V1 — Simulation verification | “The deterministic synthetic experiment produced the recorded development results under its declared design.” |
| Narrow V2 — Live technical validation | “The specifically executed local broker/TLS paths passed their recorded checks.” |
| V3 — Independent external validation | Not available until an approved independent reference run is completed |
| V4 — Clinical validation | Not available; outside current scope |

Recommended explanation:

> The project is trustworthy for its declared synthetic research purpose
> because it validates inputs, delays acknowledgement until explicit local
> handoff boundaries, minimizes disclosure, preserves provenance, tests failure
> ordering, and fails closed when release evidence is incomplete. Its documents
> also state the remaining limits: it is not clinically validated, remote
> storage completeness and full recovery are not yet proven, and external data,
> retention, credentials, scale, and alert delivery require controlled final
> runs or owner approval.

Avoid statements such as “HIPAA compliant,” “clinically safe,” “exactly once,”
“production ready,” “500-patient capable,” or “end-to-end durable” because the
current evidence does not establish them.

## 13. Open assurance gaps

The following gaps are explicitly tracked rather than hidden:

- source-message-derived outbox idempotency across configuration changes;
- terminal-failure quarantine and operational advisories;
- broker/input/outbox/Influx reconciliation;
- benchmark interruption recovery and dependence-aware inference;
- controlled restart, fault, replay, persistence, and memory tests;
- successful-storage latency;
- accepted T2–T4 scale evidence;
- approved external-reference validation;
- configured and tested retention/deletion policies;
- owner-confirmed credential rotation;
- governed Grafana bucket configuration, genuine onset-to-detection view, live
  rendering, and approved notification receipt;
- tracked-secret release scan and independent clean-clone reproduction.

The authoritative task ownership and sequencing for these gaps is maintained in
`IMPLEMENTATION_BLUEPRINT.md`.

## 14. Verification commands

Run from the Academic repository root:

```bash
# Offline correctness and dependency integrity
python -m pip check
python -m pytest -q
git diff --check

# Static infrastructure and Registry agreement
python scripts/infrastructure_doctor.py --profile nats
docker compose config --quiet
python3 ../../registry/implementation/cli.py check

# Required local live gates (start/provision services first)
REQUIRE_NATS_INTEGRATION=true python -m pytest -q brain/tests/test_integration_nats.py
REQUIRE_MQTT_INTEGRATION=true python -m pytest -q brain/tests/test_integration_mqtt.py
REQUIRE_KAFKA_INTEGRATION=true python -m pytest -q brain/tests/test_integration_kafka.py
python -m kafka_path.parity --live --count 10 --timeout 20 --format json

# Privacy-safe local and hosted audits
python scripts/audit_outbox.py --database .runtime/influx_outbox.sqlite3 \
  --output evidence/outbox_health.json --require-healthy
python scripts/audit_traceability.py --live --range 1h \
  --output evidence/traceability_audit.json --require-complete
```

Live and evidence commands must follow `OPERATIONS_AND_REPRODUCIBILITY.md`.
Never run them against real patient data or an unapproved external service.
