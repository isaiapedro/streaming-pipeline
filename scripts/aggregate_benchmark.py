#!/usr/bin/env python3
"""Validate, aggregate, and visualize the dissertation A/B/C benchmark."""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.approaches import APPROACH_A, APPROACH_B, APPROACH_C
from brain.alarm_episodes import AlarmEpisodeTracker
from data.generators.noise import NoiseConfig
from data.scenarios.definitions import SCENARIOS
from scripts.run_benchmark import _simulate_run

METRICS = (
    "detection_run_rate", "false_alarm_run_probability", "scoring_detection_latency_ms",
    "alarm_observation_count", "alarm_episode_count", "alarm_episode_rate_per_patient_day",
    "time_in_alarm_ms", "time_in_alarm_pct", "window_completeness_pct",
)
PROPORTION_METRICS = {"detection_run_rate", "false_alarm_run_probability"}
APPROACHES = (APPROACH_A, APPROACH_B, APPROACH_C)
SUMMARY_NAMES = ("n", "mean", "std", "median", "q1", "q3", "ci95_low", "ci95_high")
COLORS = {APPROACH_A: "#D55E00", APPROACH_B: "#0072B2", APPROACH_C: "#009E73"}


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite metric value is not allowed: {value!r}")
    return parsed


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"run_id", "scenario", "signal_seed", "noise_seed", "approach", "duration_s", *METRICS}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Benchmark CSV is missing columns: {', '.join(sorted(missing))}")
        rows = []
        for source in reader:
            row = dict(source)
            for metric in METRICS:
                row[metric] = _optional_float(source.get(metric))
            rows.append(row)
    return rows


def validate_full_matrix(rows: list[dict], expected_signal_seeds: int = 5, expected_noise_seeds: int = 5) -> None:
    expected_scenarios = set(SCENARIOS)
    seen_scenarios = {row["scenario"] for row in rows}
    if seen_scenarios != expected_scenarios:
        raise ValueError(f"Scenario set mismatch: expected {sorted(expected_scenarios)}, got {sorted(seen_scenarios)}")
    expected_cells = expected_signal_seeds * expected_noise_seeds
    expected_total = len(expected_scenarios) * len(APPROACHES) * expected_cells
    if len(rows) != expected_total:
        raise ValueError(f"Expected {expected_total} rows, found {len(rows)}")

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["approach"] not in APPROACHES:
            raise ValueError(f"Unknown approach: {row['approach']!r}")
        grouped[(row["scenario"], row["approach"])].append(row)
    for scenario in sorted(expected_scenarios):
        seed_sets = []
        for approach in APPROACHES:
            group = grouped[(scenario, approach)]
            seeds = {(row["signal_seed"], row["noise_seed"]) for row in group}
            signal_count = len({pair[0] for pair in seeds})
            noise_count = len({pair[1] for pair in seeds})
            if len(group) != expected_cells or len(seeds) != expected_cells:
                raise ValueError(f"{scenario}/{approach} must contain {expected_cells} unique seed pairs")
            if signal_count != expected_signal_seeds or noise_count != expected_noise_seeds:
                raise ValueError(f"{scenario}/{approach} does not contain the required crossed seed design")
            seed_sets.append(seeds)
        if not all(seeds == seed_sets[0] for seeds in seed_sets[1:]):
            raise ValueError(f"Approaches do not share identical seed pairs for {scenario}")


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _wilson(values: list[float]) -> tuple[float, float]:
    n, successes, z = len(values), sum(values), 1.959963984540054
    centre = (successes + z * z / 2) / (n + z * z)
    margin = z * math.sqrt(successes * (n - successes) / n + z * z / 4) / (n + z * z)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _bootstrap_mean_ci(values: list[float], seed: int = 20_260_913) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    estimates = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(2_000)]
    return _quantile(estimates, 0.025), _quantile(estimates, 0.975)


def _summary(values: list[float], proportion: bool = False) -> dict[str, int | float | None]:
    if not values:
        return {name: 0 if name == "n" else None for name in SUMMARY_NAMES}
    low, high = _wilson(values) if proportion else _bootstrap_mean_ci(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.stdev(values) if len(values) > 1 else None,
        "median": statistics.median(values),
        "q1": _quantile(values, 0.25),
        "q3": _quantile(values, 0.75),
        "ci95_low": low,
        "ci95_high": high,
    }


def aggregate(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["scenario"], row["approach"])].append(row)
    output = []
    for scenario in SCENARIOS:
        for approach in APPROACHES:
            group = grouped[(scenario, approach)]
            result: dict[str, object] = {"scenario": scenario, "approach": approach, "source_rows": len(group)}
            for metric in METRICS:
                values = [row[metric] for row in group if row[metric] is not None]
                for name, value in _summary(values, metric in PROPORTION_METRICS).items():
                    result[f"{metric}_{name}"] = value
            output.append(result)
    return output


def write_aggregate(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["scenario", "approach", "source_rows"] + [f"{metric}_{name}" for metric in METRICS for name in SUMMARY_NAMES]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: "" if value is None else value for key, value in row.items()} for row in rows)


def _errorbar_chart(raw: list[dict], aggregate_rows: list[dict], scenarios: list[str], metric: str, title: str, ylabel: str, path: Path) -> None:
    by_key = {(row["scenario"], row["approach"]): row for row in aggregate_rows}
    fig, axis = plt.subplots(figsize=(11, 5), constrained_layout=True)
    width = 0.24
    for offset, approach in enumerate(APPROACHES):
        positions = [index + (offset - 1) * width for index in range(len(scenarios))]
        means = [by_key[(scenario, approach)][f"{metric}_mean"] for scenario in scenarios]
        lows = [by_key[(scenario, approach)][f"{metric}_ci95_low"] for scenario in scenarios]
        highs = [by_key[(scenario, approach)][f"{metric}_ci95_high"] for scenario in scenarios]
        valid = [(x, mean, low, high) for x, mean, low, high in zip(positions, means, lows, highs) if mean is not None]
        if valid:
            x, y, low, high = zip(*valid)
            axis.errorbar(x, y, yerr=[[m - l for m, l in zip(y, low)], [h - m for m, h in zip(y, high)]], fmt="o", capsize=4, color=COLORS[approach], label=f"Approach {approach}")
        for position, scenario in zip(positions, scenarios):
            values = [row[metric] for row in raw if row["scenario"] == scenario and row["approach"] == approach and row[metric] is not None]
            axis.scatter([position] * len(values), values, s=8, alpha=0.12, color=COLORS[approach])
    axis.set(title=title, ylabel=ylabel)
    axis.set_xticks(range(len(scenarios)), [name.replace("_", " ") for name in scenarios], rotation=20, ha="right")
    axis.grid(axis="y", alpha=0.2)
    axis.legend()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _tradeoff_chart(aggregate_rows: list[dict], path: Path) -> None:
    positives = [name for name, scenario in SCENARIOS.items() if scenario.expect_alarm]
    negatives = [name for name, scenario in SCENARIOS.items() if not scenario.expect_alarm]
    by_key = {(row["scenario"], row["approach"]): row for row in aggregate_rows}
    fig, axis = plt.subplots(figsize=(7, 5), constrained_layout=True)
    for approach in APPROACHES:
        latency = statistics.fmean(by_key[(scenario, approach)]["scoring_detection_latency_ms_median"] for scenario in positives) / 1_000
        burden = statistics.fmean(by_key[(scenario, approach)]["alarm_episode_rate_per_patient_day_mean"] for scenario in negatives)
        detection = statistics.fmean(by_key[(scenario, approach)]["detection_run_rate_mean"] for scenario in positives)
        axis.scatter(latency, burden, s=100 + 400 * detection, color=COLORS[approach], alpha=0.85)
        axis.annotate(f"Approach {approach}\n{detection:.0%} detected", (latency, burden), xytext=(6, 6), textcoords="offset points")
    axis.set(xlabel="Median scoring latency among detected runs (s; lower is better)", ylabel="False-scenario alarm episodes/patient-day (lower is better)", title="Detection-speed, reliability, and alarm-burden trade-off")
    axis.grid(alpha=0.25)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _paired_latency_chart(raw: list[dict], scenarios: list[str], path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=True, sharey=True, constrained_layout=True)
    for axis, scenario in zip(axes.flat, scenarios):
        cells: dict[str, dict[str, float]] = defaultdict(dict)
        for row in raw:
            if row["scenario"] == scenario and row["scoring_detection_latency_ms"] is not None:
                cells[row["run_id"]][row["approach"]] = row["scoring_detection_latency_ms"] / 1_000
        for cell in cells.values():
            pairs = [(index, cell[approach]) for index, approach in enumerate(APPROACHES) if approach in cell]
            if pairs:
                axis.plot(*zip(*pairs), color="#888888", alpha=0.18, linewidth=0.7)
        for index, approach in enumerate(APPROACHES):
            values = [cell[approach] for cell in cells.values() if approach in cell]
            if values:
                median, q1, q3 = statistics.median(values), _quantile(values, 0.25), _quantile(values, 0.75)
                axis.errorbar(index, median, yerr=[[median - q1], [q3 - median]], fmt="o", capsize=5, color=COLORS[approach], markersize=7)
                axis.text(index, max(values) * 1.2, f"{len(values)}/25", ha="center", fontsize=8, color=COLORS[approach])
        axis.set_title(scenario.replace("_", " "))
        axis.set_yscale("log")
        axis.grid(axis="y", alpha=0.2)
    for axis in axes[-1]:
        axis.set_xticks(range(3), [f"Approach {approach}" for approach in APPROACHES])
    for axis in axes[:, 0]:
        axis.set_ylabel("Scoring latency (s, log scale)")
    fig.suptitle("Paired seed-cell latency; labels show detected runs / 25")
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _timeline(path: Path) -> None:
    record: list[dict] = []
    scenario = SCENARIOS["sepsis_progression"]
    _simulate_run(scenario, 1_000, 2_000, NoiseConfig(packet_loss_rate=0.01, spike_probability=0.005, clock_drift_ms=50), record=record)
    signals = ("heart_rate", "respiratory_rate", "spo2", "systolic_bp", "temperature")
    fig, axes = plt.subplots(6, 1, figsize=(11, 11), sharex=True, constrained_layout=True)
    for signal, signals_axis in zip(signals, axes[:-1]):
        points = [(row["elapsed_ms"] / 1_000, row["value"]) for row in record if row["kind"] == "signal" and row["signal_type"] == signal]
        if points:
            signals_axis.plot(*zip(*points), linewidth=0.8, color="#4C78A8")
        signals_axis.set_ylabel(signal.replace("_", " "), fontsize=8)
        signals_axis.axvline(scenario.onset_offset_ms / 1_000, linestyle="--", color="black", linewidth=0.8)
        signals_axis.grid(alpha=0.2)
    score_axis = axes[-1]
    for kind, approach in (("composite_b", APPROACH_B), ("composite_c", APPROACH_C)):
        points = [(row["elapsed_ms"] / 1_000, row["news2_score"]) for row in record if row["kind"] == kind]
        if points:
            score_axis.plot(*zip(*points), linewidth=1, label=f"Approach {approach} NEWS2", color=COLORS[approach])

    kind_by_approach = {APPROACH_A: "alarm_a_state", APPROACH_B: "composite_b", APPROACH_C: "composite_c"}
    duration_ms = int(scenario.duration_s * 1_000)
    for approach in APPROACHES:
        tracker = AlarmEpisodeTracker()
        last_ms = 0
        for row in record:
            if row["kind"] != kind_by_approach[approach]:
                continue
            last_ms = max(last_ms, int(row["elapsed_ms"]))
            tracker.observe(last_ms, bool(row["alarming"]))
        starts = [episode.start_ms for episode in tracker.finalize(duration_ms) if episode.start_ms >= scenario.onset_offset_ms]
        if starts:
            score_axis.axvline(starts[0] / 1_000, color=COLORS[approach], linestyle=":", linewidth=1.8, label=f"Approach {approach} first new episode")

    score_axis.axvline(scenario.onset_offset_ms / 1_000, linestyle="--", color="black", linewidth=1, label="ground-truth onset")
    score_axis.grid(alpha=0.2)
    score_axis.legend(ncol=3, fontsize=7)
    score_axis.set(xlabel="Elapsed time (s)", ylabel="NEWS2 score")
    fig.suptitle("Representative sepsis trajectory, scoring response, and first new alarm episodes")
    fig.savefig(path, dpi=200)
    plt.close(fig)


def generate_figures(raw: list[dict], aggregate_rows: list[dict], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    positive = [name for name, scenario in SCENARIOS.items() if scenario.expect_alarm]
    negative = [name for name, scenario in SCENARIOS.items() if not scenario.expect_alarm]
    paths = [
        output_dir / "abc_detection_latency.png",
        output_dir / "abc_false_alarm_probability.png",
        output_dir / "abc_alarm_episode_rate.png",
        output_dir / "abc_tradeoff.png",
        output_dir / "abc_representative_timeline.png",
    ]
    _paired_latency_chart(raw, positive, paths[0])
    _errorbar_chart(raw, aggregate_rows, negative, "false_alarm_run_probability", "Probability of at least one false alarm in a run", "Probability (Wilson 95% CI)", paths[1])
    _errorbar_chart(raw, aggregate_rows, negative, "alarm_episode_rate_per_patient_day", "Operational false-alarm episode burden", "Episodes per patient-day", paths[2])
    _tradeoff_chart(aggregate_rows, paths[3])
    _timeline(paths[4])
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--output", type=Path, default=Path("evidence/benchmark_aggregate.csv"))
    parser.add_argument("--figures-dir", type=Path, default=Path("evidence/figures"))
    parser.add_argument("--expected-signal-seeds", type=int, default=5)
    parser.add_argument("--expected-noise-seeds", type=int, default=5)
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    source = load_rows(args.input)
    validate_full_matrix(source, args.expected_signal_seeds, args.expected_noise_seeds)
    result = aggregate(source)
    write_aggregate(result, args.output)
    figures = [] if args.no_figures else generate_figures(source, result, args.figures_dir)
    print(f"Validated {len(source)} source rows and wrote {len(result)} aggregate rows to {args.output}")
    print(f"Generated {len(figures)} dissertation figures")


if __name__ == "__main__":
    main()
