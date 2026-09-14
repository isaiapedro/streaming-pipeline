#!/usr/bin/env python3
"""Run the deterministic A/B/C benchmark with crossed signal/noise seeds.

The harness reuses the production generators, scenario trajectories, noise
model, and scorers. It reports scoring latency and operational alarm episodes;
transport and storage latency remain separate live-pipeline measurements.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
PROJECT_ROOT = Path(__file__).parent.parent

from brain.alarm_episodes import AlarmEpisodeTracker
from brain.approaches import APPROACH_A, APPROACH_B, APPROACH_C, BatchScheduler, score_composite
from brain.evaluator import evaluate_message
from brain.ews_window import PatientEWSState
from data.generators.blood_pressure import BloodPressureGenerator
from data.generators.correlation import correlated_delta
from data.generators.heart_rate import HeartRateGenerator
from data.generators.noise import NoiseConfig, NoiseInjector
from data.generators.respiratory_rate import RespiratoryRateGenerator
from data.generators.spo2 import SpO2Generator
from data.generators.temperature import TemperatureGenerator
from data.scenarios.definitions import SCENARIOS, Scenario

TICK_MS = 1_000
DEFAULT_SIGNAL_SEEDS = tuple(1_000 * index for index in range(1, 6))
DEFAULT_NOISE_SEEDS = tuple(2_000 * index for index in range(1, 6))
DEFAULT_STABLE_DURATION_S = 86_400
DEFAULT_CLEAR_HOLD_MS = 10_000
APPROACHES = (APPROACH_A, APPROACH_B, APPROACH_C)
RESULT_FIELDS = (
    "run_id", "scenario", "signal_seed", "noise_seed", "approach", "duration_s",
    "detection_run_rate", "false_alarm_run_probability", "scoring_detection_latency_ms",
    "alarm_observation_count", "alarm_episode_count", "alarm_episode_rate_per_patient_day",
    "time_in_alarm_ms", "time_in_alarm_pct", "window_completeness_pct",
)
JOURNAL_VERSION = 1

_BASE_PROFILE = {
    "patient_id": "BENCH-01",
    "condition": "benchmark",
    "baselines": {
        "heart_rate": {"mean": 75, "std": 8},
        "spo2": {"mean": 97, "std": 1.0},
        "systolic_bp": {"mean": 120, "std": 10},
        "diastolic_bp": {"mean": 78, "std": 8},
        "respiratory_rate": {"mean": 16, "std": 2},
        "temperature": {"mean": 36.8, "std": 0.2},
    },
    "copd_flag": False,
}
_BP_SUB_KEYS = {"systolic_bp": "systolic", "diastolic_bp": "diastolic"}


def run_id_for(scenario: str, signal_seed: int, noise_seed: int) -> str:
    material = f"benchmark-v2:{scenario}:{signal_seed}:{noise_seed}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def _simulate_run(
    scenario: Scenario,
    signal_seed: int,
    noise_seed: int,
    noise_config: NoiseConfig,
    clear_hold_ms: int = DEFAULT_CLEAR_HOLD_MS,
    record: list[dict] | None = None,
) -> dict[str, dict]:
    """Simulate one scenario/seed cell for all approaches concurrently."""

    copd_flag = scenario.copd_flag_override if scenario.copd_flag_override is not None else False
    profile = dict(_BASE_PROFILE, copd_flag=copd_flag)
    generators = {
        "heart_rate": HeartRateGenerator(profile, signal_seed),
        "spo2": SpO2Generator(profile, signal_seed + 1),
        "blood_pressure": BloodPressureGenerator(profile, signal_seed + 2),
        "respiratory_rate": RespiratoryRateGenerator(profile, signal_seed + 3),
        "temperature": TemperatureGenerator(profile, signal_seed + 4),
    }
    noise = NoiseInjector(noise_config, noise_seed)
    spo2_scale = scenario.news2_spo2_scale_override or 1
    ews_state = PatientEWSState("BENCH-01", spo2_scale=spo2_scale)
    batch_scheduler = BatchScheduler()
    trackers = {approach: AlarmEpisodeTracker(clear_hold_ms) for approach in APPROACHES}
    tracker_timestamps = {approach: 0 for approach in APPROACHES}
    alarm_observations = {approach: [] for approach in APPROACHES}
    current_a_levels: dict[str, str] = {}
    composite_counts = {APPROACH_B: 0, APPROACH_C: 0}
    complete_counts = {APPROACH_B: 0, APPROACH_C: 0}
    latest: dict[str, float] = {}

    duration_ms = int(scenario.duration_s * 1_000)
    for elapsed_ms in range(0, duration_ms, TICK_MS):
        deltas = scenario.delta_at(elapsed_ms)
        for signal_type, generator in generators.items():
            raw_value = generator.generate(elapsed_ms)
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
                continue

            if record is not None:
                values = (
                    {"systolic_bp": noisy_value["systolic"], "diastolic_bp": noisy_value["diastolic"]}
                    if signal_type == "blood_pressure"
                    else {signal_type: noisy_value}
                )
                for name, measured in values.items():
                    record.append({"elapsed_ms": noisy_ts, "kind": "signal", "signal_type": name, "value": measured})

            for evaluated_signal, _evaluated_value, level in evaluate_message(signal_type, noisy_value):
                current_a_levels[evaluated_signal] = level
            a_alarming = any(level in ("warning", "critical") for level in current_a_levels.values())
            tracker_timestamps[APPROACH_A] = max(tracker_timestamps[APPROACH_A], noisy_ts)
            trackers[APPROACH_A].observe(tracker_timestamps[APPROACH_A], a_alarming)
            if a_alarming:
                alarm_observations[APPROACH_A].append(noisy_ts)
            if record is not None:
                record.append({"elapsed_ms": noisy_ts, "kind": "alarm_a_state", "alarming": a_alarming})

            if signal_type == "blood_pressure":
                ews_state.update("systolic_bp", noisy_value["systolic"], noisy_ts)
            else:
                ews_state.update(signal_type, noisy_value, noisy_ts)

            scored_c = score_composite(ews_state, noisy_ts, APPROACH_C)
            if scored_c is not None:
                composite_counts[APPROACH_C] += 1
                complete_counts[APPROACH_C] += int(scored_c.window_complete)
                alarming = scored_c.alarm_level != "ok"
                tracker_timestamps[APPROACH_C] = max(tracker_timestamps[APPROACH_C], noisy_ts)
                trackers[APPROACH_C].observe(tracker_timestamps[APPROACH_C], alarming)
                if alarming:
                    alarm_observations[APPROACH_C].append(noisy_ts)
                if record is not None:
                    record.append({"elapsed_ms": noisy_ts, "kind": "composite_c", "news2_score": scored_c.news2_score, "alarming": alarming})

            if batch_scheduler.due("BENCH-01", noisy_ts):
                scored_b = score_composite(ews_state, noisy_ts, APPROACH_B)
                if scored_b is not None:
                    composite_counts[APPROACH_B] += 1
                    complete_counts[APPROACH_B] += int(scored_b.window_complete)
                    alarming = scored_b.alarm_level != "ok"
                    tracker_timestamps[APPROACH_B] = max(tracker_timestamps[APPROACH_B], noisy_ts)
                    trackers[APPROACH_B].observe(tracker_timestamps[APPROACH_B], alarming)
                    if alarming:
                        alarm_observations[APPROACH_B].append(noisy_ts)
                    if record is not None:
                        record.append({"elapsed_ms": noisy_ts, "kind": "composite_b", "news2_score": scored_b.news2_score, "alarming": alarming})

    results: dict[str, dict] = {}
    for approach in APPROACHES:
        episodes = trackers[approach].finalize(duration_ms)
        post_onset_starts = [episode.start_ms for episode in episodes if episode.start_ms >= scenario.onset_offset_ms]
        detected = bool(post_onset_starts)
        time_in_alarm_ms = sum(episode.duration_ms for episode in episodes)
        results[approach] = {
            "detection_run_rate": (1.0 if detected else 0.0) if scenario.expect_alarm else None,
            "false_alarm_run_probability": None if scenario.expect_alarm else (1.0 if episodes else 0.0),
            "scoring_detection_latency_ms": (min(post_onset_starts) - scenario.onset_offset_ms) if scenario.expect_alarm and detected else None,
            "alarm_observation_count": len(alarm_observations[approach]),
            "alarm_episode_count": len(episodes),
            "alarm_episode_rate_per_patient_day": len(episodes) * 86_400_000 / duration_ms,
            "time_in_alarm_ms": time_in_alarm_ms,
            "time_in_alarm_pct": 100.0 * time_in_alarm_ms / duration_ms,
            "window_completeness_pct": (
                100.0 * complete_counts[approach] / composite_counts[approach]
                if approach in composite_counts and composite_counts[approach]
                else None
            ),
        }
    return results


def _git_state(ignore_paths: tuple[Path, ...] = ()) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        ignored = set()
        for path in ignore_paths:
            try:
                ignored.add(path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix())
            except ValueError:
                pass
        dirty = any(line[3:].strip('"') not in ignored for line in status)
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _protocol_context(
    signal_seeds: tuple[int, ...],
    noise_seeds: tuple[int, ...],
    stable_duration_s: int,
    clear_hold_ms: int,
    commit: str | None,
    dirty: bool | None,
) -> dict:
    scenarios = []
    for original in SCENARIOS.values():
        scenario = scenario_for_benchmark(original, stable_duration_s)
        scenarios.append(asdict(scenario))
    return {
        "journal_version": JOURNAL_VERSION,
        "git_commit": commit,
        "worktree_dirty": dirty,
        "pipeline_version": os.getenv("PIPELINE_VERSION"),
        "signal_seeds": list(signal_seeds),
        "noise_seeds": list(noise_seeds),
        "stable_duration_s": stable_duration_s,
        "clear_hold_ms": clear_hold_ms,
        "noise": {
            "packet_loss_rate": 0.01,
            "spike_probability": 0.005,
            "clock_drift_ms": 50,
        },
        "result_fields": list(RESULT_FIELDS),
        "scenarios": scenarios,
    }


def _protocol_hash(context: dict) -> str:
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_journal(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _read_journal(path: Path, expected_protocol_hash: str) -> list[dict]:
    """Read durable cells, discarding only a torn final append."""

    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        last_newline = data.rfind(b"\n")
        durable_length = last_newline + 1
        with path.open("r+b") as handle:
            handle.truncate(durable_length)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
        data = data[:durable_length]

    entries = []
    for line_number, line in enumerate(data.splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"benchmark journal is corrupt at complete line {line_number}") from exc
        if entry.get("protocol_hash") != expected_protocol_hash:
            raise RuntimeError("benchmark journal protocol does not match this invocation")
        if not isinstance(entry.get("log"), dict) or not isinstance(entry.get("rows"), list):
            raise RuntimeError(f"benchmark journal has an invalid entry at line {line_number}")
        log = entry["log"]
        if not isinstance(log.get("run_id"), str) or log.get("status") not in {"completed", "failed"}:
            raise RuntimeError(f"benchmark journal has invalid run identity/status at line {line_number}")
        if not isinstance(log.get("attempt_number"), int) or log["attempt_number"] < 1:
            raise RuntimeError(f"benchmark journal has an invalid attempt number at line {line_number}")
        rows = entry["rows"]
        if log["status"] == "failed" and rows:
            raise RuntimeError(f"failed journal entry contains result rows at line {line_number}")
        if log["status"] == "completed":
            approaches = {row.get("approach") for row in rows if isinstance(row, dict)}
            run_ids = {row.get("run_id") for row in rows if isinstance(row, dict)}
            if len(rows) != len(APPROACHES) or approaches != set(APPROACHES) or run_ids != {log["run_id"]}:
                raise RuntimeError(f"completed journal entry has invalid result rows at line {line_number}")
        entries.append(entry)
    return entries


def _atomic_write_outputs(out_path: Path, run_log_path: Path, rows: list[dict], logs: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_log_path.parent.mkdir(parents=True, exist_ok=True)
    csv_temp = out_path.with_name(f".{out_path.name}.tmp")
    log_temp = run_log_path.with_name(f".{run_log_path.name}.tmp")
    with csv_temp.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    with log_temp.open("w", encoding="utf-8") as handle:
        for entry in logs:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(csv_temp, out_path)
    os.replace(log_temp, run_log_path)
    _fsync_directory(out_path.parent)
    if run_log_path.parent.resolve() != out_path.parent.resolve():
        _fsync_directory(run_log_path.parent)


def scenario_for_benchmark(original: Scenario, stable_duration_s: int) -> Scenario:
    """Apply benchmark-only duration overrides without mutating the registry."""

    if stable_duration_s < 1:
        raise ValueError("stable_duration_s must be positive")
    return replace(original, duration_s=stable_duration_s) if original.scenario_id == "stable_baseline" else original


def run_benchmark(
    signal_seeds: tuple[int, ...],
    noise_seeds: tuple[int, ...],
    out_path: Path,
    run_log_path: Path,
    stable_duration_s: int = DEFAULT_STABLE_DURATION_S,
    clear_hold_ms: int = DEFAULT_CLEAR_HOLD_MS,
    resume: bool = False,
    journal_path: Path | None = None,
) -> None:
    noise_config = NoiseConfig(packet_loss_rate=0.01, spike_probability=0.005, clock_drift_ms=50)
    journal_path = journal_path or run_log_path.with_name(f".{run_log_path.name}.journal")
    resume_outputs = (
        journal_path,
        out_path,
        run_log_path,
        out_path.with_name(f".{out_path.name}.tmp"),
        run_log_path.with_name(f".{run_log_path.name}.tmp"),
    )
    commit, dirty = _git_state(resume_outputs if resume else ())
    context = _protocol_context(
        signal_seeds, noise_seeds, stable_duration_s, clear_hold_ms, commit, dirty
    )
    protocol_hash = _protocol_hash(context)
    if journal_path.exists() and not resume:
        raise RuntimeError(f"unfinished benchmark journal exists; rerun with --resume: {journal_path}")
    if resume and not journal_path.exists():
        raise RuntimeError(f"cannot resume because the benchmark journal is missing: {journal_path}")
    entries = _read_journal(journal_path, protocol_hash) if resume else []
    expected_ids = {
        run_id_for(scenario_id, signal_seed, noise_seed)
        for scenario_id in SCENARIOS
        for signal_seed in signal_seeds
        for noise_seed in noise_seeds
    }
    unknown_ids = {entry["log"].get("run_id") for entry in entries}.difference(expected_ids)
    if unknown_ids:
        raise RuntimeError("benchmark journal contains cells outside this invocation")
    attempts: dict[str, list[dict]] = {}
    for entry in entries:
        history = attempts.setdefault(entry["log"]["run_id"], [])
        if entry["log"]["attempt_number"] != len(history) + 1:
            raise RuntimeError("benchmark journal attempt sequence is invalid")
        if history and history[-1]["log"]["status"] == "completed":
            raise RuntimeError("benchmark journal contains an attempt after a completed cell")
        history.append(entry)
    completed = {
        identifier: next((entry for entry in reversed(history) if entry["log"]["status"] == "completed"), None)
        for identifier, history in attempts.items()
    }
    for original in SCENARIOS.values():
        scenario = scenario_for_benchmark(original, stable_duration_s)
        for signal_seed in signal_seeds:
            for noise_seed in noise_seeds:
                identifier = run_id_for(scenario.scenario_id, signal_seed, noise_seed)
                if completed.get(identifier) is not None:
                    print(f"{scenario.scenario_id}: signal={signal_seed} noise={noise_seed} recovered")
                    continue
                started_ns = time.time_ns()
                status = "completed"
                error = None
                caught: BaseException | None = None
                result_rows: list[dict] = []
                try:
                    results = _simulate_run(scenario, signal_seed, noise_seed, noise_config, clear_hold_ms)
                    for approach, metrics in results.items():
                        result_rows.append({
                            "run_id": identifier,
                            "scenario": scenario.scenario_id,
                            "signal_seed": signal_seed,
                            "noise_seed": noise_seed,
                            "approach": approach,
                            "duration_s": scenario.duration_s,
                            **metrics,
                        })
                except BaseException as exc:
                    status, error = "failed", type(exc).__name__
                    caught = exc
                finally:
                    ended_ns = time.time_ns()
                    prior = attempts.get(identifier, [])
                    log = {
                        "provenance_schema_version": 2,
                        "protocol_sha256": protocol_hash,
                        "run_id": identifier,
                        "scenario": scenario.scenario_id,
                        "signal_seed": signal_seed,
                        "noise_seed": noise_seed,
                        "duration_s": scenario.duration_s,
                        "clear_hold_ms": clear_hold_ms,
                        "noise": {"packet_loss_rate": 0.01, "spike_probability": 0.005, "clock_drift_ms": 50},
                        "started_at_unix_ns": started_ns,
                        "ended_at_unix_ns": ended_ns,
                        "wall_duration_ms": (ended_ns - started_ns) / 1_000_000,
                        "status": status,
                        "error": error,
                        "attempt_number": len(prior) + 1,
                        "recovered_from_interruption": bool(prior),
                        "prior_failed_attempts": sum(
                            entry["log"].get("status") == "failed" for entry in prior
                        ),
                        "git_commit": commit,
                        "worktree_dirty": dirty,
                    }
                    journal_entry = {
                        "protocol_hash": protocol_hash,
                        "log": log,
                        "rows": result_rows if status == "completed" else [],
                    }
                    _append_journal(journal_path, journal_entry)
                    attempts.setdefault(identifier, []).append(journal_entry)
                    if status == "completed":
                        completed[identifier] = journal_entry
                if status == "failed":
                    if not isinstance(caught, Exception):
                        raise caught
                    raise RuntimeError(
                        f"benchmark cell failed: {identifier} ({error}); resume with --resume"
                    ) from caught
                print(f"{scenario.scenario_id}: signal={signal_seed} noise={noise_seed} done")

    ordered_ids = [
        run_id_for(scenario_id, signal_seed, noise_seed)
        for scenario_id in SCENARIOS
        for signal_seed in signal_seeds
        for noise_seed in noise_seeds
    ]
    final_entries = [completed[identifier] for identifier in ordered_ids]
    rows = [row for entry in final_entries for row in entry["rows"]]
    logs = [entry["log"] for entry in final_entries]
    _atomic_write_outputs(out_path, run_log_path, rows, logs)
    journal_path.unlink()
    _fsync_directory(journal_path.parent)
    print(f"Wrote {len(rows)} approach rows to {out_path} and {len(logs)} run records to {run_log_path}")


def _seeds(count: int, multiplier: int) -> tuple[int, ...]:
    if count < 1:
        raise argparse.ArgumentTypeError("seed count must be positive")
    return tuple(multiplier * index for index in range(1, count + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-seeds", type=int, default=5)
    parser.add_argument("--noise-seeds", type=int, default=5)
    parser.add_argument("--stable-duration-s", type=int, default=DEFAULT_STABLE_DURATION_S)
    parser.add_argument("--clear-hold-ms", type=int, default=DEFAULT_CLEAR_HOLD_MS)
    parser.add_argument("--out", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--run-log", type=Path, default=Path("evidence/experiment_runs.jsonl"))
    parser.add_argument("--resume", action="store_true", help="Resume a matching interrupted journal")
    parser.add_argument("--journal", type=Path, help="Override the durable per-cell journal path")
    arguments = parser.parse_args()
    run_benchmark(
        _seeds(arguments.signal_seeds, 1_000),
        _seeds(arguments.noise_seeds, 2_000),
        arguments.out,
        arguments.run_log,
        arguments.stable_duration_s,
        arguments.clear_hold_ms,
        arguments.resume,
        arguments.journal,
    )
