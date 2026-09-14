import os
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# NATS JetStream
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
NATS_USER = os.getenv("NATS_USER")
NATS_PASSWORD = os.getenv("NATS_PASSWORD")
NATS_TLS = os.getenv("NATS_TLS", "false").lower() == "true"
NATS_CA_FILE = os.getenv("NATS_CA_FILE")
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "dev")
SCHEMA_VERSION = "1"


def nats_connection_options() -> dict:
    """Build authenticated/TLS NATS options without exposing secrets in code."""
    if bool(NATS_USER) != bool(NATS_PASSWORD):
        raise RuntimeError("NATS_USER and NATS_PASSWORD must be configured together")
    options: dict = {"servers": NATS_URL}
    if NATS_USER:
        options["user"] = NATS_USER
    if NATS_PASSWORD:
        options["password"] = NATS_PASSWORD
    if NATS_TLS:
        options["tls"] = ssl.create_default_context(cafile=NATS_CA_FILE or None)
        hostname = urlsplit(NATS_URL).hostname
        if not hostname:
            raise RuntimeError("NATS_URL must contain a hostname when NATS_TLS=true")
        options["tls_hostname"] = hostname
    return options

# InfluxDB Cloud — no hardcoded default. Real values live in `.env`
# (gitignored, not committed) — see `.env` for setup instructions.
INFLUX_URL    = os.getenv("INFLUX_URL")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN")
INFLUX_ORG    = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")
INFLUX_TIMEOUT_MS = int(os.getenv("INFLUX_TIMEOUT_MS", "10000"))

# Brain persistence settings. The local SQLite WAL is the acknowledgement
# boundary: a broker message is acknowledged only after every derived record is
# committed here. Keep this path on persistent, access-controlled local storage.
_outbox_path = Path(os.getenv("INFLUX_OUTBOX_PATH", ".runtime/influx_outbox.sqlite3"))
INFLUX_OUTBOX_PATH = _outbox_path if _outbox_path.is_absolute() else PROJECT_ROOT / _outbox_path
INFLUX_OUTBOX_MAX_RECORDS = int(os.getenv("INFLUX_OUTBOX_MAX_RECORDS", "100000"))
INFLUX_OUTBOX_MAX_ATTEMPTS = int(os.getenv("INFLUX_OUTBOX_MAX_ATTEMPTS", "10"))
INFLUX_RETRY_BASE_S = float(os.getenv("INFLUX_RETRY_BASE_S", "1"))
INFLUX_RETRY_MAX_S = float(os.getenv("INFLUX_RETRY_MAX_S", "60"))

# Brain flush settings
FLUSH_INTERVAL_S  = float(os.getenv("FLUSH_INTERVAL_S", "1"))
FLUSH_BUFFER_SIZE = int(os.getenv("FLUSH_BUFFER_SIZE", "500"))

if INFLUX_OUTBOX_MAX_RECORDS < 1:
    raise RuntimeError("INFLUX_OUTBOX_MAX_RECORDS must be at least 1")
if INFLUX_OUTBOX_MAX_ATTEMPTS < 1:
    raise RuntimeError("INFLUX_OUTBOX_MAX_ATTEMPTS must be at least 1")
if INFLUX_TIMEOUT_MS < 1:
    raise RuntimeError("INFLUX_TIMEOUT_MS must be at least 1")
if FLUSH_INTERVAL_S <= 0 or FLUSH_BUFFER_SIZE < 1:
    raise RuntimeError("FLUSH_INTERVAL_S and FLUSH_BUFFER_SIZE must be positive")
if INFLUX_RETRY_BASE_S <= 0 or INFLUX_RETRY_MAX_S < INFLUX_RETRY_BASE_S:
    raise RuntimeError("Influx retry settings must be positive and max >= base")
