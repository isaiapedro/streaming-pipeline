# Runtime telemetry and compliance contract

## Metadata meanings

Every `patient_vitals` and `alarms` point carries the following tags:

| Tag | Meaning | Source |
| --- | --- | --- |
| `schema_version` | Canonical message contract accepted at ingress | Validated `VitalSign` |
| `pipeline_version` | Producer/build version carried by that message | Validated `VitalSign` |
| `threshold_version` | Exact scoring configuration | Content hash for Approach A; `news2-2017-room-air-v1` for B/C |
| `scoring_approach` | Existing A, B, or C definition | Runtime scoring branch |
| `scenario_id` | Synthetic scenario, or `none` | Validated `VitalSign` |
| `transport` | Ingress path (`nats` or `mqtt`) | Runtime consumer |

Approach A captures one immutable threshold snapshot before evaluation. A hot
reload validates the complete next configuration and then replaces values and
version together. Approaches B/C use fixed NEWS2 tables and therefore carry a
separate stable version instead of the mutable Approach A configuration hash.

The local NATS alarm Protobuf schema is frozen by the transport worker. Its
validated schema and pipeline versions remain in `AlertEvent`; approach,
scenario, and threshold version are carried in NATS headers until a future
coordinator-owned schema revision is approved.

## Persistence and acknowledgement boundary

Each accepted broker message produces its complete set of telemetry records in
one SQLite WAL transaction. NATS and MQTT acknowledge that input only after the
transaction commits. A capacity or local persistence failure leaves the input
unacknowledged and restores tentative scoring/batch state so broker redelivery
can retry it. Stable content-derived keys make this redelivery idempotent at
the outbox boundary.

InfluxDB delivery occurs after acknowledgement. A delivery failure increments
retry metadata and retains the records for bounded exponential retry across
restart; it does not discard the batch. Consequently, acknowledgement proves a
local durable handoff, not successful remote storage. An end-to-end storage
claim requires separate publish-to-successful-write evidence and reconciliation
between broker input, outbox state, and InfluxDB output.

The default outbox lives at `.runtime/influx_outbox.sqlite3`, outside version
control. Its parent and database use private permissions. Operators must
monitor pending rows, retry attempts, last error, database integrity, and disk
capacity; reaching the configured maximum deliberately applies backpressure.

## Privacy and logging

Runtime logs may include approach, signal class, scenario, version, severity,
counts, and durations. They must not combine a patient identifier with a raw
vital value. InfluxDB contains synthetic patient context required by the
experiment and must not receive real clinical data under this prototype
contract.

## Retention

| Data class | Proposed default (not active until owner approval) | Disposal / review |
| --- | --- | --- |
| Raw synthetic vitals | 30 days | Bucket retention policy; shorten after experiment freeze |
| Synthetic alarm events | 180 days | Review after dissertation acceptance |
| DLQ envelopes | 7 days | Delete after triage; payload may contain rejected input |
| Aggregate experiment evidence | Through dissertation archive period | Versioned aggregate files and checksums only |
| Logs | 14 days | No raw vital-plus-identifier pairs |

Cloud retention is an operator configuration, not embedded in source. These
values are proposals until the owner approves them. Before a hosted run, the
operator must verify the actual bucket policies match the approved values and
record only non-secret confirmation evidence.

## Credential status

The source no longer contains a fallback InfluxDB credential, and `.env` plus
generated certificates are ignored. Rotation of the historically exposed
InfluxDB token cannot be established from repository state. Status:
**operator confirmation pending**. Record the confirmation date here after
rotation; never record either the old or replacement token.

## Alert activation

The provisioned synthetic critical-alert rule is paused by default and has no
committed notification endpoint. An operator may activate it only after
selecting an approved destination, confirming the input is synthetic, and
recording a non-sensitive test date and outcome.
