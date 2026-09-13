#!/usr/bin/env bash
# Generates an untracked local-development certificate for secured NATS runs.
set -euo pipefail
umask 077

CERT_DIR="${NATS_CERT_DIR:-$(cd "$(dirname "$0")/.." && pwd)/nats/certs}"
FORCE=false
if [[ "${1:-}" == "--force" ]]; then
  FORCE=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--force]" >&2
  exit 2
fi

mkdir -p "$CERT_DIR"
if [[ "$FORCE" != true ]] && [[ -e "$CERT_DIR/nats-key.pem" || -e "$CERT_DIR/nats-cert.pem" ]]; then
  echo "Certificate material already exists; use --force to replace it." >&2
  exit 1
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout "$CERT_DIR/nats-key.pem" \
  -out "$CERT_DIR/nats-cert.pem" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
echo "Generated development certificate in $CERT_DIR"
