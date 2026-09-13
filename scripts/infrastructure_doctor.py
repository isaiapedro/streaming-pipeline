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
    "secure": {
        "ports": (4222, 8222),
        "tools": ("docker", "nats", "openssl"),
        "services": ("nats-secure",),
    },
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
    command = [tool, "--version"]
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


def _compose_model(compose_args: list[str], services: tuple[str, ...]) -> tuple[str, list[str], tuple[int, ...]]:
    raw = _run([*compose_args, "config", "--no-interpolate", "--format", "json"])
    model = json.loads(raw)
    selected = {name: model["services"][name] for name in services}
    images = sorted(service["image"] for service in selected.values())
    ports = []
    for service in selected.values():
        for binding in service.get("ports", []):
            published = binding.get("published")
            if published is not None:
                ports.append(int(published))
    sanitized = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return sanitized, images, tuple(sorted(ports))


def _running_services(compose_args: list[str]) -> set[str]:
    return set(filter(None, _run([*compose_args, "ps", "--status", "running", "--services"]).splitlines()))


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
    rendered, images, compose_ports = _compose_model(compose_args, contract["services"])
    if compose_ports != tuple(sorted(contract["ports"])):
        raise RuntimeError(
            f"Compose ports {compose_ports} do not match profile contract {contract['ports']}"
        )
    _registry_status(compose_ports)
    if start:
        already_running = _running_services(compose_args)
        collisions = [
            port
            for port in contract["ports"]
            if _port_ready(port) and not set(contract["services"]).issubset(already_running)
        ]
        if collisions:
            raise RuntimeError(
                f"refusing to start {profile}; owned ports already have an unidentified listener: {collisions}"
            )
        _run([*compose_args, "up", "-d", "--wait", *contract["services"]], capture=False)
        live = True
    inventory: dict[str, object] = {
        "profile": profile,
        "live": live,
        "registry": "verified",
        "compose_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "images": images,
        "tools": {tool: _version(tool) for tool in contract["tools"]},
        "ports": {str(port): "ready" if live and _port_ready(port) else "not_checked" for port in contract["ports"]},
    }
    if live:
        running = _running_services(compose_args)
        missing_services = sorted(set(contract["services"]) - running)
        if missing_services:
            raise RuntimeError(f"profile {profile} services are not running: {missing_services}")
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
    parser.add_argument("--force", action="store_true", help="allow replacing an existing output file")
    args = parser.parse_args()
    payload = json.dumps(
        inspect(args.profile, live=args.live, start=args.start), indent=2, sort_keys=True
    ) + "\n"
    if args.output:
        if args.output.exists() and not args.force:
            raise RuntimeError(f"refusing to overwrite existing inventory: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
