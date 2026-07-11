"""Manage an Xray VLESS egress with subscription refresh, validation, and rotation.

The rotator downloads a text subscription containing vless:// links, converts each
candidate to an Xray JSON config, validates the config with `xray run -test`, then
performs a live HTTP probe through a temporary Xray SOCKS listener before making
that candidate active.
"""

from __future__ import annotations

import json
import logging
import os
import random
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [xray-rotator] %(message)s",
)
logger = logging.getLogger("xray-rotator")

DEFAULT_SUBSCRIPTION = (
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/"
    "main/BLACK_VLESS_RUS_mobile.txt"
)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def first(query: dict[str, list[str]], *names: str, default: str = "") -> str:
    for name in names:
        values = query.get(name)
        if values:
            return values[0]
    return default


def truthy_query(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_vless_uri(uri: str, socks_port: int) -> dict[str, Any]:
    """Convert a VLESS share URI into a minimal Xray client configuration.

    Unsupported transports raise ValueError so the rotator can skip the candidate.
    The source list is heterogeneous by design; accepting a subset and validating it
    with Xray is safer than silently generating invalid JSON for every exotic option.
    """

    parsed = urllib.parse.urlsplit(uri.strip())
    if parsed.scheme.lower() != "vless":
        raise ValueError("not a vless URI")
    if not parsed.username or not parsed.hostname or parsed.port is None:
        raise ValueError("VLESS URI is missing id, host, or port")

    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    network = first(query, "type", default="tcp").lower()
    if network == "raw":
        network = "tcp"
    if network == "splithttp":
        network = "xhttp"

    supported_networks = {"tcp", "ws", "grpc", "xhttp", "httpupgrade"}
    if network not in supported_networks:
        raise ValueError(f"unsupported transport: {network}")

    encryption = first(query, "encryption", default="none") or "none"
    user: dict[str, Any] = {
        "id": urllib.parse.unquote(parsed.username),
        "encryption": encryption,
    }

    flow = first(query, "flow")
    if flow:
        user["flow"] = flow

    packet_encoding = first(query, "packetEncoding", "packetencoding")
    if packet_encoding:
        user["packetEncoding"] = packet_encoding

    outbound: dict[str, Any] = {
        "tag": "proxy",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": parsed.hostname,
                    "port": parsed.port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": {
            "network": network,
            "security": first(query, "security", default="none").lower(),
        },
    }

    stream = outbound["streamSettings"]
    path = urllib.parse.unquote(first(query, "path", default="/")) or "/"
    host_header = first(query, "host")

    if network == "ws":
        ws_settings: dict[str, Any] = {"path": path}
        if host_header:
            ws_settings["headers"] = {"Host": host_header}
        stream["wsSettings"] = ws_settings
    elif network == "grpc":
        service_name = first(query, "serviceName", "servicename") or path.lstrip("/")
        grpc_settings: dict[str, Any] = {"serviceName": service_name}
        authority = first(query, "authority") or host_header
        if authority:
            grpc_settings["authority"] = authority
        if first(query, "mode").lower() == "multi":
            grpc_settings["multiMode"] = True
        stream["grpcSettings"] = grpc_settings
    elif network == "xhttp":
        xhttp_settings: dict[str, Any] = {"path": path}
        if host_header:
            xhttp_settings["host"] = host_header
        mode = first(query, "mode")
        if mode and mode.lower() != "auto":
            xhttp_settings["mode"] = mode
        extra = first(query, "extra")
        if extra:
            try:
                xhttp_settings["extra"] = json.loads(urllib.parse.unquote(extra))
            except json.JSONDecodeError:
                logger.debug("Ignoring malformed XHTTP extra field")
        stream["xhttpSettings"] = xhttp_settings
    elif network == "httpupgrade":
        hu_settings: dict[str, Any] = {"path": path}
        if host_header:
            hu_settings["host"] = host_header
        stream["httpupgradeSettings"] = hu_settings

    security = stream["security"]
    if security == "tls":
        tls_settings: dict[str, Any] = {
            "serverName": first(query, "sni") or parsed.hostname,
        }
        fingerprint = first(query, "fp")
        if fingerprint:
            tls_settings["fingerprint"] = fingerprint
        alpn = first(query, "alpn")
        if alpn:
            tls_settings["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
        insecure = first(query, "allowInsecure", "allowinsecure", "insecure")
        if insecure:
            tls_settings["allowInsecure"] = truthy_query(insecure)
        stream["tlsSettings"] = tls_settings
    elif security == "reality":
        public_key = first(query, "pbk", "publicKey", "publickey")
        server_name = first(query, "sni")
        if not public_key or not server_name:
            raise ValueError("REALITY candidate is missing pbk or sni")
        reality_settings: dict[str, Any] = {
            "serverName": server_name,
            "publicKey": public_key,
        }
        fingerprint = first(query, "fp", default="chrome")
        if fingerprint:
            reality_settings["fingerprint"] = fingerprint
        short_id = first(query, "sid", "shortId", "shortid")
        if short_id:
            reality_settings["shortId"] = short_id
        spider_x = first(query, "spx", "spiderX", "spiderx")
        if spider_x:
            reality_settings["spiderX"] = urllib.parse.unquote(spider_x)
        stream["realitySettings"] = reality_settings
    elif security not in {"", "none"}:
        raise ValueError(f"unsupported security layer: {security}")

    return {
        "log": {"loglevel": os.getenv("XRAY_LOG_LEVEL", "warning")},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": True},
            }
        ],
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": ["socks-in"],
                    "outboundTag": "proxy",
                }
            ],
        },
    }


def candidate_label(uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    label = urllib.parse.unquote(parsed.fragment) if parsed.fragment else "unnamed"
    host = parsed.hostname or "unknown-host"
    return f"{label} ({host}:{parsed.port or '?'})"


class XrayRotator:
    def __init__(self) -> None:
        self.xray_bin = os.getenv("XRAY_BIN", "/usr/local/bin/xray")
        self.subscription_url = os.getenv("XRAY_SUBSCRIPTION_URL", DEFAULT_SUBSCRIPTION)
        self.validation_url = os.getenv("XRAY_VALIDATION_URL", "https://www.wildberries.ru/")
        self.ip_check_url = os.getenv("XRAY_IP_CHECK_URL", "").strip()
        self.active_port = env_int("XRAY_SOCKS_PORT", 1080)
        self.test_port = env_int("XRAY_TEST_SOCKS_PORT", 1081)
        self.rotate_interval = env_int("XRAY_ROTATE_INTERVAL", 900)
        self.health_interval = env_int("XRAY_HEALTH_INTERVAL", 60)
        self.feed_refresh_interval = env_int("XRAY_FEED_REFRESH_INTERVAL", 7200)
        self.max_candidates = env_int("XRAY_MAX_CANDIDATES", 15)
        self.probe_timeout = env_int("XRAY_PROBE_TIMEOUT", 12)
        self.max_http_status = env_int("XRAY_VALIDATE_STATUS_MAX", 399)
        self.health_failures_before_rotate = env_int("XRAY_HEALTH_FAILURES", 2)
        self.workdir = Path(os.getenv("XRAY_WORKDIR", "/tmp/xray-rotator"))
        self.ready_file = Path(os.getenv("XRAY_READY_FILE", "/tmp/xray-ready"))
        self.cache_file = self.workdir / "subscription.txt"
        self.active_config_path = self.workdir / "active.json"
        self.test_config_path = self.workdir / "candidate.json"
        self.log_path = self.workdir / "xray.log"
        self.stop_requested = False
        self.active_process: subprocess.Popen[bytes] | None = None
        self.active_uri: str | None = None
        self.candidates: list[str] = []
        self.workdir.mkdir(parents=True, exist_ok=True)

    def request_stop(self, *_: object) -> None:
        self.stop_requested = True

    def fetch_subscription(self) -> list[str]:
        logger.info("Refreshing VLESS subscription: %s", self.subscription_url)
        request = urllib.request.Request(
            self.subscription_url,
            headers={"User-Agent": "WildberriesToolsMCP-XrayRotator/1.0"},
        )
        text: str
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8", errors="replace")
            self.cache_file.write_text(text, encoding="utf-8")
        except (OSError, urllib.error.URLError) as exc:
            if not self.cache_file.exists():
                raise RuntimeError(f"subscription download failed: {exc}") from exc
            logger.warning("Subscription refresh failed, using cached copy: %s", exc)
            text = self.cache_file.read_text(encoding="utf-8")

        candidates = [
            line.strip()
            for line in text.splitlines()
            if line.strip().lower().startswith("vless://")
        ]
        candidates = list(dict.fromkeys(candidates))
        random.shuffle(candidates)
        logger.info("Loaded %d unique VLESS candidates", len(candidates))
        return candidates

    def write_config(self, path: Path, config: dict[str, Any]) -> None:
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def syntax_test(self, path: Path) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                [self.xray_bin, "run", "-test", "-config", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        output = (result.stdout or "").strip()
        return result.returncode == 0, output[-1200:]

    def start_xray(self, path: Path) -> subprocess.Popen[bytes]:
        log_handle = self.log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            [self.xray_bin, "run", "-config", str(path)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        log_handle.close()
        return process

    @staticmethod
    def stop_process(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    @staticmethod
    def wait_for_port(port: int, process: subprocess.Popen[bytes], timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    def probe(self, port: int, url: str | None = None) -> tuple[bool, str]:
        target = url or self.validation_url
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--connect-timeout",
            str(max(3, self.probe_timeout // 2)),
            "--max-time",
            str(self.probe_timeout),
            "--proxy",
            f"socks5h://127.0.0.1:{port}",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            target,
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.probe_timeout + 5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)

        status_text = (result.stdout or "").strip()
        try:
            status = int(status_text)
        except ValueError:
            status = 0
        ok = result.returncode == 0 and 200 <= status <= self.max_http_status
        detail = f"HTTP {status or 'unknown'}"
        if not ok and result.stderr:
            detail += f"; {result.stderr.strip()[-500:]}"
        return ok, detail

    def egress_ip(self, port: int) -> str | None:
        if not self.ip_check_url:
            return None
        try:
            result = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    str(self.probe_timeout),
                    "--proxy",
                    f"socks5h://127.0.0.1:{port}",
                    self.ip_check_url,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.probe_timeout + 5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (result.stdout or "").strip()
        return value[:200] if result.returncode == 0 and value else None

    def validate_candidate(self, uri: str) -> dict[str, Any] | None:
        label = candidate_label(uri)
        try:
            config = parse_vless_uri(uri, self.test_port)
        except (ValueError, TypeError) as exc:
            logger.debug("Skipping %s: %s", label, exc)
            return None

        self.write_config(self.test_config_path, config)
        syntax_ok, syntax_output = self.syntax_test(self.test_config_path)
        if not syntax_ok:
            logger.debug("Xray rejected %s: %s", label, syntax_output)
            return None

        process = self.start_xray(self.test_config_path)
        try:
            if not self.wait_for_port(self.test_port, process):
                logger.debug("Candidate Xray failed to listen: %s", label)
                return None
            probe_ok, detail = self.probe(self.test_port)
            if not probe_ok:
                logger.info("Candidate failed live probe: %s -> %s", label, detail)
                return None
            logger.info("Candidate validated: %s -> %s", label, detail)
            return parse_vless_uri(uri, self.active_port)
        finally:
            self.stop_process(process)

    def activate(self, uri: str, config: dict[str, Any]) -> bool:
        label = candidate_label(uri)
        staged_path = self.workdir / "active.next.json"
        self.write_config(staged_path, config)
        syntax_ok, syntax_output = self.syntax_test(staged_path)
        if not syntax_ok:
            logger.warning("Refusing activation; Xray rejected staged config %s: %s", label, syntax_output)
            return False

        previous_config = self.active_config_path.read_text(encoding="utf-8") if self.active_config_path.exists() else None
        previous_uri = self.active_uri
        self.stop_process(self.active_process)
        self.active_process = None
        staged_path.replace(self.active_config_path)

        process = self.start_xray(self.active_config_path)
        if self.wait_for_port(self.active_port, process):
            probe_ok, detail = self.probe(self.active_port)
            if probe_ok:
                self.active_process = process
                self.active_uri = uri
                self.ready_file.write_text("ready\n", encoding="utf-8")
                egress_ip = self.egress_ip(self.active_port)
                if egress_ip:
                    logger.info("Activated %s; egress=%s", label, egress_ip)
                else:
                    logger.info("Activated %s", label)
                return True
            logger.warning("Activated process failed final probe: %s -> %s", label, detail)
        else:
            logger.warning("Activated process failed to listen: %s", label)

        self.stop_process(process)

        if previous_config is not None:
            logger.warning("Rolling back to previous Xray configuration")
            self.active_config_path.write_text(previous_config, encoding="utf-8")
            rollback = self.start_xray(self.active_config_path)
            if self.wait_for_port(self.active_port, rollback):
                self.active_process = rollback
                self.active_uri = previous_uri
                self.ready_file.write_text("ready\n", encoding="utf-8")
                return False
            self.stop_process(rollback)

        self.ready_file.unlink(missing_ok=True)
        self.active_uri = None
        return False

    def rotate(self) -> bool:
        if not self.candidates:
            self.candidates = self.fetch_subscription()

        pool = [candidate for candidate in self.candidates if candidate != self.active_uri]
        random.shuffle(pool)
        attempts = 0
        for uri in pool:
            if self.stop_requested:
                return False
            attempts += 1
            if attempts > self.max_candidates:
                break
            config = self.validate_candidate(uri)
            if config is None:
                continue
            if self.activate(uri, config):
                return True

        logger.error("No usable VLESS candidate found after %d attempts", attempts)
        return False

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        self.ready_file.unlink(missing_ok=True)

        try:
            self.candidates = self.fetch_subscription()
        except Exception as exc:
            logger.error("Initial subscription fetch failed: %s", exc)

        while not self.stop_requested and self.active_process is None:
            try:
                if self.rotate():
                    break
            except Exception:
                logger.exception("Initial VLESS rotation failed")
            if not self.stop_requested:
                time.sleep(15)

        if self.stop_requested:
            return 0

        next_rotation = time.monotonic() + self.rotate_interval
        next_health = time.monotonic() + self.health_interval
        next_feed_refresh = time.monotonic() + self.feed_refresh_interval
        health_failures = 0

        while not self.stop_requested:
            now = time.monotonic()

            if self.active_process is None or self.active_process.poll() is not None:
                logger.warning("Active Xray process exited; rotating immediately")
                self.ready_file.unlink(missing_ok=True)
                self.active_process = None
                try:
                    self.rotate()
                except Exception:
                    logger.exception("Recovery rotation failed")
                next_health = time.monotonic() + self.health_interval
                time.sleep(2)
                continue

            if now >= next_feed_refresh:
                try:
                    self.candidates = self.fetch_subscription()
                except Exception:
                    logger.exception("Subscription refresh failed")
                next_feed_refresh = now + self.feed_refresh_interval

            if now >= next_health:
                ok, detail = self.probe(self.active_port)
                if ok:
                    health_failures = 0
                    logger.debug("Active VLESS health check OK: %s", detail)
                else:
                    health_failures += 1
                    logger.warning(
                        "Active VLESS health check failed (%d/%d): %s",
                        health_failures,
                        self.health_failures_before_rotate,
                        detail,
                    )
                    if health_failures >= self.health_failures_before_rotate:
                        self.rotate()
                        health_failures = 0
                        next_rotation = time.monotonic() + self.rotate_interval
                next_health = time.monotonic() + self.health_interval

            if now >= next_rotation:
                logger.info("Periodic VLESS rotation started")
                self.rotate()
                next_rotation = time.monotonic() + self.rotate_interval
                next_health = time.monotonic() + self.health_interval

            time.sleep(1)

        self.ready_file.unlink(missing_ok=True)
        self.stop_process(self.active_process)
        return 0


def main() -> None:
    try:
        code = XrayRotator().run()
    except Exception:
        logger.exception("Fatal Xray rotator error")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
