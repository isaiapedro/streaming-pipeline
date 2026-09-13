# Release Gate Report

**Date:** 2026-09-13
**Scope:** Integrated Worker 1–3 implementation prior to final evidence freeze

## Prior worker audit

- Worker 1 implemented schema/transport validation, isolated Kafka, broker
  rejection paths, explicit commit ordering, and consumer configuration
  contracts.
- Worker 2 implemented the crossed evidence design, episode metrics,
  aggregation, raw/run hashing, dependency verification, explicit KL direction,
  and fail-closed finalization.
- Worker 3 implemented versioned telemetry, atomic threshold snapshots, and a
  durable idempotent SQLite WAL outbox before NATS/MQTT acknowledgement.
- Coordinator integration corrected NEWS2 Scale 2 eligibility, stale-window
  scoring, single-parameter escalation, port governance, and operator docs.

## Gates executed

| Gate | Result |
| --- | --- |
| Full isolated-environment pytest | 196 passed, 3 optional-infrastructure skips |
| Installed dependency integrity | `pip check` passed |
| Compose render | Passed |
| Registry validation | Passed, 42 components |
| Git whitespace | Passed |
| NATS provisioning from existing drift | Passed after non-interactive CLI fix |
| Required live NATS integration | 2 passed |
| Required live Kafka integration | 1 passed |
| Live NATS/Kafka parity | NATS 20/20 accepted; Kafka 20/20 accepted |
| Kafka topic/schema provisioning | Passed; `BACKWARD_TRANSITIVE`, compatible candidate accepted, incompatible rejected |
| Secure NATS integration | 2 passed |
| Secure NATS wrong-password test | Rejected as required |
| Current-source secret scan | No embedded private key or literal application credential found; ignored `.env` excluded by design |

The first isolated dependency install failed closed because the original
`pytest==8.3.4` pin was incompatible with `pytest-asyncio==1.4.0`, whose
declared lower bound is pytest 8.4. The baseline was tested with pytest 9.1.1;
the direct pin was corrected to 9.1.1 and the isolated environment rebuilt
before evidence regeneration.

The first isolated test run also rejected a valid Kafka topic description:
the contract parser did not distinguish a comma inside the value
`cleanup.policy=compact,delete` from the separator before the next key. The
parser now recognizes key boundaries explicitly and retains the negative drift
test for `retention.ms`.

The live NATS gate found that `nats consumer edit` still requested confirmation
when repairing an existing `MaxAckPending` drift in a non-terminal session.
`scripts/create_streams.sh` now passes `--force`, has a regression assertion,
and successfully repaired and verified the same live consumers.

## Gates that cannot be self-attested by source code

- The owner must rotate the ignored live-looking Influx token and record only
  confirmation/date, never either token value.
- Hosted Influx publish-to-successful-storage reconciliation requires approved
  credentials and must remain unexecuted until then.
- External distribution validation requires an approved reference dataset kept
  outside Git.
- T2–T4 scale runs require approved target hardware; lack of hardware is
  `unexecuted`, not pass or fail.
- Final Grafana rendering/notification requires an approved destination and
  synthetic-only operator session.

## Evidence freeze sequence

After the implementation commit is clean, recreate the exact pinned
environment, rerun the offline tests, regenerate benchmark/run log/aggregates/
figures, commit reviewed evidence, run fail-closed final manifest mode from the
clean evidence commit, and commit the attestation. A signed release tag is not
created while any owner/external gate above is unresolved.
