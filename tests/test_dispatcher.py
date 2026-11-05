"""TaskDispatcher tests against the fake server."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pysabelle.raw.exceptions import (
    IsabelleCommandError,
    IsabelleConnectionError,
    IsabelleTaskCancelled,
    IsabelleTimeoutError,
)
from pysabelle.raw.protocol import RawReply

from .conftest import FakeIsabelleServer, default_handler, encode_reply


def _async_cmd(*tail: tuple[str, dict[str, Any]]):
    """Handler replying ``OK {task}`` followed by ``tail`` replies in the SAME write."""
    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        t = srv.new_task()
        out = encode_reply("OK", {"task": t})
        for kind, payload in tail:
            out += encode_reply(kind, {"task": t, **payload})
        return out
    return handler


async def test_terminal_reply_in_same_segment_as_ok(client_factory) -> None:
    """Regression (C1): FINISHED right after OK used to be dropped -> hang forever."""
    client, _ = await client_factory(default_handler({
        "slow_cmd": _async_cmd(("FINISHED", {"value": 42})),
    }))
    reply = await asyncio.wait_for(client._dispatcher.run_async("slow_cmd", {}), timeout=5)
    assert reply.get("value") == 42


async def test_notes_in_same_segment_are_delivered(client_factory) -> None:
    client, _ = await client_factory(default_handler({
        "cmd": _async_cmd(
            ("NOTE", {"message": "one"}),
            ("NOTE", {"message": "two"}),
            ("FINISHED", {}),
        ),
    }))
    seen: list[str] = []

    async def on_note(reply: RawReply) -> None:
        seen.append(reply.get("message"))

    await asyncio.wait_for(client._dispatcher.run_async("cmd", {}, on_note=on_note), 5)
    assert seen == ["one", "two"]


async def test_immediate_failed(client_factory) -> None:
    client, _ = await client_factory(default_handler({
        "cmd": _async_cmd(("FAILED", {"kind": "error", "message": "no such session"})),
    }))
    with pytest.raises(IsabelleCommandError) as exc_info:
        await asyncio.wait_for(client._dispatcher.run_async("cmd", {}), 5)
    assert exc_info.value.kind == "FAILED"


async def test_interrupt_maps_to_cancelled(client_factory) -> None:
    client, _ = await client_factory(default_handler({
        "cmd": _async_cmd(("FAILED", {"kind": "error", "message": "Interrupt"})),
    }))
    with pytest.raises(IsabelleTaskCancelled):
        await asyncio.wait_for(client._dispatcher.run_async("cmd", {}), 5)


async def test_interleaved_tasks(client_factory) -> None:
    """Two concurrent tasks; terminal replies arrive in reverse order."""
    first_task: dict[str, str] = {}

    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        t = srv.new_task()
        if name == "a":
            first_task["a"] = t
            return encode_reply("OK", {"task": t})
        # finish b, then a, in one write
        return (encode_reply("OK", {"task": t})
                + encode_reply("FINISHED", {"task": t, "who": "b"})
                + encode_reply("FINISHED", {"task": first_task["a"], "who": "a"}))

    client, _ = await client_factory(default_handler({"a": handler, "b": handler}))
    task_a = asyncio.create_task(client._dispatcher.run_async("a", {}))
    await asyncio.sleep(0.05)
    rb = await asyncio.wait_for(client._dispatcher.run_async("b", {}), 5)
    ra = await asyncio.wait_for(task_a, 5)
    assert (ra.get("who"), rb.get("who")) == ("a", "b")


async def test_connection_lost_fails_fast(client_factory) -> None:
    """Regression (M10): after the reader loop dies new commands must not hang."""
    client, srv = await client_factory()
    await srv.drop_connections()
    await asyncio.sleep(0.05)  # let the reader loop observe EOF
    with pytest.raises(IsabelleConnectionError):
        await asyncio.wait_for(client.echo(1), 5)


async def test_command_after_stop_fails(client_factory) -> None:
    client, _ = await client_factory()
    await client._dispatcher.stop()
    with pytest.raises(IsabelleConnectionError):
        await asyncio.wait_for(client.echo(1), 5)


def _never_finishes(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
    return encode_reply("OK", {"task": srv.new_task()})


async def _wait_for_command(srv: FakeIsabelleServer, name: str, n: int = 1) -> list[Any]:
    for _ in range(100):
        if len(srv.commands(name)) >= n:
            break
        await asyncio.sleep(0.01)
    return srv.commands(name)


async def test_timeout_reports_task_and_cancels_on_server(client_factory) -> None:
    """Regression (M1): task_id/message of IsabelleTimeoutError were mixed up."""
    client, srv = await client_factory(default_handler({"slow": _never_finishes}))
    with pytest.raises(IsabelleTimeoutError) as exc_info:
        await client._dispatcher.run_async("slow", {}, timeout=0.1)
    task_id = "00000000-0000-0000-0000-000000000001"
    assert exc_info.value.task_id == task_id
    assert exc_info.value.timeout == 0.1
    assert str(exc_info.value) == f"Task {task_id} timed out after 0.1s"
    assert await _wait_for_command(srv, "cancel") == [{"task": task_id}]
    assert client._dispatcher._pending == {}


async def test_asyncio_cancellation_cancels_on_server(client_factory) -> None:
    client, srv = await client_factory(default_handler({"slow": _never_finishes}))
    job = asyncio.create_task(client._dispatcher.run_async("slow", {}))
    await asyncio.sleep(0.05)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert await _wait_for_command(srv, "cancel") == [
        {"task": "00000000-0000-0000-0000-000000000001"}
    ]


async def test_failed_with_non_object_payload(client_factory) -> None:
    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        t = srv.new_task()
        return encode_reply("OK", {"task": t}) + f'FAILED "oops {t}"\n'.encode()

    client, _ = await client_factory(default_handler({"cmd": handler}))
    # payload is not an object -> no task id -> nothing routable; must not crash the loop
    with pytest.raises(IsabelleTimeoutError):
        await client._dispatcher.run_async("cmd", {}, timeout=0.1)
    assert await client.echo(1) == 1
