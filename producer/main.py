"""Entry point: connects to NATS JetStream and runs one producer per patient.

Baseline mode (no args) is unchanged from the original MVP. Pass --scenario
to overlay a deterministic clinical scenario (data/scenarios/definitions.py)
on every patient, and --signal-seed/--noise-seed for reproducible runs —
required for the benchmark harness and for demoing ground-truth detection
latency live.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import nats

from config.settings import NATS_URL
from data.generators.noise import NoiseConfig, NoiseInjector
from data.scenarios.definitions import SCENARIOS
from producer.mqtt_producer import MqttPublisher
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=None,
                         help="Overlay a deterministic clinical scenario on every patient")
    parser.add_argument("--signal-seed", type=int, default=None,
                         help="Base seed for generator RNGs (reproducible physiological variability)")
    parser.add_argument("--noise-seed", type=int, default=None,
                         help="Seed for transport noise injection")
    parser.add_argument("--packet-loss", type=float, default=0.0)
    parser.add_argument("--spike-probability", type=float, default=0.0)
    parser.add_argument("--dropout-probability", type=float, default=0.0)
    parser.add_argument("--dropout-duration-s", type=float, default=0.0)
    parser.add_argument("--clock-drift-ms", type=int, default=0)
    parser.add_argument("--dual-mqtt", action="store_true",
                         help="Also publish every message to MQTT (Mosquitto) for the NATS-vs-MQTT comparison")
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    profiles = _load_profiles()
    scenario = SCENARIOS[args.scenario] if args.scenario else None

    noise_config = NoiseConfig(
        packet_loss_rate=args.packet_loss,
        spike_probability=args.spike_probability,
        dropout_probability=args.dropout_probability,
        dropout_duration_s=args.dropout_duration_s,
        clock_drift_ms=args.clock_drift_ms,
    )

    if scenario:
        log.info("Scenario active: %s (%s)", scenario.scenario_id, scenario.description)

    log.info("Connecting to NATS at %s", NATS_URL)
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()

    mqtt_publisher = None
    if args.dual_mqtt:
        log.info("Dual-publishing to MQTT at %s:%d", args.mqtt_host, args.mqtt_port)
        mqtt_publisher = MqttPublisher(args.mqtt_host, args.mqtt_port)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        log.info("Shutdown signal received — stopping producers.")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    producers = [
        PatientProducer(
            profile, js,
            signal_seed=None if args.signal_seed is None else args.signal_seed + i * 100,
            noise_injector=NoiseInjector(noise_config, None if args.noise_seed is None else args.noise_seed + i),
            scenario=scenario,
            mqtt=mqtt_publisher,
        )
        for i, profile in enumerate(profiles)
    ]
    tasks = [asyncio.create_task(p.run(), name=p.patient_id) for p in producers]

    log.info("Publishing vitals for %d patients. Press Ctrl+C to stop.", len(producers))

    await stop_event.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await nc.drain()
    if mqtt_publisher is not None:
        mqtt_publisher.close()
    log.info("NATS connection closed. Bye.")


if __name__ == "__main__":
    asyncio.run(main())
