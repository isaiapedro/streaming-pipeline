import os

from dotenv import load_dotenv

load_dotenv()

# NATS JetStream
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")

# InfluxDB Cloud — no hardcoded default. Real values live in `.env`
# (gitignored, not committed) — see `.env` for setup instructions.
INFLUX_URL    = os.getenv("INFLUX_URL")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN")
INFLUX_ORG    = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

# Brain flush settings
FLUSH_INTERVAL_S  = 1      # seconds between buffer flushes
FLUSH_BUFFER_SIZE = 500    # flush early if buffer reaches this many records
