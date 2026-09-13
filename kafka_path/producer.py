"""CLI publisher for the isolated Kafka/Schema Registry comparison path."""

from __future__ import annotations

import argparse
import time

from config.settings import PIPELINE_VERSION, SCHEMA_VERSION
from kafka_path.settings import KafkaSettings
from kafka_path.transport import KafkaVitalProducer
from schema import vitals_pb2


def _message(args: argparse.Namespace, timestamp_ms: int) -> vitals_pb2.VitalSign:
    message = vitals_pb2.VitalSign(
        patient_id=args.patient_id,
        signal_type=args.signal_type,
        timestamp_ms=timestamp_ms,
        schema_version=SCHEMA_VERSION,
        pipeline_version=PIPELINE_VERSION,
        scenario_id=args.scenario_id,
    )
    if args.signal_type == "blood_pressure":
        message.bp.systolic = args.value
        message.bp.diastolic = args.diastolic
    else:
        message.scalar_value = args.value
    return message


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient-id", default="P-001")
    parser.add_argument(
        "--signal-type",
        choices=("heart_rate", "spo2", "blood_pressure", "respiratory_rate", "temperature"),
        default="heart_rate",
    )
    parser.add_argument("--value", type=float, default=80.0)
    parser.add_argument("--diastolic", type=float, default=80.0)
    parser.add_argument("--scenario-id", default="kafka_smoke")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    producer = KafkaVitalProducer(KafkaSettings.from_env())
    producer.start()
    for _ in range(args.count):
        producer.publish(_message(args, int(time.time() * 1000)))


if __name__ == "__main__":
    main()
