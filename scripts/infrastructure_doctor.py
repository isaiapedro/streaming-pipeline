#!/usr/bin/env python3
"""Fail-closed, privacy-safe preflight for local academic infrastructure."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]

PROFILES = {
    "nats": {"ports": (4222, 8222), "tools": ("docker", "nats"), "services": ("nats",)},
    "secure": {"ports": (4222, 8222), "tools": ("docker", "nats"), "services": ("nats-secure",)},
    "mqtt": {"ports": (1883,), "tools": ("docker",), "services": ("mosquitto",)},
    "kafka": {
        "ports": (18081, 19092),
        "tools": ("docker",),
        "services": ("kafka", "schema-registry"),
    },
}


def _run(command: list[str], *, capture: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout


def _version(tool: str) -> str:
    command = [tool, "--version"] if tool != "docker" else [tool, "version", "--format", "{{.Client.Version}}"]
    return _run(command).strip().splitlines()[0]


def _registry_status(ports: tuple[int, ...]) -> str:
    catalog = WORKSPACE_ROOT / "registry" / "PORTS.md"
    if not catalog.exists():
        return "parent_registry_unavailable"
    text = catalog.read_text()
    missing = [port for port in ports if f"| {port} | Academic workspace |" not in text]
    if missing:
        raise RuntimeError(f"ports absent from Academic Registry allocation: {missing}")
    return "verified"


def _port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def inspect(profile: str, *, live: bool, start: bool = False) -> dict[str, object]:
    contract = PROFILES[profile]
    missing_tools = [tool for tool in contract["tools"] if shutil.which(tool) is None]
    if missing_tools:
        raise RuntimeError(f"required tools unavailable: {', '.join(missing_tools)}")
    compose_args = ["docker", "compose"]
    if profile in {"kafka", "secure"}:
        compose_args += ["--profile", profile]
    if start:
        _run([*compose_args, "up", "-d", "--wait", *contract["services"]], capture=False)
        live = True
    rendered = _run([*compose_args, "config"])
    images = sorted(filter(None, _run([*compose_args, "config", "--images"]).splitlines()))
    inventory: dict[str, object] = {
        "profile": profile,
        "live": live,
        "registry": _registry_status(contract["ports"]),
        "compose_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "images": images,
        "tools": {tool: _version(tool) for tool in contract["tools"]},
        "ports": {str(port): "ready" if live and _port_ready(port) else "not_checked" for port in contract["ports"]},
    }
    if live:
        unavailable = [port for port in contract["ports"] if not _port_ready(port)]
        if unavailable:
            raise RuntimeError(f"profile {profile} endpoints unavailable: {unavailable}")
        if profile in {"nats", "secure"}:
            _run(["bash", "scripts/create_streams.sh"], capture=False)
        elif profile == "kafka":
            _run(["bash", "scripts/create_kafka_topics.sh"], capture=False)
            _run([sys.executable, "-m", "kafka_path.provision"], capture=False)
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--start",
        action="store_true",
        help="start only the selected profile services, wait for health, then run live checks",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(
        inspect(args.profile, live=args.live, start=args.start), indent=2, sort_keys=True
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
