import csv

import pytest

from data.generators.noise import NoiseConfig
from data.scenarios.definitions import Scenario
import scripts.run_noise_scoring_experiment as experiment
from scripts.run_noise_scoring_experiment import NoiseCondition


def _results(base: float):
    return {
        approach: {
            "detection_run_rate": 1.0,
            "false_alarm_run_probability": None,
            "scoring_detection_latency_ms": base,
            "alarm_episode_rate_per_patient_day": base,
            "time_in_alarm_pct": base,
            "window_completeness_pct": 100.0 - base,
        }
        for approach in ("A", "B", "C")
    }


def test_default_matrix_covers_declared_loss_and_dropout_factors():
    conditions = experiment.default_conditions()
    assert [condition.noise_profile for condition in conditions].count("clean") == 1
    assert {condition.packet_loss_rate for condition in conditions} == {0.0, 0.01, 0.05, 0.10}
    assert {condition.dropout_duration_s for condition in conditions} == {0, 10, 30, 60}
    assert {"packet_loss", "dropout", "spike", "jitter", "combined"}.issubset(
        {condition.noise_profile for condition in conditions}
    )


def test_noise_condition_rejects_invalid_or_nonclean_clean_profiles():
    with pytest.raises(ValueError, match="packet loss"):
        NoiseCondition("packet_loss", packet_loss_rate=0.02)
    with pytest.raises(ValueError, match="clean profile"):
        NoiseCondition("clean", spike_probability=0.1)
    with pytest.raises(ValueError, match="exactly one clean"):
        experiment.validate_conditions((NoiseCondition("packet_loss", packet_loss_rate=0.01),))


def test_build_rows_pairs_every_condition_and_computes_signed_deltas(monkeypatch):
    scenario = Scenario("short", "test", 2, 0, 0, {}, "none")
    monkeypatch.setattr(experiment, "SCENARIOS", {"short": scenario})

    def fake_simulate(_scenario, _signal_seed, _noise_seed, config, _hold, record):
        degraded = config.packet_loss_rate * 100
        if degraded:
            record.extend([
                {"kind": "dropped", "signal_type": "spo2", "elapsed_ms": 0},
                {"kind": "signal", "signal_type": "spo2", "elapsed_ms": 1_000},
            ])
        return _results(degraded)

    monkeypatch.setattr(experiment, "_simulate_run", fake_simulate)
    conditions = (NoiseCondition("clean"), NoiseCondition("packet_loss", packet_loss_rate=0.05))
    rows = experiment.build_rows((1_000,), (2_000,), conditions, stable_duration_s=2)
    assert len(rows) == 6
    noisy = next(row for row in rows if row["noise_profile"] == "packet_loss" and row["approach"] == "B")
    assert noisy["pair_id"] == next(row["pair_id"] for row in rows if row["noise_profile"] == "clean")
    assert noisy["delta_scoring_detection_latency_ms_vs_clean"] == 5.0
    assert noisy["delta_window_completeness_pct_vs_clean"] == -5.0
    assert noisy["max_observation_recovery_ms"] == 1_000.0
    assert noisy["delta_max_observation_recovery_ms_vs_clean"] == 1_000.0
    assert noisy["delta_false_alarm_run_probability_vs_clean"] is None
    assert all(
        row["delta_scoring_detection_latency_ms_vs_clean"] == 0
        for row in rows if row["noise_profile"] == "clean"
    )


def test_recovery_metric_maps_blood_pressure_message_to_expanded_components():
    record = [
        {"kind": "dropped", "signal_type": "blood_pressure", "elapsed_ms": 1_000},
        {"kind": "signal", "signal_type": "systolic_bp", "elapsed_ms": 4_000},
        {"kind": "signal", "signal_type": "diastolic_bp", "elapsed_ms": 4_000},
    ]
    assert experiment._max_observation_recovery_ms(record, 5_000) == 3_000


def test_rows_are_deterministic_and_csv_preserves_factor_columns(tmp_path, monkeypatch):
    scenario = Scenario("short", "test", 1, 0, 0, {}, "none")
    monkeypatch.setattr(experiment, "SCENARIOS", {"short": scenario})
    monkeypatch.setattr(experiment, "_simulate_run", lambda *args: _results(0.0))
    conditions = (NoiseCondition("clean"), NoiseCondition("jitter", clock_jitter_ms=50))
    first = experiment.build_rows((1,), (2,), conditions, stable_duration_s=1)
    second = experiment.build_rows((1,), (2,), conditions, stable_duration_s=1)
    assert first == second
    output = tmp_path / "noise.csv"
    experiment.write_rows(first, output)
    written = list(csv.DictReader(output.open()))
    assert len(written) == 6
    assert {row["noise_profile"] for row in written} == {"clean", "jitter"}
    assert all(row["experiment_id"] and row["pair_id"] for row in written)


def test_window_completeness_counts_failed_scoring_attempts(monkeypatch):
    scenario = Scenario("short", "test", 1, 0, 0, {}, "none")
    result = __import__("scripts.run_benchmark", fromlist=["_simulate_run"])._simulate_run(
        scenario, 1, 2, NoiseConfig(packet_loss_rate=1.0)
    )
    assert result["B"]["window_completeness_pct"] is None
    assert result["C"]["window_completeness_pct"] is None
