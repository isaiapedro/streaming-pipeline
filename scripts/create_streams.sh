#!/usr/bin/env bash
# Creates the NATS JetStream stream and durable consumer for patient vitals.
# Run once after `docker compose up`.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

NATS_URL="${NATS_URL:-nats://localhost:4222}"
NATS_ARGS=(--server "$NATS_URL")
if [[ -n "${NATS_USER:-}" ]]; then NATS_ARGS+=(--user "$NATS_USER"); fi
if [[ -n "${NATS_PASSWORD:-}" ]]; then NATS_ARGS+=(--password "$NATS_PASSWORD"); fi
if [[ "${NATS_TLS:-false}" == "true" ]]; then
  if [[ -n "${NATS_CA_FILE:-}" ]]; then NATS_ARGS+=(--tlsca "$NATS_CA_FILE"); fi
fi

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CMD="$PYTHON_BIN"
elif [[ -x "$PROJECT_DIR/tcc_env/bin/python" ]]; then
  PYTHON_CMD="$PROJECT_DIR/tcc_env/bin/python"
else
  PYTHON_CMD="python3"
fi

create_or_verify_consumer() {
  local consumer="$1"
  echo "Creating durable consumer ${consumer}..."
  if nats "${NATS_ARGS[@]}" consumer info VITALS "$consumer" >/dev/null 2>&1; then
    # AckWait, MaxDeliver, MaxAckPending and the filter are mutable. Reconcile
    # them idempotently, then verify the complete contract (including the
    # immutable explicit-ack policy) before any application consumes data.
    nats "${NATS_ARGS[@]}" consumer edit VITALS "$consumer" \
      --filter "vitals.>" \
      --wait 30s \
      --max-deliver 3 \
      --max-pending 500 \
      --force \
      --no-interactive
    nats "${NATS_ARGS[@]}" consumer info VITALS "$consumer" --json \
      | "$PYTHON_CMD" "$PROJECT_DIR/scripts/check_nats_consumer_config.py" "$consumer"
    echo "Consumer ${consumer} exists and matches the local contract."
  else
    nats "${NATS_ARGS[@]}" consumer add VITALS "$consumer" \
      --pull \
      --filter "vitals.>" \
      --ack explicit \
      --wait 30s \
      --deliver all \
      --max-deliver 3 \
      --max-pending 500 \
      --defaults
    nats "${NATS_ARGS[@]}" consumer info VITALS "$consumer" --json \
      | "$PYTHON_CMD" "$PROJECT_DIR/scripts/check_nats_consumer_config.py" "$consumer"
  fi
}

create_or_verify_stream() {
  local stream="$1"
  local subjects="$2"
  local max_age="$3"
  echo "Creating stream ${stream}..."
  if nats "${NATS_ARGS[@]}" stream info "$stream" >/dev/null 2>&1; then
    nats "${NATS_ARGS[@]}" stream edit "$stream" \
      --subjects "$subjects" \
      --retention limits \
      --max-age "$max_age" \
      --replicas 1 \
      --force \
      --no-interactive
  else
    nats "${NATS_ARGS[@]}" stream add "$stream" \
      --subjects "$subjects" \
      --storage file \
      --retention limits \
      --max-age "$max_age" \
      --replicas 1 \
      --defaults
  fi
  nats "${NATS_ARGS[@]}" stream info "$stream" --json \
    | "$PYTHON_CMD" "$PROJECT_DIR/scripts/check_nats_stream_config.py" "$stream"
  echo "Stream ${stream} matches the local contract."
}

create_or_verify_stream VITALS "vitals.>" 24h
create_or_verify_stream VITALS_DLQ "dlq.vitals.>" 24h
create_or_verify_stream ALARMS "alarms.>" 168h

create_or_verify_consumer BRAIN
create_or_verify_consumer LOCAL_SCORER

echo "Done."
