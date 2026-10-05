#!/usr/bin/env python3
"""Run paired clean/noise/dropout experiments over the A/B/C scorers.

Each non-clean cell is paired to a clean cell with the same scenario, signal
seed, noise seed, and scoring approach. Output rows include raw measurements
and signed deltas (condition minus clean), making infrastructure degradation
effects directly measurable without conflating physiological randomness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.generators.noise import NoiseConfig
from data.scenarios.definitions import SCENARIOS
from scripts.run_benchmark import (
    APPROACHES,
    DEFAULT_CLEAR_HOLD_MS,
    DEFAULT_NOISE_SEEDS,
    DEFAULT_SIGNAL_SEEDS,
    _simulate_run,
    scenario_for_benchmark,
)

LOSS_LEVELS = (0.00, 0.01, 0.05, 0.10)
DROPOUT_DURATIONS_S = (0, 10, 30, 60)
EFFECT_METRICS = (
    "detection_run_rate",
    "false_alarm_run_probability",
    "scoring_detection_latency_ms",
    "alarm_episode_rate_per_patient_day",
    "time_in_alarm_pct",
    "window_completeness_pct",
    "max_observation_recovery_ms",
)
RESULT_FIELDS = (
    "experiment_id", "pair_id", "scenario", "signal_seed", "noise_seed", "approach",
    "noise_profile", "packet_loss_rate", "dropout_duration_s", "dropout_probability",
    "spike_probability", "clock_jitter_ms", "duration_s",
    *EFFECT_METRICS,
    *(f"delta_{metric}_vs_clean" for metric in EFFECT_METRICS),
)


@dataclass(frozen=True)
class NoiseCondition:
    noise_profile: str
    packet_loss_rate: float = 0.0
    dropout_duration_s: int = 0
    dropout_probability: float = 0.0
    spike_probability: float = 0.0
    clock_jitter_ms: int = 0

    def __post_init__(self) -> None:
        if self.noise_profile not in {"clean", "packet_loss", "dropout", "spike", "jitter", "combined"}:
            raise ValueError(f"unknown noise profile: {self.noise_profile}")
        if self.packet_loss_rate not in LOSS_LEVELS:
            raise ValueError(f"packet loss must be one of {LOSS_LEVELS}")
        if self.dropout_duration_s not in DROPOUT_DURATIONS_S:
            raise ValueError(f"dropout duration must be one of {DROPOUT_DURATIONS_S}")
        for name, value in (("dropout_probability", self.dropout_probability), ("spike_probability", self.spike_probability)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if self.clock_jitter_ms < 0:
            raise ValueError("clock jitter must not be negative")
        if self.noise_profile == "clean" and any(asdict(self)[key] for key in asdict(self) if key != "noise_profile"):
            raise ValueError("clean profile cannot enable degradation")

    def config(self) -> NoiseConfig:
        return NoiseConfig(
            packet_loss_rate=self.packet_loss_rate,
            spike_probability=self.spike_probability,
            dropout_probability=self.dropout_probability,
            dropout_duration_s=self.dropout_duration_s,
            clock_drift_ms=self.clock_jitter_ms,
        )


def default_conditions() -> tuple[NoiseCondition, ...]:
    """Return the declared factor matrix, including one unique clean control."""

    conditions = [NoiseCondition("clean")]
    conditions.extend(NoiseCondition("packet_loss", packet_loss_rate=loss) for loss in LOSS_LEVELS[1:])
    conditions.extend(
        NoiseCondition("dropout", dropout_duration_s=duration, dropout_probability=0.005)
        for duration in DROPOUT_DURATIONS_S[1:]
    )
    conditions.extend((NoiseCondition("spike", spike_probability=0.005), NoiseCondition("jitter", clock_jitter_ms=50)))
    conditions.extend(
        NoiseCondition(
            "combined", packet_loss_rate=loss, dropout_duration_s=duration,
            dropout_probability=0.005, spike_probability=0.005, clock_jitter_ms=50,
        )
        for loss in LOSS_LEVELS[1:]
        for duration in DROPOUT_DURATIONS_S[1:]
    )
    return tuple(conditions)


def _condition_key(condition: NoiseCondition) -> str:
    return json.dumps(asdict(condition), sort_keys=True, separators=(",", ":"))


def _identifier(prefix: str, *parts: object) -> str:
    material = ":".join((prefix, *(str(part) for part in parts))).encode()
    return hashlib.sha256(material).hexdigest()[:16]


def _max_observation_recovery_ms(record: list[dict], _duration_ms: int) -> float:
    """Longest observable missing interval that subsequently recovered.

    Right-censored gaps still active at the end of a run are intentionally not
    reported as recovery. The metric is transport-observation availability,
    shared by all approaches within the paired cell.
    """

    gap_started: dict[str, int] = {}
    recoveries: list[int] = []
    for item in record:
        signal = item.get("signal_type")
        # The simulator emits blood-pressure drops at the source-message level
        # but expands retained messages into their two scored components.
        recovery_signal = "blood_pressure" if signal in {"systolic_bp", "diastolic_bp"} else signal
        if item.get("kind") == "dropped":
            gap_started.setdefault(signal, int(item["elapsed_ms"]))
        elif item.get("kind") == "signal" and recovery_signal in gap_started:
            recoveries.append(max(0, int(item["elapsed_ms"]) - gap_started.pop(recovery_signal)))
    return float(max(recoveries, default=0))


def validate_conditions(conditions: tuple[NoiseCondition, ...]) -> None:
    if not conditions:
        raise ValueError("at least one noise condition is required")
    keys = [_condition_key(condition) for condition in conditions]
    if len(keys) != len(set(keys)):
        raise ValueError("noise conditions must be unique")
    clean = [condition for condition in conditions if condition.noise_profile == "clean"]
    if len(clean) != 1:
        raise ValueError("exactly one clean condition is required for paired deltas")


def build_rows(
    signal_seeds: tuple[int, ...] = DEFAULT_SIGNAL_SEEDS,
    noise_seeds: tuple[int, ...] = DEFAULT_NOISE_SEEDS,
    conditions: tuple[NoiseCondition, ...] | None = None,
    stable_duration_s: int = 86_400,
    clear_hold_ms: int = DEFAULT_CLEAR_HOLD_MS,
) -> list[dict]:
    conditions = conditions or default_conditions()
    validate_conditions(conditions)
    if not signal_seeds or not noise_seeds or len(set(signal_seeds)) != len(signal_seeds) or len(set(noise_seeds)) != len(noise_seeds):
        raise ValueError("signal and noise seeds must be non-empty and unique")

    rows: list[dict] = []
    for original in SCENARIOS.values():
        scenario = scenario_for_benchmark(original, stable_duration_s)
        for signal_seed in signal_seeds:
            for noise_seed in noise_seeds:
                pair_id = _identifier("noise-pair-v1", scenario.scenario_id, signal_seed, noise_seed)
                cell_results: dict[str, tuple[dict[str, dict], float]] = {}
                for condition in conditions:
                    record: list[dict] = []
                    results = _simulate_run(
                        scenario, signal_seed, noise_seed, condition.config(), clear_hold_ms, record
                    )
                    recovery = _max_observation_recovery_ms(record, int(scenario.duration_s * 1_000))
                    cell_results[_condition_key(condition)] = (results, recovery)

                clean_condition = next(condition for condition in conditions if condition.noise_profile == "clean")
                clean_results, clean_recovery = cell_results[_condition_key(clean_condition)]
                for condition in conditions:
                    results, recovery = cell_results[_condition_key(condition)]
                    for approach in APPROACHES:
                        metrics = {metric: results[approach].get(metric) for metric in EFFECT_METRICS}
                        metrics["max_observation_recovery_ms"] = recovery
                        clean_metrics = {metric: clean_results[approach].get(metric) for metric in EFFECT_METRICS}
                        clean_metrics["max_observation_recovery_ms"] = clean_recovery
                        deltas = {
                            f"delta_{metric}_vs_clean": (
                                metrics[metric] - clean_metrics[metric]
                                if metrics[metric] is not None and clean_metrics[metric] is not None else None
                            )
                            for metric in EFFECT_METRICS
                        }
                        rows.append({
                            "experiment_id": _identifier("noise-cell-v1", pair_id, _condition_key(condition), approach),
                            "pair_id": pair_id,
                            "scenario": scenario.scenario_id,
                            "signal_seed": signal_seed,
                            "noise_seed": noise_seed,
                            "approach": approach,
                            **asdict(condition),
                            "duration_s": scenario.duration_s,
                            **metrics,
                            **deltas,
                        })
    validate_rows(rows, conditions, signal_seeds, noise_seeds)
    return rows


def validate_rows(rows: list[dict], conditions: tuple[NoiseCondition, ...], signal_seeds: tuple[int, ...], noise_seeds: tuple[int, ...]) -> None:
    expected = len(SCENARIOS) * len(signal_seeds) * len(noise_seeds) * len(conditions) * len(APPROACHES)
    if len(rows) != expected:
        raise ValueError(f"expected {expected} rows, found {len(rows)}")
    ids = [row["experiment_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("experiment IDs are not unique")
    for row in rows:
        for metric in EFFECT_METRICS:
            value = row[metric]
            delta = row[f"delta_{metric}_vs_clean"]
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"non-finite {metric}")
            if delta is not None and not math.isfinite(float(delta)):
                raise ValueError(f"non-finite delta for {metric}")
            if row["noise_profile"] == "clean" and delta not in (None, 0, 0.0):
                raise ValueError("clean-control deltas must be zero or unavailable")


def write_rows(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows({key: "" if value is None else value for key, value in row.items()} for row in rows)
    temporary.replace(path)


def _seeds(count: int, multiplier: int) -> tuple[int, ...]:
    if count < 1:
        raise argparse.ArgumentTypeError("seed count must be positive")
    return tuple(multiplier * index for index in range(1, count + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-seeds", type=int, default=5)
    parser.add_argument("--noise-seeds", type=int, default=5)
    parser.add_argument("--stable-duration-s", type=int, default=86_400)
    parser.add_argument("--clear-hold-ms", type=int, default=DEFAULT_CLEAR_HOLD_MS)
    parser.add_argument("--out", type=Path, default=Path("evidence/noise_scoring_experiment.csv"))
    arguments = parser.parse_args()
    experiment_rows = build_rows(
        _seeds(arguments.signal_seeds, 1_000), _seeds(arguments.noise_seeds, 2_000),
        stable_duration_s=arguments.stable_duration_s, clear_hold_ms=arguments.clear_hold_ms,
    )
    write_rows(experiment_rows, arguments.out)
    print(f"Wrote {len(experiment_rows)} paired noise-scoring rows to {arguments.out}")
