# Academic Workspace Behavior Contract

## Domain scope

This folder contains the synthetic patient-vitals research implementation,
tests, local infrastructure definitions, dashboards, and aggregate dissertation
evidence. It is an independent nested repository and must not import runtime
data from the Personal domain.

## Required behavior

- Only synthetic profiles and signals may enter the pipeline, DLQ, InfluxDB,
  Grafana, logs, screenshots, or repository evidence.
- NATS/MQTT input must pass the canonical Protobuf and subject-identity
  validation before it changes scoring state.
- Accepted broker messages are acknowledged only after their complete derived
  telemetry batch commits to the private SQLite WAL outbox.
- Remote InfluxDB delivery is asynchronous. Local acknowledgement must never be
  described as confirmed cloud storage without separate reconciliation.
- Approach and NEWS2 semantics must follow `DECISIONS.md`; missing or stale
  composite inputs do not produce a score.
- Runtime records retain schema, pipeline, threshold, approach, scenario, and
  transport provenance.
- Operational logs and audit artifacts must not expose patient identifiers,
  raw vital values, message subjects, credentials, endpoints, row-level
  reference data, or arbitrary remote exception text.
- Reference datasets stay outside Git and are supplied explicitly under an
  approved licence or data-use basis. Only governed aggregates may enter
  `evidence/`.
- Final evidence must be reproduced from a reviewed clean commit and exact
  pinned environment. Missing live or external evidence is labelled
  `unexecuted`, never zero or passed.

## Authorities

- `DECISIONS.md`: accepted scientific and architectural standards.
- `TELEMETRY_CONTRACT.md`: persistence, telemetry, privacy, retention, and
  alert rules.
- `OPERATIONS_AND_REPRODUCIBILITY.md`: executable operator procedure.
- `IMPLEMENTATION_BLUEPRINT.md`: remaining work, sequencing, and release
  gates.
- `IMPLEMENTED.md`: consolidated implementation status, historical checks,
  pending decisions, and unfinished work.
- `TRUST_AND_ASSURANCE.md`: evidence-backed explanation of security, privacy,
  reliability, testing, traceability, accountability, and claim limitations.
