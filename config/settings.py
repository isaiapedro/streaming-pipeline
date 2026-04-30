import os

# NATS JetStream
NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")

# InfluxDB Cloud
INFLUX_URL    = os.getenv("INFLUX_URL", "https://us-east-1-1.aws.cloud2.influxdata.com")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN", "wsK393AFgn1J7Kawi5tFKBC1IBNl_PWW4L5xXiPC6kAJ_gfRUXFG7z2_ZTqmHn10qAluGk4GetcuBT5gmA0_kw==")
INFLUX_ORG    = os.getenv("INFLUX_ORG", "personal")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "vitals")

# Brain flush settings
FLUSH_INTERVAL_S  = 1      # seconds between buffer flushes
FLUSH_BUFFER_SIZE = 500    # flush early if buffer reaches this many records
