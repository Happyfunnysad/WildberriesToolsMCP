"""PID 1 supervisor for the MCP server and optional Xray egress rotator."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    python = sys.executable
    server_cmd = [python, "/app/server.py"]

    if not env_bool("XRAY_ENABLED", default=True):
        os.execv(python, server_cmd)
        return 0

    ready_file = Path(os.getenv("XRAY_READY_FILE", "/tmp/xray-ready"))
    startup_timeout = int(os.getenv("XRAY_STARTUP_TIMEOUT", "180"))
    ready_file.unlink(missing_ok=True)

    rotator = subprocess.Popen([python, "/app/proxy/rotator.py"])
    server: subprocess.Popen[bytes] | None = None
    stopping = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        if server is not None and server.poll() is None:
            server.send_signal(signum)
        if rotator.poll() is None:
            rotator.send_signal(signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline and not stopping:
        if rotator.poll() is not None:
            print(
                f"Xray rotator exited before readiness with code {rotator.returncode}",
                file=sys.stderr,
                flush=True,
            )
            return rotator.returncode or 1
        if ready_file.exists():
            break
        time.sleep(0.5)
    else:
        if not stopping:
            print(
                f"Timed out after {startup_timeout}s waiting for a validated VLESS route",
                file=sys.stderr,
                flush=True,
            )
        terminate(rotator)
        return 1

    if stopping:
        terminate(rotator)
        return 0

    server = subprocess.Popen(server_cmd)

    try:
        while not stopping:
            server_code = server.poll()
            rotator_code = rotator.poll()

            if server_code is not None:
                terminate(rotator)
                return server_code
            if rotator_code is not None:
                print(
                    f"Xray rotator exited with code {rotator_code}; stopping MCP server",
                    file=sys.stderr,
                    flush=True,
                )
                terminate(server)
                return rotator_code or 1
            time.sleep(0.5)
    finally:
        terminate(server)
        terminate(rotator)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
