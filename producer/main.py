"""Entry point: connects to NATS JetStream and runs one producer per patient."""

import asyncio
import glob
import json
import logging
import signal
import sys
from pathlib import Path

import nats

from config.settings import NATS_URL
from producer.patient_producer import PatientProducer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"


def _load_profiles() -> list[dict]:
    paths = sorted(PROFILES_DIR.glob("P-*.json"))
    if not paths:
        log.error("No patient profiles found in %s", PROFILES_DIR)
        sys.exit(1)
    profiles = [json.loads(p.read_text()) for p in paths]
    log.info("Loaded %d patient profiles: %s", len(profiles),
             [p["patient_id"] for p in profiles])
    return profiles


async def main() -> None:
    profiles = _load_profiles()

    log.info("Connecting to NATS at %s", NATS_URL)
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal received — stopping producers.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    producers = [PatientProducer(profile, js) for profile in profiles]
    tasks = [asyncio.create_task(p.run(), name=p.patient_id) for p in producers]

    log.info("Publishing vitals for %d patients. Press Ctrl+C to stop.", len(producers))

    await stop_event.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await nc.drain()
    log.info("NATS connection closed. Bye.")


if __name__ == "__main__":
    asyncio.run(main())
