"""Silent container health probes: no credentials, proxy use, or diagnostic output."""

from __future__ import annotations

import http.client
import ipaddress
import os
import re
import stat
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

WEB_PORT = 5000
# This is the worker's private container tmpfs marker, checked with lstat below
# so the read-only probe never follows a link or creates an insecure temp file.
HEARTBEAT_PATH = Path("/tmp/litblogs-worker-heartbeat")  # nosec B108
WORKER_MAX_AGE_SECONDS = 1500.0


def origin_host(origin: str) -> str:
    """Return an HTTP Host value only from an unambiguous root HTTPS origin."""
    if not origin or re.search(r"[\s\x00-\x1f\x7f]", origin):
        raise ValueError("Invalid healthcheck origin")
    parsed = urlsplit(origin)
    hostname = parsed.hostname
    if (
        parsed.scheme != "https" or not hostname or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
    ):
        raise ValueError("Invalid healthcheck origin")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if len(hostname) > 253 or not all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in hostname.split(".")
        ):
            raise ValueError("Invalid healthcheck origin") from None
        host = hostname
    else:
        host = f"[{hostname}]" if address.version == 6 else hostname
    port = parsed.port
    if port is not None:
        if not 1 <= port <= 65535:
            raise ValueError("Invalid healthcheck origin")
        host = f"{host}:{port}"
    return host


def worker_healthy(path: Path = HEARTBEAT_PATH, *, max_age: float = WORKER_MAX_AGE_SECONDS) -> bool:
    try:
        information = path.lstat()
        age = time.time() - information.st_mtime
        return stat.S_ISREG(information.st_mode) and 0 <= age <= max_age
    except OSError:
        return False


def web_healthy() -> bool:
    connection = None
    try:
        host = origin_host(os.environ.get("LITBLOGS_ORIGIN") or os.environ.get("FRONTEND_URL", ""))
        # HTTPConnection is direct: it never consults proxy environment variables
        # and does not follow redirects away from the fixed loopback endpoint.
        connection = http.client.HTTPConnection("127.0.0.1", WEB_PORT, timeout=5.0)
        connection.request("GET", "/api/health/ready", headers={"Host": host, "Accept": "application/json"})
        response = connection.getresponse()
        try:
            return response.status == 200
        finally:
            response.close()
    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if arguments == ["web"]:
            return 0 if web_healthy() else 1
        if arguments == ["worker"]:
            return 0 if worker_healthy() else 1
    except Exception:
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
