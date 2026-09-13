"""Static, privacy-safe tests for infrastructure preflight inventory."""

import json

import pytest

from scripts import infrastructure_doctor as doctor
from scripts import verify_secure_nats as secure


def test_compose_inventory_selects_only_profile_services_and_never_interpolates(monkeypatch):
    commands = []
    model = {
        "services": {
            "nats": {
                "image": "nats@sha256:test",
                "environment": {"PASSWORD": "${NATS_PASSWORD}"},
                "ports": [
                    {"published": "4222", "target": 4222},
                    {"published": "8222", "target": 8222},
                ],
            },
            "mosquitto": {"image": "mqtt@sha256:test", "ports": []},
        }
    }

    def run(command, capture=True):
        commands.append(command)
        return json.dumps(model)

    monkeypatch.setattr(doctor, "_run", run)
    rendered, images, ports = doctor._compose_model(
        ["docker", "compose"], ("nats",)
    )

    assert commands == [["docker", "compose", "config", "--no-interpolate", "--format", "json"]]
    assert "mosquitto" not in rendered
    assert "secret-value" not in rendered
    assert images == ["nats@sha256:test"]
    assert ports == (4222, 8222)


def test_doctor_rejects_listener_not_owned_by_selected_compose_service(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _tool: "/bin/tool")
    monkeypatch.setattr(
        doctor,
        "_compose_model",
        lambda _args, _services: ("{}", ["nats@sha256:test"], (4222, 8222)),
    )
    monkeypatch.setattr(doctor, "_registry_status", lambda _ports: "verified")
    monkeypatch.setattr(doctor, "_running_services", lambda _args: set())
    monkeypatch.setattr(doctor, "_port_ready", lambda port: port == 4222)

    with pytest.raises(RuntimeError, match="unidentified listener"):
        doctor.inspect("nats", live=False, start=True)


@pytest.mark.asyncio
async def test_secure_verifier_uses_ephemeral_project_and_removes_container(monkeypatch):
    commands = []
    expected_password = None

    def run(command, **kwargs):
        nonlocal expected_password
        commands.append(command)
        expected_password = kwargs.get("env", {}).get("NATS_PASSWORD", expected_password)

    class Connection:
        async def close(self):
            return None

    async def connect(*, user=None, password=None, cafile=None):
        if cafile and user and password == expected_password:
            return Connection()
        raise RuntimeError("connection rejected")

    monkeypatch.setattr(secure.subprocess, "run", run)
    monkeypatch.setattr(secure, "_connect", connect)

    result = await secure.verify()

    compose_commands = [command for command in commands if command[:2] == ["docker", "compose"]]
    assert len(compose_commands) == 2
    assert compose_commands[0][2] == "-p"
    assert compose_commands[0][3].startswith("academic-secure-check-")
    assert compose_commands[1][2:4] == compose_commands[0][2:4]
    assert "up" in compose_commands[0]
    assert "down" in compose_commands[1]
    assert result == {
        "authenticated": True,
        "anonymous_rejected": True,
        "wrong_password_rejected": True,
        "untrusted_ca_rejected": True,
    }
