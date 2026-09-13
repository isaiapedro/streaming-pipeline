# Milestone 4 — Transport and Schema Verification

**Date:** 2026-09-13
**Decision:** Implemented comparison
**Boundary:** Opt-in local research path; NATS remains the MVP transport

## Delivered

- Single-node KRaft Kafka and Confluent Schema Registry 8.3.1 behind the
  `kafka` Compose profile, with Registry-allocated host ports `19092` and
  `18081` bound to loopback.
- Idempotent provisioning for `vitals.protobuf.v1` (three partitions) and
  `vitals.dlq.protobuf.v1` (one partition, compact/delete, one-day retention).
- Schema Registry-framed canonical `VitalSign` and `DeadLetterEnvelope`
  Protobuf records.
- `BACKWARD_TRANSITIVE` policy on both value subjects, explicit provisioning,
  and fail-closed runtime clients with schema auto-registration disabled.
- Patient-ID record keys, idempotent production, `read_committed` consumption,
  and synchronous manual offset commits.
- Poison-record DLQ handling with stable rejection keys and structured source
  topic, partition, offset, and timestamp fields.
- Independent producer, consumer, and provisioning CLIs under `kafka_path/`;
  no changes route the NATS application through Kafka.
- An opt-in aggregate parity harness sends identical canonical synthetic
  messages through NATS and Kafka and reports fixed success, rejection, P50,
  and P99 fields in JSON or CSV.

## Failure semantics

| Condition | DLQ | Source offset |
| --- | --- | --- |
| Valid record and successful handler | No | Commit after handler |
| Structural/key/schema-ID poison record | Publish and confirm | Commit after DLQ delivery |
| Handler/storage failure | No | Do not commit |
| Transient Schema Registry failure | No | Do not commit |
| DLQ delivery failure | Delivery attempted | Do not commit |

This ordering prevents acknowledged loss. It remains at-least-once: a process
failure between DLQ delivery and source commit can repeat the rejection. The
stable rejection key plus compacted DLQ bounds the durable duplicate footprint.

## Reproducible verification

```bash
docker compose --profile kafka up -d --wait kafka schema-registry
bash scripts/create_kafka_topics.sh
bash scripts/create_kafka_topics.sh
python -m kafka_path.provision
python -m pytest brain/tests/test_kafka_transport.py \
  brain/tests/test_integration_kafka.py -q
REQUIRE_KAFKA_INTEGRATION=true \
  python -m pytest brain/tests/test_integration_kafka.py -q
python -m kafka_path.parity --live --count 20 --timeout 20 --format json
```

Observed results:

- Topic provisioning succeeded twice without duplicate-resource failures.
- Both subjects reported `BACKWARD_TRANSITIVE`.
- Additive Protobuf evolution was accepted; a field-type change was rejected.
- Broker-free Kafka suite: 11 passed.
- Sandboxed optional mode: 11 passed, 1 skipped when the infrastructure check
  cannot reach the local services.
- Required live integration: 1 passed twice against retained topic history,
  exercising valid delivery/commit plus wrong-key, malformed-frame, and
  unknown-schema-ID records through the structured DLQ.
- Live parity runs accepted 20/20 and then 10/10 identical synthetic messages
  on each transport, emitted both JSON and CSV, and left no temporary NATS
  consumer. The observed latency values are local development measurements,
  not benchmark evidence or a production comparison.
- Compose parsing, shell syntax, Python compilation, and `git diff --check`
  passed.
- Root Registry validation passed for 42 components after reserving ports
  `18081` and `19092` in `registry/PORTS.md`.
- Final offline Kafka/schema/parity selection: 20 passed and 1 live test
  skipped while the brokers were intentionally stopped.
- After the parallel lanes reconciled their temporary interface drift, the
  complete repository suite passed with 196 tests and 3 optional-infrastructure
  skips.

## Known limitations

- One broker and combined broker/controller mode are for local comparison only.
- Kafka and Schema Registry use plaintext loopback listeners; production
  authentication, authorization, and encryption are not implemented.
- No Kafka transactions or atomic source-to-DLQ transaction are claimed.
- The test establishes behavior, not 500-patient throughput or hosted-service
  durability.
- The third-party client currently emits an Authlib `httpx` deprecation warning;
  it does not fail the tested path.

The NATS, Kafka, and Schema Registry test containers were stopped after
verification. The pre-existing Mosquitto container was left untouched. Broker
volumes were retained for reproducibility; no payload capture or credential was
added to source control.
