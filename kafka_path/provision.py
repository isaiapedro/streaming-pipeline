"""Provision Schema Registry subjects and verify the evolution policy."""

from __future__ import annotations

import argparse
from pathlib import Path

from confluent_kafka.schema_registry import Schema

from kafka_path.settings import KafkaSettings
from kafka_path.transport import KafkaCodec
from schema import vitals_pb2


EVOLUTION_DIR = Path(__file__).parents[1] / "schema" / "evolution"


def provision(settings: KafkaSettings, *, verify_evolution: bool = True) -> dict[str, object]:
    codec = KafkaCodec(settings, auto_register=True)
    codec.set_compatibility()
    codec.encode_vital(
        vitals_pb2.VitalSign(
            patient_id="P-SCHEMA",
            signal_type="heart_rate",
            scalar_value=80,
            timestamp_ms=1,
            schema_version="1",
            pipeline_version="schema-provisioning",
        )
    )
    codec.encode_dlq(
        vitals_pb2.DeadLetterEnvelope(
            original_payload=b"schema-provisioning",
            error_type="SchemaProvisioning",
            error_message="registration-only",
            source_subject="schema-provisioning",
            rejected_at_ms=1,
            schema_version="1",
            pipeline_version="schema-provisioning",
            source_transport="kafka",
            source_topic=settings.vitals_topic,
        )
    )
    codec.assert_compatibility()

    result: dict[str, object] = {
        "compatibility": settings.compatibility,
        "vitals_subject": settings.vitals_subject,
        "dlq_subject": settings.dlq_subject,
    }
    if verify_evolution:
        compatible = Schema(
            (EVOLUTION_DIR / "vitals_compatible.proto").read_text(),
            schema_type="PROTOBUF",
        )
        incompatible = Schema(
            (EVOLUTION_DIR / "vitals_incompatible.proto").read_text(),
            schema_type="PROTOBUF",
        )
        compatible_ok = codec.registry.test_compatibility_all_versions(
            settings.vitals_subject,
            compatible,
            normalize=True,
        )
        incompatible_ok = codec.registry.test_compatibility_all_versions(
            settings.vitals_subject,
            incompatible,
            normalize=True,
        )
        if not compatible_ok:
            raise RuntimeError("Additive Protobuf evolution was unexpectedly rejected")
        if incompatible_ok:
            raise RuntimeError("Field-type-changing Protobuf evolution was unexpectedly accepted")
        result.update(compatible_candidate=True, incompatible_candidate=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-evolution-check", action="store_true")
    args = parser.parse_args()
    result = provision(KafkaSettings.from_env(), verify_evolution=not args.skip_evolution_check)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
