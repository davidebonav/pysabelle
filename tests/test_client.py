"""Client-level tests against the fake server (handshake, sync commands)."""

from __future__ import annotations

import pytest

from pysabelle.client.client import IsabelleClient
from pysabelle.raw.exceptions import IsabelleCommandError, IsabelleConnectionError


async def test_handshake_and_echo(client_factory) -> None:
    client, srv = await client_factory()
    assert await client.echo({"a": [1, 2, 3]}) == {"a": [1, 2, 3]}
    assert "help" in await client.help()
    assert srv.commands("echo") == [{"a": [1, 2, 3]}]
    # regression: no stray empty message after each long message
    assert [name for name, _ in srv.received] == ["echo", "help"]


async def test_wrong_password(fake_server_factory) -> None:
    srv = await fake_server_factory()
    with pytest.raises(IsabelleConnectionError):
        await IsabelleClient.connect("127.0.0.1", srv.port, "wrong")


async def test_error_reply(client_factory) -> None:
    client, _ = await client_factory()
    with pytest.raises(IsabelleCommandError) as exc_info:
        await client._dispatcher.run_sync("no_such_command")
    assert exc_info.value.kind == "ERROR"
