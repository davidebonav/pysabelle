"""Data models for server information."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """Connection information for a running Isabelle server.

    Attributes:
        name: Server name (as given with `-n`).
        host: Hostname or IP address the server is listening on.
        port: TCP port number.
        password: Password required for the initial handshake.
    """

    name: str
    host: str
    port: int
    password: str

    def __repr__(self) -> str:
        # Password intentionally redacted to avoid accidental exposure in logs.
        return (
            f"ServerInfo(name={self.name!r}, host={self.host!r}, "
            f"port={self.port}, password=***)"
        )

    def __str__(self) -> str:
        # Mirrors the wire format emitted by ``isabelle server``.
        return f'server "{self.name}" = {self.host}:{self.port}'
