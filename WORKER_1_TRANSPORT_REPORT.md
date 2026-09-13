# Worker 1 Transport and Schema Report

**Date:** 2026-09-13
**Scope:** Milestone 3 transport hardening and Milestone 4 isolated Kafka comparison

## Outcome

The NATS/Protobuf path now has deterministic offline tests, live transport
coverage, broker-isolated dead letters, subject/payload identity enforcement,
fail-closed secure-profile startup, and idempotent stream provisioning that no
longer hides CLI failures.

The scope gate was resolved in favor of an isolated research comparison. Kafka
and Confluent Schema Registry are implemented behind an opt-in Compose profile
without changing the NATS MVP entry points.

## Implemented

- Replaced the cancelled `localhost` connection probe that left pytest's event
  loop waiting on DNS work. The integration probe now uses numeric loopback for
  local URLs and bounded NATS-native connection settings.
- Added `REQUIRE_NATS_INTEGRATION=true`: optional local runs skip cleanly, while
  explicit live/CI runs fail on connection, authentication, or trust errors.
- Gave integration consumers unique names to prevent concurrent worker/test
  collisions.
- Added patient/signal subject-to-Protobuf identity validation before state or
  writer mutation, including the MQTT topic path.
- Moved dead letters from `vitals.dlq.nats` to `dlq.vitals.nats` and provisioned
  a separate `VITALS_DLQ` stream. Scoring consumers can no longer receive DLQ
  records through `vitals.>`.
- Added deterministic `Nats-Msg-Id` headers for rejected inputs so JetStream's
  duplicate window suppresses duplicate DLQ storage after redelivery.
- Corrected consumer provisioning to create pull consumers explicitly.
- Replaced catch-all “already exists” handling with inspect-then-create logic;
  real authentication, TLS, broker, and CLI failures now propagate.
- Added fail-closed credential checks to the secure container entry point.
- Required NATS username/password to be configured as a pair in Python.
- Derived TLS hostname verification from `NATS_URL` instead of hardcoding
  `localhost`.
- Bound local NATS, monitoring, and MQTT published ports to loopback.
- Made development certificate generation no-clobber by default, with explicit
  `--force`, restrictive `umask`, and a test-only output-directory override.
- Added isolated Kafka producer and consumer entry points using Schema
  Registry-framed canonical Protobuf records and patient-ID keys.
- Enforced `BACKWARD_TRANSITIVE` compatibility for vital and DLQ subjects,
  disabled runtime auto-registration, and added compatible/breaking evolution
  fixtures.
- Added manual commit ordering: handler success precedes valid-record commit;
  poison records commit only after DLQ delivery; handler and transient registry
  failures remain uncommitted.
- Added idempotent topic provisioning and structured source coordinates in the
  Kafka DLQ envelope.
- Added an explicit-live, aggregate-only NATS/Kafka parity harness using the
  same canonical synthetic Protobuf messages and bounded cleanup.

## Verification performed

| Check | Result |
| --- | --- |
| Complete offline pytest run | 133 passed, 2 skipped in 2.57s |
| Required live NATS integration | 2 passed |
| Required live authenticated TLS integration | 2 passed |
| Stream provisioning repeated against existing resources | Passed; no duplicate creation |
| Wrong NATS password | Rejected |
| Missing/untrusted CA | Rejected |
| Secure container with empty credentials | Exited 1 and remained stopped |
| Compose configuration parse | Passed for default and secure profiles |
| Shell syntax | Passed for stream and certificate scripts |
| Python compilation | Passed |
| `git diff --check` | Passed |
| Kafka topic provisioning, repeated | Passed; 3 vital partitions and 1 compact/delete DLQ partition |
| Schema Registry compatibility | `BACKWARD_TRANSITIVE`; additive candidate accepted, breaking candidate rejected |
| Kafka broker-free transport tests | 11 passed |
| Required live Kafka integration | 1 passed twice; valid commit and wrong-key, malformed-frame, unknown-schema DLQ paths |
| Live NATS/Kafka parity harness | 20/20 then 10/10 accepted on each transport; JSON/CSV; cleanup verified |
| Final offline Kafka/schema/parity selection | 20 passed, 1 live skip |
| Complete integrated repository suite after all worker remediation | 185 passed, 3 skipped |

The temporary insecure and secure NATS containers were left stopped after the
verification runs. Certificates, credentials, broker data, and benchmark
payloads remain outside tracked source.

## Tests added or strengthened

- Subject patient mismatch, signal mismatch, malformed subject, and incorrect
  subject shape.
- DLQ message-ID stability and input specificity.
- Rejection before state/writer mutation.
- No source acknowledgement when DLQ publication fails.
- Partial credential rejection and TLS hostname derivation.
- Stream setup failure propagation.
- Certificate no-clobber behavior and private key permissions.
- Offline bounded integration skips and required-live behavior.
- Non-interactive consumer drift reconciliation (`consumer edit --force`) and
  regression coverage, discovered by the final live release gate.

## Remaining Worker 1 risks

1. **Remote storage boundary:** Worker 3 added a durable local SQLite WAL
   outbox before broker acknowledgement, idempotent replay, and retained Influx
   retries. This establishes local durable handoff, not confirmed remote cloud
   persistence; the latter still requires live storage reconciliation evidence.
2. **Live configuration evidence:** consumer drift reconciliation is
   implemented and tested offline, but must still be executed against the
   final live NATS instance.
3. **Kafka comparison boundary:** the profile is single-broker, loopback-only,
   plaintext development infrastructure. It does not establish production
   durability, security, transactions, or the 500-patient scale claim.
4. **Credential incident closure:** the old Influx token found in repository
   history requires an owner-confirmed rotation and, if required by policy,
   history-remediation decision. No credential value belongs in this report.

## 2026-09-13 integrated release rerun

The post-remediation live rerun passed: required NATS integration 2/2,
required Kafka integration 1/1, and live transport parity accepted 20/20
messages on each transport. Secure NATS also passed 2/2 after fresh
provisioning, and an incorrect password was rejected. The first drifted NATS
provisioning attempt exposed an interactive CLI confirmation; the script now
uses explicit `--force`, and the same drifted resources reconciled and passed
the JSON contract check non-interactively.
