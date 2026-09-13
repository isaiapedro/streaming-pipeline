"""Atomic, versioned configuration for Approach A alarm thresholds."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


_DEFAULT_THRESHOLDS = {
    "heart_rate": {
        "warning_high": 100,
        "critical_high": 120,
        "warning_low": 50,
        "critical_low": 40,
    },
    "spo2": {"warning_low": 94, "critical_low": 90},
    "systolic_bp": {
        "warning_high": 140,
        "critical_high": 180,
        "warning_low": 90,
    },
    "respiratory_rate": {
        "warning_high": 20,
        "critical_high": 30,
        "warning_low": 10,
    },
    "temperature": {
        "warning_high": 37.5,
        "critical_high": 38.5,
        "warning_low": 36.0,
    },
}


@dataclass(frozen=True)
class ThresholdSnapshot:
    """One immutable threshold set and the label derived from its content."""

    values: Mapping[str, Mapping[str, float]]
    version: str


def threshold_version(values: Mapping[str, Mapping[str, float]]) -> str:
    normalized = {
        signal_name: {band_name: float(value) for band_name, value in bands.items()}
        for signal_name, bands in values.items()
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


def _freeze(values: Mapping[str, Mapping[str, float]]) -> Mapping[str, Mapping[str, float]]:
    if not values:
        raise ValueError("threshold configuration cannot be empty")
    frozen: dict[str, Mapping[str, float]] = {}
    for signal_name, bands in values.items():
        if not isinstance(signal_name, str) or not signal_name or not isinstance(bands, Mapping):
            raise ValueError("threshold configuration has an invalid signal entry")
        numeric_bands: dict[str, float] = {}
        for band_name, value in bands.items():
            if band_name not in {"warning_high", "critical_high", "warning_low", "critical_low"}:
                raise ValueError(f"unsupported threshold band: {band_name}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"threshold {signal_name}.{band_name} must be numeric")
            numeric_bands[band_name] = float(value)
        frozen[signal_name] = MappingProxyType(numeric_bands)
    return MappingProxyType(frozen)


def _make_snapshot(
    values: Mapping[str, Mapping[str, float]], version: str | None = None,
) -> ThresholdSnapshot:
    frozen = _freeze(values)
    computed = threshold_version({name: dict(bands) for name, bands in frozen.items()})
    if version is not None and version != computed:
        raise ValueError("threshold version does not match threshold content")
    return ThresholdSnapshot(values=frozen, version=computed)


_snapshot = _make_snapshot(_DEFAULT_THRESHOLDS)

# Compatibility view for scripts that only need the current values. Runtime
# scoring captures get_threshold_snapshot() once so values and version cannot
# come from different hot-reload revisions.
SIGNAL_THRESHOLDS = _snapshot.values


def get_threshold_snapshot() -> ThresholdSnapshot:
    return _snapshot


def install_thresholds(
    values: Mapping[str, Mapping[str, float]], version: str | None = None,
) -> ThresholdSnapshot:
    """Validate first, then atomically replace the process-wide snapshot."""

    next_snapshot = _make_snapshot(values, version)
    global _snapshot, SIGNAL_THRESHOLDS
    _snapshot = next_snapshot
    SIGNAL_THRESHOLDS = next_snapshot.values
    return next_snapshot


NEWS2_THRESHOLD_VERSION = "news2-2017-room-air-v1"
