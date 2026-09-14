import os
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import config.settings as settings
from config.nats_consumers import BRAIN_CONSUMER, NatsConsumerContract
from config.nats_streams import ALARMS_STREAM, VITALS_STREAM


PROJECT_ROOT = Path(__file__).parents[2]


def test_nats_credentials_must_be_configured_as_a_pair(monkeypatch):
    monkeypatch.setattr(settings, "NATS_USER", "operator")
    monkeypatch.setattr(settings, "NATS_PASSWORD", None)

    with pytest.raises(RuntimeError, match="configured together"):
        settings.nats_connection_options()


def test_tls_hostname_is_derived_from_nats_url(monkeypatch):
    sentinel_context = object()
    monkeypatch.setattr(settings, "NATS_URL", "tls://nats.example.test:4222")
    monkeypatch.setattr(settings, "NATS_USER", None)
    monkeypatch.setattr(settings, "NATS_PASSWORD", None)
    monkeypatch.setattr(settings, "NATS_TLS", True)
    monkeypatch.setattr(settings, "NATS_CA_FILE", "/tmp/test-ca.pem")
    monkeypatch.setattr(
        settings.ssl,
        "create_default_context",
        lambda *, cafile: sentinel_context,
    )

    options = settings.nats_connection_options()

    assert options["tls"] is sentinel_context
    assert options["tls_hostname"] == "nats.example.test"


def test_stream_setup_propagates_nats_cli_failures(tmp_path):
    fake_nats = tmp_path / "nats"
    fake_nats.write_text("#!/usr/bin/env sh\nexit 23\n")
    fake_nats.chmod(fake_nats.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts" / "create_streams.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23
    assert "already exists" not in result.stdout


def test_dev_certificate_generator_refuses_silent_overwrite(tmp_path):
    env = {**os.environ, "NATS_CERT_DIR": str(tmp_path)}
    command = ["bash", str(PROJECT_ROOT / "scripts" / "generate_dev_tls.sh")]

    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True, capture_output=True)
    first_key = (tmp_path / "nats-key.pem").read_bytes()
    refused = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False, capture_output=True)

    assert refused.returncode != 0
    assert (tmp_path / "nats-key.pem").read_bytes() == first_key
    assert stat.S_IMODE((tmp_path / "nats-key.pem").stat().st_mode) == 0o600

    subprocess.run(command + ["--force"], cwd=PROJECT_ROOT, env=env, check=True, capture_output=True)


def test_nats_consumer_contract_has_bounded_explicit_acknowledgements():
    config = BRAIN_CONSUMER.as_config()
    assert config.deliver_policy.value == "all"
    assert config.ack_policy.value == "explicit"
    assert config.ack_wait == 30.0
    assert config.max_deliver == 3
    assert config.max_ack_pending == 500
    assert config.filter_subject == "vitals.>"
    assert config.replay_policy.value == "instant"


def test_nats_consumer_contract_rejects_server_configuration_drift():
    contract = NatsConsumerContract("BRAIN")
    drifted = {
        "durable_name": "BRAIN",
        "filter_subject": "vitals.>",
        "deliver_policy": "new",
        "ack_policy": "explicit",
        "ack_wait": 60_000_000_000,
        "max_deliver": 5,
        "max_ack_pending": 1_000,
        "replay_policy": "original",
    }
    with pytest.raises(RuntimeError, match="configuration drift") as error:
        contract.assert_matches(drifted)
    message = str(error.value)
    assert "ack_wait=60.0" in message
    assert "deliver_policy='new'" in message
    assert "max_deliver=5" in message
    assert "max_ack_pending=1000" in message
    assert "replay_policy='original'" in message


def test_nats_consumer_contract_accepts_cli_nanosecond_duration():
    BRAIN_CONSUMER.assert_matches({
        "durable_name": "BRAIN",
        "filter_subject": "vitals.>",
        "deliver_policy": "all",
        "ack_policy": "explicit",
        "ack_wait": 30_000_000_000,
        "max_deliver": 3,
        "max_ack_pending": 500,
        "replay_policy": "instant",
    })


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    [("deliver_policy", "new"), ("replay_policy", "original")],
)
def test_nats_consumer_contract_rejects_delivery_semantic_drift(field, drifted_value):
    actual = {
        "durable_name": "BRAIN",
        "filter_subject": "vitals.>",
        "deliver_policy": "all",
        "ack_policy": "explicit",
        "ack_wait": 30_000_000_000,
        "max_deliver": 3,
        "max_ack_pending": 500,
        "replay_policy": "instant",
    }
    actual[field] = drifted_value

    with pytest.raises(RuntimeError, match=field):
        BRAIN_CONSUMER.assert_matches(actual)


def test_stream_setup_pins_acknowledgement_limits():
    script = (PROJECT_ROOT / "scripts" / "create_streams.sh").read_text()
    assert "--ack explicit" in script
    assert "--wait 30s" in script
    assert "--max-deliver 3" in script
    assert "--max-pending 500" in script
    assert "consumer edit VITALS" in script
    assert "--force" in script
    assert "check_nats_consumer_config.py" in script
    assert "create_or_verify_stream ALARMS" in script
    assert "check_nats_stream_config.py" in script


def test_stream_contract_accepts_cli_nanoseconds_and_rejects_drift():
    VITALS_STREAM.assert_matches({
        "name": "VITALS",
        "subjects": ["vitals.>"],
        "max_age": 86_400_000_000_000,
        "storage": "file",
        "retention": "limits",
        "num_replicas": 1,
    })

    with pytest.raises(RuntimeError, match="configuration drift"):
        ALARMS_STREAM.assert_matches({
            "name": "ALARMS",
            "subjects": ["alarms.>"],
            "max_age": 86_400_000_000_000,
            "storage": "file",
            "retention": "limits",
            "num_replicas": 1,
        })


def test_consumer_config_checker_accepts_contract_and_rejects_drift():
    checker = PROJECT_ROOT / "scripts" / "check_nats_consumer_config.py"
    valid = {
        "config": {
            "durable_name": "BRAIN",
            "filter_subject": "vitals.>",
            "deliver_policy": "all",
            "ack_policy": "explicit",
            "ack_wait": 30_000_000_000,
            "max_deliver": 3,
            "max_ack_pending": 500,
            "replay_policy": "instant",
        }
    }
    command = [sys.executable, str(checker), "BRAIN"]
    accepted = subprocess.run(
        command, cwd=PROJECT_ROOT, input=json.dumps(valid), text=True, capture_output=True
    )
    assert accepted.returncode == 0

    valid["config"]["max_deliver"] = 4
    rejected = subprocess.run(
        command, cwd=PROJECT_ROOT, input=json.dumps(valid), text=True, capture_output=True
    )
    assert rejected.returncode != 0
    assert "configuration drift" in rejected.stderr
