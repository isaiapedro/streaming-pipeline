#!/usr/bin/env bash
# Creates the NATS JetStream stream and durable consumer for patient vitals.
# Run once after `docker compose up`.

set -euo pipefail

NATS_URL="${NATS_URL:-nats://localhost:4222}"

echo "Creating stream VITALS..."
nats --server "$NATS_URL" stream add VITALS \
  --subjects "vitals.>" \
  --storage file \
  --retention limits \
  --max-age 24h \
  --replicas 1 \
  --defaults 2>/dev/null || echo "Stream VITALS already exists."

echo "Creating durable consumer BRAIN..."
nats --server "$NATS_URL" consumer add VITALS BRAIN \
  --filter "vitals.>" \
  --ack explicit \
  --deliver all \
  --max-deliver 3 \
  --defaults 2>/dev/null || echo "Consumer BRAIN already exists."

echo "Done."
