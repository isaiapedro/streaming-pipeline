#!/usr/bin/env python3
"""Benchmark harness — runs approaches A/B/C over the 6-scenario suite,
each x10 (signal_seed, noise_seed) pairs, and emits a CSV of thesis metrics.

This is an in-process simulation (no live NATS/InfluxDB) — it re-uses the
same generators, scenario trajectories, noise model, and scoring modules as
the live pipeline, so results are representative of the real scoring logic
while being fast/deterministic to iterate on. `p99_pipeline_latency_ms` is
left blank here — that is a live-pipeline metric, measured separately by
running `producer/main.py --scenario ... ` against a real NATS+InfluxDB
deployment (see plan-detailed.md L9), not by this offline harness.

Usage:
    python scripts/run_benchmark.py [--runs 10] [--out benchmark_results.csv]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.generators.heart_rate import HeartRateGenerator
from data.generators.spo2 import SpO2Generator
from data.generators.blood_pressure import BloodPressureGenerator
from data.generators.respiratory_rate import RespiratoryRateGenerator
from data.generators.temperature import TemperatureGenerator
from data.generators.correlation import correlated_delta
from data.generators.noise import NoiseConfig, NoiseInjector
from data.scenarios.definitions import SCENARIOS, Scenario
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from brain.approaches import APPROACH_A, APPROACH_B, APPROACH_C, BatchScheduler, score_composite

TICK_MS = 1000  # simulation resolution — finer than any scenario's ramp/onset timing

# Representative baseline patient for the benchmark (fixed across all runs
# and approaches — only signal_seed/noise_seed vary; see plan-detailed.md
# "fair comparison rule").
_BASE_PROFILE = {
    "patient_id": "BENCH-01",
    "condition": "benchmark",
    "baselines": {
        "heart_rate":       {"mean": 75,  "std": 8},
        "spo2":             {"mean": 97,  "std": 1.0},
        "systolic_bp":      {"mean": 120, "std": 10},
        "diastolic_bp":     {"mean": 78,  "std": 8},
        "respiratory_rate": {"mean": 16,  "std": 2},
        "temperature":      {"mean": 36.8, "std": 0.2},
    },
    "copd_flag": False,
}

_BP_SUB_KEYS = {"systolic_bp": "systolic", "diastolic_bp": "diastolic"}


def _simulate_run(
    scenario: Scenario, signal_seed: int, noise_seed: int, noise_config: NoiseConfig,
    record: list | None = None,
) -> dict:
    """Run one (scenario, seed pair) simulation for all 3 approaches concurrently.

    Returns per-approach metrics dict. If `record` is a list, every raw
    signal reading and every composite score (B/C) is appended to it as a
    dict row — used by the visualization notebook to reconstruct full
    timeseries without duplicating this simulation logic.
    """
    copd_flag = scenario.copd_flag_override if scenario.copd_flag_override is not None else False
    profile = dict(_BASE_PROFILE, copd_flag=copd_flag)

    generators = {
        "heart_rate":       HeartRateGenerator(profile, signal_seed + 0),
        "spo2":             SpO2Generator(profile, signal_seed + 1),
        "blood_pressure":   BloodPressureGenerator(profile, signal_seed + 2),
        "respiratory_rate": RespiratoryRateGenerator(profile, signal_seed + 3),
        "temperature":      TemperatureGenerator(profile, signal_seed + 4),
    }
    noise = NoiseInjector(noise_config, noise_seed)

    ews_state = PatientEWSState("BENCH-01", copd_flag=copd_flag)
    batch_scheduler = BatchScheduler()

    alarms = {APPROACH_A: [], APPROACH_B: [], APPROACH_C: []}  # list of timestamps (ms)
    latest: dict[str, float] = {}

    duration_ms = int(scenario.duration_s * 1000)
    for elapsed_ms in range(0, duration_ms, TICK_MS):
        deltas = scenario.delta_at(elapsed_ms)

        for signal_type, gen in generators.items():
            raw_value = gen.generate(elapsed_ms)

            if signal_type == "blood_pressure":
                value = dict(raw_value)
                for flat_key, sub_key in _BP_SUB_KEYS.items():
                    value[sub_key] += deltas.get(flat_key, 0.0)
            else:
                delta = deltas.get(signal_type, 0.0)
                delta += correlated_delta(signal_type, latest, profile["baselines"], copd_flag)
                value = raw_value + delta

            if signal_type == "blood_pressure":
                latest["systolic_bp"] = value["systolic"]
                latest["diastolic_bp"] = value["diastolic"]
            else:
                latest[signal_type] = value

            noisy_value, noisy_ts = noise.apply(signal_type, value, elapsed_ms)
            if noisy_value is None:
                if record is not None:
                    record.append({"elapsed_ms": elapsed_ms, "kind": "dropped", "signal_type": signal_type})
                continue  # dropped in transit — approaches never see this reading

            if record is not None:
                if isinstance(noisy_value, dict):
                    record.append({"elapsed_ms": noisy_ts, "kind": "signal", "signal_type": "systolic_bp", "value": noisy_value["systolic"]})
                    record.append({"elapsed_ms": noisy_ts, "kind": "signal", "signal_type": "diastolic_bp", "value": noisy_value["diastolic"]})
                else:
                    record.append({"elapsed_ms": noisy_ts, "kind": "signal", "signal_type": signal_type, "value": noisy_value})

            # --- Approach A ---
            for _sig, _val, level in evaluate_message(signal_type, noisy_value):
                if level in ("warning", "critical"):
                    alarms[APPROACH_A].append(noisy_ts)
                    if record is not None:
                        record.append({"elapsed_ms": noisy_ts, "kind": "alarm_a", "signal_type": _sig, "level": level})

            # --- Update shared window state (backs B and C) ---
            if signal_type == "blood_pressure":
                ews_state.update("systolic_bp", noisy_value["systolic"], noisy_ts)
            else:
                ews_state.update(signal_type, noisy_value, noisy_ts)

            # --- Approach C: continuous ---
            scored_c = score_composite(ews_state, noisy_ts, APPROACH_C)
            if scored_c is not None:
                if record is not None:
                    record.append({"elapsed_ms": noisy_ts, "kind": "composite_c", "news2_score": scored_c.news2_score})
                if scored_c.alarm_level != "ok":
                    alarms[APPROACH_C].append(noisy_ts)

            # --- Approach B: fixed ~60s tick ---
            if batch_scheduler.due("BENCH-01", noisy_ts):
                scored_b = score_composite(ews_state, noisy_ts, APPROACH_B)
                if scored_b is not None:
                    if record is not None:
                        record.append({"elapsed_ms": noisy_ts, "kind": "composite_b", "news2_score": scored_b.news2_score})
                    if scored_b.alarm_level != "ok":
                        alarms[APPROACH_B].append(noisy_ts)

    results = {}
    for approach, fired in alarms.items():
        fired_after_onset = [t for t in fired if t >= scenario.onset_offset_ms]
        detected = len(fired_after_onset) > 0

        if scenario.expect_alarm:
            tpr = 1.0 if detected else 0.0
            fpr = None
            detection_latency_ms = (min(fired_after_onset) - scenario.onset_offset_ms) if detected else None
        else:
            tpr = None
            fpr = 1.0 if len(fired) > 0 else 0.0
            detection_latency_ms = None

        alarm_rate_per_day = len(fired) * (86_400_000 / duration_ms)

        results[approach] = {
            "TPR": tpr, "FPR": fpr,
            "detection_latency_ms": detection_latency_ms,
            "alarm_rate_per_day": round(alarm_rate_per_day, 2),
            "p99_pipeline_latency_ms": "",  # live-pipeline-only metric; see module docstring
        }
    return results


def run_benchmark(num_runs: int, out_path: Path) -> None:
    noise_config = NoiseConfig(packet_loss_rate=0.01, spike_probability=0.005, clock_drift_ms=50)

    rows = []
    for scenario in SCENARIOS.values():
        for run_idx in range(num_runs):
            signal_seed = 1000 * (run_idx + 1)
            noise_seed = 2000 * (run_idx + 1)
            results = _simulate_run(scenario, signal_seed, noise_seed, noise_config)
            for approach, metrics in results.items():
                rows.append({
                    "scenario": scenario.scenario_id,
                    "signal_seed": signal_seed,
                    "noise_seed": noise_seed,
                    "approach": approach,
                    **metrics,
                })
            print(f"{scenario.scenario_id} run {run_idx + 1}/{num_runs} done")

    fieldnames = ["scenario", "signal_seed", "noise_seed", "approach",
                  "TPR", "FPR", "detection_latency_ms", "alarm_rate_per_day",
                  "p99_pipeline_latency_ms"]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10, help="Seed pairs per scenario")
    parser.add_argument("--out", type=Path, default=Path("benchmark_results.csv"))
    args = parser.parse_args()
    run_benchmark(args.runs, args.out)
