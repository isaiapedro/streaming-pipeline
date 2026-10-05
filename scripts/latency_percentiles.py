"""Privacy-safe aggregate latency percentile exports and comparison plots."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path


PERCENTILES = tuple(range(50, 100))


def percentile(values: Sequence[float], percent: int) -> float | None:
    """Return a linearly interpolated percentile for ``percent`` in [0, 100]."""
    if not values:
        return None
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def percentile_rows(
    samples: Mapping[str, Sequence[float | None]],
    percentiles: Sequence[int] = PERCENTILES,
) -> list[dict[str, int | float | str]]:
    """Build aggregate rows, excluding missing/rejected observations."""
    rows: list[dict[str, int | float | str]] = []
    for transport, candidates in samples.items():
        values = [value for value in candidates if value is not None]
        for percent in percentiles:
            value = percentile(values, percent)
            if value is not None:
                rows.append(
                    {
                        "transport": transport,
                        "percentile": percent,
                        "latency_ms": round(value, 6),
                        "sample_count": len(values),
                    }
                )
    return rows


def write_percentile_csv(rows: Sequence[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("transport", "percentile", "latency_ms", "sample_count"),
        )
        writer.writeheader()
        writer.writerows(rows)


def render_percentile_plot(
    rows: Sequence[dict], output: Path, *, title: str, log_y: bool = False
) -> None:
    import matplotlib.pyplot as plt

    output.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(10, 6), constrained_layout=True)
    transports = list(dict.fromkeys(str(row["transport"]) for row in rows))
    for transport in transports:
        selected = [row for row in rows if row["transport"] == transport]
        axis.plot(
            [row["percentile"] for row in selected],
            [row["latency_ms"] for row in selected],
            marker="o",
            markersize=2.5,
            linewidth=2,
            label=transport.upper(),
        )
    axis.set_title(title)
    axis.set_xlabel("Latency percentile")
    axis.set_ylabel("Latency (ms)")
    if log_y:
        axis.set_yscale("log")
        axis.set_ylabel("Latency (ms, logarithmic scale)")
    axis.set_xticks((50, 60, 70, 80, 90, 95, 99))
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.savefig(output, dpi=180)
    plt.close(figure)
