#!/usr/bin/env python3
"""Serve one presentation artifact directory on an unused loopback port.

The root workspace reserves fixed ports for named services. Presentation-only
static files therefore use port 0, which asks the operating system to choose a
currently unused ephemeral development port.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIRECTORIES = {
    "benchmarks": ROOT / "evidence/figures",
    "distribution": ROOT / ".runtime/presentation/distribution",
    "noise": ROOT / ".runtime/presentation/noise_injection",
}


def content_directory(name: str) -> Path:
    directory = CONTENT_DIRECTORIES[name]
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Presentation directory does not exist: {directory}. "
            "Generate that visualization before starting its server."
        )
    return directory


def serve(name: str) -> None:
    directory = content_directory(name)
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        print(f"Serving {name} from {directory}", flush=True)
        print(f"Open http://127.0.0.1:{port}/", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", choices=sorted(CONTENT_DIRECTORIES))
    args = parser.parse_args()
    serve(args.content)


if __name__ == "__main__":
    main()
