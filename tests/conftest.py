"""Shared fixtures: an in-process fake Isabelle server and integration-test gating."""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from pysabelle.client.client import IsabelleClient

PASSWORD = "fake-password"

#: A handler receives (command, argument, server) and returns the raw bytes to
#: write back (possibly several replies concatenated into a single write).
Handler = Callable[[str, Any, "FakeIsabelleServer"], "bytes | Awaitable[bytes] | None"]


def encode_reply(kind: str, arg: Any = None) -> bytes:
    """Encode a server reply exactly like Isabelle's ``Byte_Message.write_line_message``.

    Messages longer than 100 bytes get a length header that counts the
    trailing newline (``n + 1``), as the real server does.
    """
    text = kind if arg is None else f"{kind} {json.dumps(arg)}"
    body = text.encode("utf-8")
    if len(body) > 100 or b"\n" in body:
        return f"{len(body) + 1}\n".encode("ascii") + body + b"\n"
    return body + b"\n"


class FakeIsabelleServer:
    """Minimal scripted TCP server speaking the Isabelle server protocol (§4.2)."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.received: list[tuple[str, Any]] = []
        self._ids = itertools.count(1)
        self._server: asyncio.base_events.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self.port = 0
        self.disconnects = 0

    def new_task(self) -> str:
        return f"00000000-0000-0000-0000-{next(self._ids):012d}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._on_connect, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        for w in self._writers:
            w.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_connections(self) -> None:
        """Close every client connection (simulates a server crash)."""
        for w in self._writers:
            w.close()

    async def wait_disconnect(self, n: int = 1) -> bool:
        for _ in range(200):
            if self.disconnects >= n:
                return True
            await asyncio.sleep(0.01)
        return False

    def commands(self, name: str) -> list[Any]:
        """Arguments of all received commands with the given name."""
        return [arg for cmd, arg in self.received if cmd == name]

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)
        password = (await reader.readline()).decode().strip()
        if password != PASSWORD:
            writer.close()  # silent disconnection, as in §4.2.4
            return
        writer.write(encode_reply("OK", {"isabelle_id": "fake", "isabelle_name": "Fake"}))
        await writer.drain()

        while True:
            header = await reader.readline()
            if not header:
                self.disconnects += 1
                break
            stripped = header.strip()
            if stripped.isdigit():
                text = (await reader.readexactly(int(stripped))).decode("utf-8")
            else:
                text = header.decode("utf-8")
            text = text.rstrip("\r\n")
            if not text:
                # what the real server does with an empty message (server.scala)
                self.received.append(("", None))
                note = {"message": "Command 'help' provides list of commands", "kind": "writeln"}
                writer.write(encode_reply("NOTE", note))
                await writer.drain()
                continue
            name, _, rest = text.partition(" ")
            arg = json.loads(rest) if rest.strip() else None
            self.received.append((name, arg))

            out = self.handler(name, arg, self)
            if inspect.isawaitable(out):
                out = await out
            if out:
                writer.write(out)  # one single write: replies may share a TCP segment
                await writer.drain()


# ---------------------------------------------------------------------------
# Canned payloads
# ---------------------------------------------------------------------------

def node_status(ok: bool = True) -> dict[str, Any]:
    return {
        "ok": ok, "total": 3, "unprocessed": 0, "running": 0, "warned": 0,
        "failed": 0 if ok else 1, "finished": 3 if ok else 2, "canceled": False,
        "consolidated": True, "percentage": 100,
    }


def node_entry(node_name: str, theory_name: str, ok: bool = True) -> dict[str, Any]:
    return {
        "node_name": node_name, "theory_name": theory_name,
        "status": node_status(ok), "messages": [], "exports": [],
    }


SESSION_ID = "11111111-1111-1111-1111-111111111111"
TMP_DIR = "/tmp/fake_session"


def default_handler(overrides: dict[str, Handler] | None = None) -> Handler:
    """Handler implementing a plausible happy path; ``overrides`` replace single commands."""
    overrides = overrides or {}

    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes | Awaitable[bytes] | None:
        if name in overrides:
            return overrides[name](name, arg, srv)
        if name == "help":
            return encode_reply("OK", ["cancel", "echo", "help", "purge_theories"])
        if name == "echo":
            return encode_reply("OK", arg)
        if name == "cancel":
            return encode_reply("OK")
        if name == "session_start":
            t = srv.new_task()
            return encode_reply("OK", {"task": t}) + encode_reply(
                "FINISHED", {"task": t, "session_id": SESSION_ID, "tmp_dir": TMP_DIR}
            )
        if name == "session_stop":
            t = srv.new_task()
            return encode_reply("OK", {"task": t}) + encode_reply(
                "FINISHED", {"task": t, "ok": True, "return_code": 0}
            )
        if name == "use_theories":
            t = srv.new_task()
            return encode_reply("OK", {"task": t}) + encode_reply(
                "FINISHED", {"task": t, "ok": True, "errors": [], "nodes": []}
            )
        if name == "purge_theories":
            return encode_reply("OK", {"purged": [], "retained": []})
        return encode_reply("ERROR", {"kind": "error", "message": f"Bad command {name!r}"})

    return handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def fake_server_factory():
    """Factory fixture: ``srv = await fake_server_factory(handler)``."""
    servers: list[FakeIsabelleServer] = []

    async def make(handler: Handler | None = None) -> FakeIsabelleServer:
        srv = FakeIsabelleServer(handler or default_handler())
        await srv.start()
        servers.append(srv)
        return srv

    yield make
    for srv in servers:
        await srv.close()


@pytest.fixture
async def client_factory(fake_server_factory):
    """Factory fixture returning ``(client, server)`` with the dispatcher started."""
    clients: list[IsabelleClient] = []

    async def make(handler: Handler | None = None) -> tuple[IsabelleClient, FakeIsabelleServer]:
        srv = await fake_server_factory(handler)
        client = await IsabelleClient.connect("127.0.0.1", srv.port, PASSWORD)
        await client.__aenter__()
        clients.append(client)
        return client, srv

    yield make
    for c in clients:
        await c.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Integration tests against a real local Isabelle
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("isabelle") is not None:
        return
    skip = pytest.mark.skip(reason="'isabelle' executable not found on PATH")
    for item in items:
        if "isabelle" in item.keywords:
            item.add_marker(skip)
