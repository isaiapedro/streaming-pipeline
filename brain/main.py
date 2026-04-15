"""Brain service entry point.

Subscribes to all vitals subjects on NATS JetStream, evaluates thresholds,
and writes batched records to InfluxDB Cloud.
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import nats
from nats.errors import TimeoutError as NatsTimeout

from config.settings import NATS_URL
from brain.evaluator import evaluate_message
from brain.influx_writer import InfluxWriter, VitalRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"
_PULL_BATCH   = 50
_PULL_TIMEOUT = 1.0   # seconds


def _load_condition_map() -> dict[str, str]:
    """Returns {patient_id: condition} from all profile JSONs."""
    mapping = {}
    for path in sorted(PROFILES_DIR.glob("P-*.json")):
        p = json.loads(path.read_text())
        mapping[p["patient_id"]] = p["condition"]
    if not mapping:
        log.error("No patient profiles found in %s", PROFILES_DIR)
        sys.exit(1)
    log.info("Condition map loaded: %s", mapping)
    return mapping


async def _process(msg, condition_map: dict, writer: InfluxWriter) -> None:
    try:
        data = json.loads(msg.data)
    except json.JSONDecodeError as exc:
        log.warning("Bad JSON on subject %s: %s", msg.subject, exc)
        await msg.ack()
        return

    patient_id  = data.get("patient_id", "unknown")
    signal_type = data.get("signal_type", "unknown")
    value       = data.get("value")
    timestamp   = data.get("timestamp", 0)
    condition   = condition_map.get(patient_id, "unknown")

    readings = evaluate_message(signal_type, value)
    for sig, float_val, alarm_level in readings:
        if alarm_level != "ok":
            log.info("[%s] %s=%s → %s", patient_id, sig, float_val, alarm_level.upper())
        await writer.enqueue(VitalRecord(
            patient_id=patient_id,
            signal_type=sig,
            condition=condition,
            alarm_level=alarm_level,
            value=float_val,
            timestamp_ms=timestamp,
        ))

    await msg.ack()


async def main() -> None:
    condition_map = _load_condition_map()

    writer = InfluxWriter()
    await writer.start()

    log.info("Connecting to NATS at %s", NATS_URL)
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    # Durable pull consumer — survives brain restarts, picks up where it left off
    sub = await js.pull_subscribe("vitals.>", durable="BRAIN", stream="VITALS")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal — draining brain service.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log.info("Brain service running. Waiting for vitals messages…")
    processed = 0

    while not stop_event.is_set():
        try:
            msgs = await sub.fetch(_PULL_BATCH, timeout=_PULL_TIMEOUT)
        except NatsTimeout:
            continue
        except Exception as exc:
            log.error("fetch error: %s", exc)
            await asyncio.sleep(1)
            continue

        for msg in msgs:
            await _process(msg, condition_map, writer)
            processed += 1

    log.info("Processed %d messages total. Shutting down.", processed)
    await writer.stop()
    try:
        await asyncio.wait_for(nc.drain(), timeout=5.0)
    except Exception:
        await nc.close()
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
