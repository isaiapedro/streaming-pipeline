# Milestone 3 Report — NATS L1–L3 Completion Work

## Implemented

- Canonical Protobuf definitions for vital signs, blood pressure, local alarm
  events, and rejected-payload envelopes.
- Protobuf publishing and decoding on the active NATS and MQTT paths.
- Structural validation before EWS state mutation, including value shape,
  patient/signal identity, numerical bounds, timestamps, versions, and blood
  pressure relationships.
- NATS dead-letter envelopes on the isolated `dlq.vitals.nats` subject,
  subject/payload identity validation, idempotent producer IDs,
  and a local continuous NEWS2 scorer that publishes medium/high alarm events.
- An opt-in Docker NATS profile with TLS and authenticated clients; local
  certificates and credentials remain untracked, and the secure connection was
  verified against the profile.
- A reference-CSV-driven synthetic-distribution validation tool that exports
  labelled histograms and KL-divergence metrics without storing clinical data.

## Verification

- Unit and integration tests cover Protobuf serialization, validation failures,
  DLQ envelopes, priority mapping, distribution-tool input, and real NATS
  publish/consume scoring. Offline broker checks terminate with bounded skips;
  `REQUIRE_NATS_INTEGRATION=true` turns an unavailable or misconfigured broker
  into a failure for explicit live verification.
- Kafka, Confluent Schema Registry, and the Kafka validated-message path are
  intentionally not included; they are Milestone 4.

## Remaining evidence action

Run `scripts/validate_distributions.py` with an approved reference CSV and a
matching synthetic CSV before claiming distribution plausibility in the
dissertation. The tool is implemented; no clinical reference data was added.
