import socket
import struct
from pathlib import Path
from typing import Literal, Protocol


class UploadScannerUnavailable(RuntimeError):
    pass


class UploadRejected(RuntimeError):
    pass


class UploadScanner(Protocol):
    def preflight(self) -> None: ...

    def scan(self, path: Path) -> None: ...


class NoopUploadScanner:
    """Non-production scanner used only when scanning is explicitly optional."""

    def preflight(self) -> None:
        return None

    def scan(self, path: Path) -> None:
        if not path.is_file():
            raise UploadScannerUnavailable("Upload staging file is unavailable")


class DeterministicUploadScanner:
    """Deterministic test double; never selected by production configuration."""

    def __init__(self, verdict: Literal["clean", "infected", "unavailable"] = "clean"):
        self.verdict = verdict

    def preflight(self) -> None:
        if self.verdict == "unavailable":
            raise UploadScannerUnavailable("Scanner unavailable")

    def scan(self, path: Path) -> None:
        self.preflight()
        if not path.is_file():
            raise UploadScannerUnavailable("Upload staging file is unavailable")
        if self.verdict == "infected":
            raise UploadRejected("Upload rejected by scanner")


class ClamdUploadScanner:
    """Minimal clamd INSTREAM client with a bounded network timeout."""

    def __init__(self, host: str, port: int, timeout_seconds: float = 5.0):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def _connect(self):
        try:
            return socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise UploadScannerUnavailable("Scanner unavailable") from exc

    @staticmethod
    def _receive_reply(scanner_socket: socket.socket) -> bytes:
        chunks = []
        while True:
            try:
                chunk = scanner_socket.recv(4096)
            except OSError as exc:
                raise UploadScannerUnavailable("Scanner response failed") from exc
            if not chunk:
                break
            chunks.append(chunk)
            if b"\0" in chunk or b"\n" in chunk:
                break
        return b"".join(chunks).rstrip(b"\0\r\n")

    def preflight(self) -> None:
        with self._connect() as scanner_socket:
            try:
                scanner_socket.sendall(b"zPING\0")
            except OSError as exc:
                raise UploadScannerUnavailable("Scanner preflight failed") from exc
            if self._receive_reply(scanner_socket) != b"PONG":
                raise UploadScannerUnavailable("Scanner preflight failed")

    def scan(self, path: Path) -> None:
        if not path.is_file():
            raise UploadScannerUnavailable("Upload staging file is unavailable")
        with self._connect() as scanner_socket:
            try:
                scanner_socket.sendall(b"zINSTREAM\0")
                with path.open("rb") as candidate:
                    while chunk := candidate.read(1024 * 1024):
                        scanner_socket.sendall(struct.pack("!I", len(chunk)))
                        scanner_socket.sendall(chunk)
                scanner_socket.sendall(struct.pack("!I", 0))
            except OSError as exc:
                raise UploadScannerUnavailable("Scanner stream failed") from exc

            reply = self._receive_reply(scanner_socket)
            if reply.endswith(b" OK"):
                return
            if reply.endswith(b" FOUND"):
                raise UploadRejected("Upload rejected by scanner")
            raise UploadScannerUnavailable("Scanner returned an invalid response")


__all__ = [
    "ClamdUploadScanner",
    "DeterministicUploadScanner",
    "NoopUploadScanner",
    "UploadRejected",
    "UploadScanner",
    "UploadScannerUnavailable",
]
