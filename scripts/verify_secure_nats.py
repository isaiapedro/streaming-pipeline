#!/usr/bin/env python3
"""Create disposable credentials/certificates and verify secure NATS locally."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import ssl
import subprocess
import tempfile
from pathlib import Path

import nats

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_S = 120


async def _connect(*, user=None, password=None, cafile=None):
    context = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    return await nats.connect(
        servers="tls://127.0.0.1:4222",
        user=user,
        password=password,
        tls=context,
        tls_hostname="localhost",
        allow_reconnect=False,
        connect_timeout=2,
        max_reconnect_attempts=0,
    )


async def _must_reject(**kwargs) -> None:
    try:
        connection = await _connect(**kwargs)
    except Exception:
        return
    await connection.close()
    raise RuntimeError("secure NATS unexpectedly accepted a prohibited connection")


async def verify() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="academic-secure-nats-") as directory:
        cert_dir = Path(directory)
        subprocess.run(
            ["bash", "scripts/generate_dev_tls.sh"],
            cwd=PROJECT_ROOT,
            env={**os.environ, "NATS_CERT_DIR": str(cert_dir)},
            check=True,
            timeout=30,
        )
        user = f"test-{secrets.token_hex(8)}"
        password = secrets.token_urlsafe(24)
        compose_env = {
            **os.environ,
            "NATS_USER": user,
            "NATS_PASSWORD": password,
            "NATS_CERT_DIR": str(cert_dir),
        }
        project_name = f"academic-secure-check-{secrets.token_hex(6)}"
        compose = ["docker", "compose", "-p", project_name, "--profile", "secure"]
        try:
            subprocess.run(
                [*compose, "up", "-d", "--wait", "nats-secure"],
                cwd=PROJECT_ROOT,
                env=compose_env,
                check=True,
                timeout=COMMAND_TIMEOUT_S,
            )
            connection = await _connect(
                user=user,
                password=password,
                cafile=str(cert_dir / "nats-cert.pem"),
            )
            await connection.close()
            await _must_reject(cafile=str(cert_dir / "nats-cert.pem"))
            connection = await _connect(
                user=user, password=password, cafile=str(cert_dir / "nats-cert.pem")
            )
            await connection.close()
            await _must_reject(
                user=user,
                password="incorrect-password",
                cafile=str(cert_dir / "nats-cert.pem"),
            )
            connection = await _connect(
                user=user, password=password, cafile=str(cert_dir / "nats-cert.pem")
            )
            await connection.close()
            await _must_reject(user=user, password=password)
            connection = await _connect(
                user=user, password=password, cafile=str(cert_dir / "nats-cert.pem")
            )
            await connection.close()
        finally:
            subprocess.run(
                [*compose, "down", "--remove-orphans"],
                cwd=PROJECT_ROOT,
                env=compose_env,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=COMMAND_TIMEOUT_S,
            )
    return {
        "authenticated": True,
        "anonymous_rejected": True,
        "wrong_password_rejected": True,
        "untrusted_ca_rejected": True,
    }


def main() -> int:
    print(json.dumps(asyncio.run(verify()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
