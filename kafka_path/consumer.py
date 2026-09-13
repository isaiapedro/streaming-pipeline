"""CLI validator for the isolated Kafka/Schema Registry comparison path."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain.validation import ValidVital
from kafka_path.settings import KafkaSettings
from kafka_path.transport import KafkaVitalConsumer


PROFILES_DIR = Path(__file__).parents[1] / "data" / "profiles"


def _profiles() -> dict[str, dict]:
    return {
        profile["patient_id"]: profile
        for profile in (json.loads(path.read_text()) for path in PROFILES_DIR.glob("P-*.json"))
    }


def _print_vital(vital: ValidVital) -> None:
    print(
        json.dumps(
            {
                "patient_id": vital.patient_id,
                "signal_type": vital.signal_type,
                "timestamp_ms": vital.timestamp_ms,
                "schema_version": vital.schema_version,
                "pipeline_version": vital.pipeline_version,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-messages", type=int, default=0, help="0 means run until interrupted")
    args = parser.parse_args()

    consumer = KafkaVitalConsumer(_profiles(), KafkaSettings.from_env())
    consumer.start()
    processed = 0
    try:
        while not args.max_messages or processed < args.max_messages:
            if consumer.poll_once(_print_vital):
                processed += 1
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
