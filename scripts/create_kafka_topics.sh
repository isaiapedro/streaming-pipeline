#!/usr/bin/env bash
# Creates the isolated Kafka research topics without masking broker or CLI failures.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$PROJECT_DIR/docker-compose.yml" --profile kafka)
BOOTSTRAP_SERVER="kafka:29092"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CMD="$PYTHON_BIN"
elif [[ -x "$PROJECT_DIR/tcc_env/bin/python" ]]; then
  PYTHON_CMD="$PROJECT_DIR/tcc_env/bin/python"
else
  PYTHON_CMD="python3"
fi

create_topic() {
  local topic="$1"
  local partitions="$2"
  shift 2

  "${COMPOSE[@]}" exec -T kafka kafka-topics \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor 1 \
    "$@"

  local description
  description="$("${COMPOSE[@]}" exec -T kafka kafka-topics \
    --bootstrap-server "$BOOTSTRAP_SERVER" \
    --describe \
    --topic "$topic")"
  printf '%s\n' "$description"
  printf '%s\n' "$description" \
    | "$PYTHON_CMD" "$PROJECT_DIR/scripts/check_kafka_topic_config.py" "$topic"
}

create_topic "vitals.protobuf.v1" 3
create_topic "vitals.dlq.protobuf.v1" 1 \
  --config "cleanup.policy=compact,delete" \
  --config "retention.ms=86400000"
