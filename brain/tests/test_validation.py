import time

import pytest

from brain.validation import (
    ValidationError,
    dead_letter,
    dead_letter_message_id,
    nats_dead_letter_message_id,
    decode_and_validate,
)
from schema import vitals_pb2

PROFILES = {"P-001": {"patient_id": "P-001"}}
NOW = 1_800_000_000_000


def _vital(**overrides):
    message = vitals_pb2.VitalSign(
        patient_id="P-001", signal_type="heart_rate", scalar_value=80,
        timestamp_ms=NOW, schema_version="1", pipeline_version="test",
    )
    for name, value in overrides.items():
        setattr(message, name, value)
    return message.SerializeToString()


def test_valid_scalar_round_trip_preserves_metadata():
    vital = decode_and_validate(
        _vital(), PROFILES, now_ms=NOW, source_subject="vitals.P-001.heart_rate"
    )
    assert vital.value == 80
    assert vital.schema_version == "1"
    assert vital.pipeline_version == "test"


@pytest.mark.parametrize("subject, reason", [
    ("vitals.P-404.heart_rate", "subject_patient_mismatch"),
    ("vitals.P-001.spo2", "subject_signal_mismatch"),
    ("unexpected.P-001.heart_rate", "invalid_source_subject"),
    ("vitals.P-001", "invalid_source_subject"),
])
def test_rejects_subject_payload_identity_mismatch(subject, reason):
    with pytest.raises(ValidationError, match=reason):
        decode_and_validate(_vital(), PROFILES, now_ms=NOW, source_subject=subject)


@pytest.mark.parametrize("raw, reason", [
    (b"not protobuf", "malformed_protobuf"),
    (_vital(patient_id="P-404"), "unknown_or_missing_patient_id"),
    (_vital(signal_type="ecg"), "unknown_or_missing_signal_type"),
    (_vital(schema_version="2"), "unsupported_schema_version"),
    (_vital(timestamp_ms=0), "invalid_timestamp"),
])
def test_rejects_invalid_structure(raw, reason):
    with pytest.raises(ValidationError, match=reason):
        decode_and_validate(raw, PROFILES, now_ms=NOW)


def test_rejects_wrong_value_shape_and_invalid_blood_pressure():
    wrong_shape = vitals_pb2.VitalSign(patient_id="P-001", signal_type="spo2", timestamp_ms=NOW,
                                        schema_version="1", pipeline_version="test")
    wrong_shape.bp.systolic, wrong_shape.bp.diastolic = 120, 80
    with pytest.raises(ValidationError, match="scalar_signal_requires_scalar_value"):
        decode_and_validate(wrong_shape.SerializeToString(), PROFILES, now_ms=NOW)

    bad_bp = vitals_pb2.VitalSign(patient_id="P-001", signal_type="blood_pressure", timestamp_ms=NOW,
                                  schema_version="1", pipeline_version="test")
    bad_bp.bp.systolic, bad_bp.bp.diastolic = 70, 90
    with pytest.raises(ValidationError, match="systolic_less_than_diastolic"):
        decode_and_validate(bad_bp.SerializeToString(), PROFILES, now_ms=NOW)


def test_dead_letter_preserves_the_invalid_payload():
    raw = b"bad"
    encoded = dead_letter(raw, ValidationError("bad_message"), "vitals.P-001.spo2", pipeline_version="test")
    envelope = vitals_pb2.DeadLetterEnvelope()
    envelope.ParseFromString(encoded)
    assert envelope.original_payload == raw
    assert envelope.source_subject == "vitals.P-001.spo2"


def test_dead_letter_message_id_is_stable_and_input_specific():
    first = dead_letter_message_id(b"bad", "vitals.P-001.spo2")
    assert first == dead_letter_message_id(b"bad", "vitals.P-001.spo2")
    assert first != dead_letter_message_id(b"worse", "vitals.P-001.spo2")
    assert first != dead_letter_message_id(b"bad", "vitals.P-002.spo2")


def test_dead_letter_message_id_distinguishes_distinct_broker_messages():
    first = dead_letter_message_id(
        b"bad", "vitals.P-001.spo2", source_message_id=41
    )
    assert first == dead_letter_message_id(
        b"bad", "vitals.P-001.spo2", source_message_id=41
    )
    assert first != dead_letter_message_id(
        b"bad", "vitals.P-001.spo2", source_message_id=42
    )


def test_nats_dead_letter_id_uses_stable_stream_sequence():
    class Sequence:
        stream = 17

    class Metadata:
        sequence = Sequence()

    class Message:
        subject = "vitals.P-001.spo2"
        data = b"bad"
        metadata = Metadata()

    first = nats_dead_letter_message_id(Message())
    assert first == nats_dead_letter_message_id(Message())
    Message.metadata.sequence.stream = 18
    assert first != nats_dead_letter_message_id(Message())
