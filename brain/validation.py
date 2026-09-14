"""Wire decoding and structural validation for every vital-sign consumer."""

from __future__ import annotations

import math
import time
from hashlib import sha256
from dataclasses import dataclass

from google.protobuf.message import DecodeError

from schema import vitals_pb2

SUPPORTED_SCHEMA_VERSION = "1"
DLQ_SUBJECT = "dlq.vitals.nats"
_MAX_FUTURE_MS = 5 * 60 * 1000
_RANGES = {
    "heart_rate": (0.0, 300.0),
    "spo2": (0.0, 100.0),
    "respiratory_rate": (0.0, 100.0),
    "temperature": (25.0, 45.0),
    "blood_pressure": (0.0, 300.0),
}
_SCALAR_SIGNALS = {"heart_rate", "spo2", "respiratory_rate", "temperature"}


class ValidationError(ValueError):
    """A payload was decoded but cannot safely enter clinical scoring."""


@dataclass(frozen=True)
class ValidVital:
    patient_id: str
    signal_type: str
    value: float | dict[str, float]
    timestamp_ms: int
    schema_version: str
    pipeline_version: str
    scenario_id: str
    onset_offset_ms: int


def decode_and_validate(
    raw: bytes,
    profiles: dict[str, dict],
    *,
    now_ms: int | None = None,
    source_subject: str | None = None,
) -> ValidVital:
    message = vitals_pb2.VitalSign()
    try:
        message.ParseFromString(raw)
    except DecodeError as exc:
        raise ValidationError(f"malformed_protobuf: {exc}") from exc

    if not message.patient_id or message.patient_id not in profiles:
        raise ValidationError("unknown_or_missing_patient_id")
    if message.signal_type not in _SCALAR_SIGNALS | {"blood_pressure"}:
        raise ValidationError("unknown_or_missing_signal_type")
    if message.schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ValidationError("unsupported_schema_version")
    if not message.pipeline_version:
        raise ValidationError("missing_pipeline_version")
    if message.timestamp_ms <= 0:
        raise ValidationError("invalid_timestamp")
    reference_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if message.timestamp_ms > reference_ms + _MAX_FUTURE_MS:
        raise ValidationError("timestamp_too_far_in_future")
    if source_subject is not None:
        _validate_source_subject(source_subject, message.patient_id, message.signal_type)

    value_kind = message.WhichOneof("value")
    if message.signal_type in _SCALAR_SIGNALS:
        if value_kind != "scalar_value":
            raise ValidationError("scalar_signal_requires_scalar_value")
        value = float(message.scalar_value)
        _validate_number(message.signal_type, value)
    else:
        if value_kind != "bp":
            raise ValidationError("blood_pressure_requires_bp_value")
        if not message.bp.HasField("systolic") or not message.bp.HasField("diastolic"):
            raise ValidationError("blood_pressure_requires_both_components")
        systolic, diastolic = float(message.bp.systolic), float(message.bp.diastolic)
        _validate_number("blood_pressure", systolic)
        _validate_number("blood_pressure", diastolic)
        if systolic < diastolic:
            raise ValidationError("systolic_less_than_diastolic")
        value = {"systolic": systolic, "diastolic": diastolic}

    return ValidVital(
        patient_id=message.patient_id,
        signal_type=message.signal_type,
        value=value,
        timestamp_ms=message.timestamp_ms,
        schema_version=message.schema_version,
        pipeline_version=message.pipeline_version,
        scenario_id=message.scenario_id or "none",
        onset_offset_ms=message.onset_offset_ms,
    )


def _validate_source_subject(source_subject: str, patient_id: str, signal_type: str) -> None:
    parts = source_subject.split(".")
    if len(parts) != 3 or parts[0] != "vitals":
        raise ValidationError("invalid_source_subject")
    if parts[1] != patient_id:
        raise ValidationError("subject_patient_mismatch")
    if parts[2] != signal_type:
        raise ValidationError("subject_signal_mismatch")


def _validate_number(signal_type: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValidationError("non_finite_value")
    low, high = _RANGES[signal_type]
    if not low <= value <= high:
        raise ValidationError(f"value_out_of_range:{signal_type}")


def dead_letter(
    raw: bytes,
    error: Exception,
    source_subject: str,
    *,
    pipeline_version: str,
    source_transport: str = "nats",
    source_topic: str = "",
    source_partition: int = 0,
    source_offset: int = 0,
    source_timestamp_ms: int = 0,
) -> bytes:
    envelope = vitals_pb2.DeadLetterEnvelope(
        original_payload=raw,
        error_type=type(error).__name__,
        error_message=str(error),
        source_subject=source_subject,
        rejected_at_ms=int(time.time() * 1000),
        schema_version=SUPPORTED_SCHEMA_VERSION,
        pipeline_version=pipeline_version,
        source_transport=source_transport,
        source_topic=source_topic,
        source_partition=source_partition,
        source_offset=source_offset,
        source_timestamp_ms=source_timestamp_ms,
    )
    return envelope.SerializeToString()


def dead_letter_message_id(
    raw: bytes,
    source_subject: str,
    *,
    source_message_id: str | int | None = None,
) -> str:
    """Return a stable de-duplication ID for one rejected source message.

    A broker identity keeps redelivery of the same message idempotent without
    collapsing two distinct publications that happen to have identical bytes.
    Callers without a broker identity retain the content-derived fallback.
    """

    material = source_subject.encode() + b"\0"
    if source_message_id is not None:
        material += str(source_message_id).encode() + b"\0"
    digest = sha256(material + raw).hexdigest()
    return f"dlq:{digest}"


def nats_dead_letter_message_id(msg) -> str:
    """Bind a rejection ID to JetStream's stable source stream sequence."""

    try:
        source_sequence = msg.metadata.sequence.stream
    except (AttributeError, TypeError, ValueError):
        source_sequence = None
    return dead_letter_message_id(
        msg.data,
        msg.subject,
        source_message_id=source_sequence,
    )
