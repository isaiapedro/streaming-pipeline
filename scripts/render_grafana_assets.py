#!/usr/bin/env python3
"""Render governed Grafana templates without embedding credentials."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "__INFLUX_BUCKET__"
ASSETS = (
    Path("dashboards/dashboard.yml"),
    Path("dashboards/vitals.json"),
    Path("dashboards/comparison.json"),
    Path("alerting/rules.yml"),
    Path("datasources/influxdb.yml"),
)
TEMPLATED_ASSETS = {
    Path("dashboards/vitals.json"),
    Path("dashboards/comparison.json"),
    Path("alerting/rules.yml"),
}
BUCKET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def render_assets(bucket: str, output_dir: Path) -> list[Path]:
    if not BUCKET_PATTERN.fullmatch(bucket):
        raise ValueError("INFLUX_BUCKET must use 1-128 letters, digits, dots, underscores, or hyphens")
    source_dir = ROOT / "grafana" / "provisioning"
    prepared: list[tuple[Path, str]] = []
    for relative in ASSETS:
        source = source_dir / relative
        content = source.read_text()
        if relative in TEMPLATED_ASSETS:
            if TOKEN not in content:
                raise RuntimeError(f"missing governed bucket token in {relative}")
            content = content.replace(TOKEN, bucket)
            if TOKEN in content:
                raise RuntimeError(f"unresolved governed bucket token in {relative}")
        prepared.append((relative, content))

    # Validate every source before touching the output tree. A bad template can
    # therefore never leave a plausible-looking, partially rendered bundle.
    rendered: list[Path] = []
    for relative, content in prepared:
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        rendered.append(destination)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=os.getenv("INFLUX_BUCKET"))
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / ".runtime" / "grafana" / "provisioning",
    )
    args = parser.parse_args()
    if not args.bucket:
        parser.error("set INFLUX_BUCKET or pass --bucket")
    paths = render_assets(args.bucket, args.output_dir)
    print(f"Rendered {len(paths)} Grafana assets with governed bucket configuration")


if __name__ == "__main__":
    main()
