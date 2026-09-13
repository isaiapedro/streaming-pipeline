#!/usr/bin/env python3
"""Render dissertation evidence completeness without turning missing data into zero."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).parent.parent


def _architecture_figure(path: Path) -> None:
    fig, axis = plt.subplots(figsize=(12, 6), constrained_layout=True)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    nodes = {
        "Synthetic\ngenerators": (0.03, 0.62, "implemented"),
        "NATS + canonical\nProtobuf ingress": (0.24, 0.62, "implemented"),
        "Validated A/B/C +\nlocal NEWS2 scoring": (0.47, 0.62, "implemented"),
        "SQLite WAL\ndurable outbox": (0.70, 0.62, "implemented"),
        "Local alarm\npublish": (0.70, 0.84, "implemented"),
        "Influx confirmed\ncloud persistence": (0.82, 0.62, "unverified"),
        "Grafana live render\n+ notification": (0.82, 0.34, "unverified"),
        "Cloud suppression\nfeedback": (0.47, 0.12, "future"),
        "T2–T4 scale\nevidence": (0.24, 0.12, "unverified"),
        "Kafka + Schema Registry\nisolated comparison": (0.24, 0.36, "supplemental"),
    }
    styles = {
        "implemented": ("#D9F2E6", "#009E73", "-"),
        "supplemental": ("#DCEAF7", "#0072B2", "-"),
        "unverified": ("#F0F0F0", "#777777", "--"),
        "future": ("#F4DDEC", "#CC79A7", "--"),
    }
    centres = {}
    for label, (x, y, status) in nodes.items():
        face, edge, linestyle = styles[status]
        width, height = 0.16, 0.11
        axis.add_patch(FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.012", facecolor=face, edgecolor=edge, linewidth=2, linestyle=linestyle))
        axis.text(x + width / 2, y + height / 2, label, ha="center", va="center", fontsize=8)
        centres[label] = (x + width / 2, y + height / 2)

    def arrow(source: str, target: str, dashed: bool = False) -> None:
        axis.annotate("", xy=centres[target], xytext=centres[source], arrowprops={"arrowstyle": "->", "color": "#555555", "linestyle": "--" if dashed else "-", "linewidth": 1.4, "shrinkA": 45, "shrinkB": 45})

    arrow("Synthetic\ngenerators", "NATS + canonical\nProtobuf ingress")
    arrow("NATS + canonical\nProtobuf ingress", "Validated A/B/C +\nlocal NEWS2 scoring")
    arrow("Validated A/B/C +\nlocal NEWS2 scoring", "SQLite WAL\ndurable outbox")
    arrow("Validated A/B/C +\nlocal NEWS2 scoring", "Local alarm\npublish")
    arrow("SQLite WAL\ndurable outbox", "Influx confirmed\ncloud persistence", True)
    arrow("Influx confirmed\ncloud persistence", "Grafana live render\n+ notification", True)
    arrow("Synthetic\ngenerators", "Kafka + Schema Registry\nisolated comparison")
    arrow("NATS + canonical\nProtobuf ingress", "T2–T4 scale\nevidence", True)
    arrow("Influx confirmed\ncloud persistence", "Cloud suppression\nfeedback", True)
    arrow("Cloud suppression\nfeedback", "Local alarm\npublish", True)
    axis.text(0.02, 0.97, "Demonstrated and planned architecture", fontsize=16, fontweight="bold", va="top")
    axis.text(0.02, 0.91, "Solid green: implemented core · solid blue: isolated supplemental path · dashed grey: unverified · dashed magenta: future", fontsize=9, va="top")
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    manifest = json.loads((ROOT / "evidence/manifest.json").read_text())
    controls = manifest.get("compliance_controls", {})
    traceability = manifest["live_experiments"].get("stored_traceability_audit", {"status": "unexecuted"})
    rows = [
        ("A/B/C scoring benchmark", "executed"),
        ("NATS/MQTT latency", manifest["live_experiments"]["protocol"]["status"]),
        ("Publish-to-consume latency", manifest["live_experiments"]["pipeline_latency"]["status"]),
        ("Publish-to-storage latency", "unexecuted"),
        ("Synthetic/reference distribution", manifest["distribution_reference"]["status"]),
        ("Scale T1", manifest["scale_tiers"][0]["status"]),
        ("Scale T2–T4", "unexecuted"),
        ("Stored traceability coverage", traceability["status"]),
        ("Grafana configuration", "offline_tested"),
        ("Grafana live render", controls.get("dashboard_semantic_validation", {}).get("live_render", "unexecuted")),
        ("Alert notification delivery", controls.get("alert_delivery", {}).get("status", "unexecuted")),
        ("Credential rotation", controls.get("credential_rotation", {}).get("status", "owner_confirmation_pending")),
        ("Retention approval", controls.get("retention_policy", {}).get("status", "owner_approval_pending")),
        ("Suppression round trip", "unimplemented"),
    ]
    colors = {
        "executed": "#009E73", "passed": "#009E73", "offline_tested": "#E69F00",
        "executed_partial": "#E69F00", "incomplete": "#D55E00", "no_records": "#999999",
        "unexecuted": "#999999", "unimplemented": "#CC79A7",
        "owner_confirmation_pending": "#CC79A7", "owner_approval_pending": "#CC79A7",
        "invalid": "#D55E00",
    }
    fig, axis = plt.subplots(figsize=(10, 8), constrained_layout=True)
    y = list(range(len(rows)))
    axis.barh(y, [1] * len(rows), color=[colors.get(status, "#D55E00") for _, status in rows])
    axis.set_yticks(y, [label for label, _ in rows])
    axis.set_xlim(0, 1)
    axis.set_xticks([])
    axis.invert_yaxis()
    axis.set_title("Dissertation evidence status (missing evidence is not zero)")
    for index, (_, status) in enumerate(rows):
        axis.text(0.02, index, status.replace("_", " "), va="center", color="white", fontweight="bold")
    output = ROOT / "evidence/figures/evidence_status.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)

    protocol_rows = {row["dimension"]: row for row in csv.DictReader((ROOT / "evidence/protocol_benchmark.csv").open())}
    fig, axis = plt.subplots(figsize=(7, 4), constrained_layout=True)
    x = [0, 1]
    width = 0.34
    for offset, broker in ((-width / 2, "nats"), (width / 2, "mqtt")):
        values = [float(protocol_rows[metric][broker]) for metric in ("latency_p50_ms", "latency_p99_ms")]
        axis.bar([position + offset for position in x], values, width, label=broker.upper())
    axis.set_xticks(x, ["P50", "P99"])
    axis.set(ylabel="Publish-to-consume latency (ms)", title="Partial local protocol comparison (n=100 each)")
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    protocol_output = ROOT / "evidence/figures/protocol_latency.png"
    fig.savefig(protocol_output, dpi=200)
    plt.close(fig)

    tiers = manifest["scale_tiers"]
    fig, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    positions = list(range(len(tiers)))
    targets = [float(tier["target_rate_msg_s"]) for tier in tiers]
    axis.scatter(positions, targets, marker="x", s=75, color="#666666", label="Target")
    for position, tier in zip(positions, tiers):
        if tier["status"] == "executed":
            axis.scatter(position, float(tier["achieved_rate_msg_s"]), s=80, color="#009E73", label="Achieved" if position == 0 else None)
        else:
            axis.annotate("not executed", (position, targets[position]), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8, color="#777777")
    axis.set_yscale("log")
    axis.set_xticks(positions, [tier["tier"] for tier in tiers])
    axis.set(ylabel="Messages/s (log scale)", xlabel="Scale tier", title="Scale evidence: targets versus executed measurements")
    axis.legend()
    axis.grid(axis="y", alpha=0.2)
    scale_output = ROOT / "evidence/figures/scale_status.png"
    fig.savefig(scale_output, dpi=200)
    plt.close(fig)

    tags = ["patient context", "schema version", "pipeline version", "threshold version", "scoring approach", "scenario", "transport"]
    columns = ["implemented", "unit-tested", "live stored audit"]
    live_value = 2 if traceability["status"] == "passed" else 0
    values = [[2, 2, live_value] for _ in tags]
    fig, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    axis.imshow(values, aspect="auto", cmap=ListedColormap(["#999999", "#E69F00", "#009E73"]), vmin=0, vmax=2)
    axis.set_xticks(range(len(columns)), columns)
    axis.set_yticks(range(len(tags)), tags)
    axis.set_title("Traceability coverage by evidence gate")
    for row in range(len(tags)):
        for column in range(len(columns)):
            axis.text(column, row, "yes" if values[row][column] == 2 else "unexecuted", ha="center", va="center", color="white", fontsize=8, fontweight="bold")
    trace_output = ROOT / "evidence/figures/traceability_status.png"
    fig.savefig(trace_output, dpi=200)
    plt.close(fig)
    architecture_output = ROOT / "evidence/figures/architecture_status.png"
    _architecture_figure(architecture_output)
    print(f"Wrote {output}, {protocol_output}, {scale_output}, {trace_output}, and {architecture_output}")


if __name__ == "__main__":
    main()
