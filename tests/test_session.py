"""High-level session tests against the fake server."""

from __future__ import annotations

from typing import Any

import pytest

from pysabelle.session import IsabelleSession, TheoryLoadError

from .conftest import (
    PASSWORD,
    FakeIsabelleServer,
    default_handler,
    encode_reply,
    node_entry,
)

MASTER = "/work/project"
NODES = [
    node_entry(f"{MASTER}/A.thy", "Draft.A"),
    node_entry(f"{MASTER}/B.thy", "Draft.B"),
]


def _use_theories(ok: bool = True):
    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        t = srv.new_task()
        errors = [] if ok else [{"kind": "error", "message": "boom"}]
        return encode_reply("OK", {"task": t}) + encode_reply(
            "FINISHED", {"task": t, "ok": ok, "errors": errors, "nodes": NODES}
        )
    return handler


def _purge_like_isabelle(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
    """Mimics Isabelle2025-2: names ending in '.thy' are a 'Malformed theory import'."""
    for t in arg.get("theories", []):
        if t.endswith(".thy"):
            return encode_reply(
                "ERROR", {"kind": "error", "message": f'Malformed theory import: "{t}"'}
            )
    purged = [{"node_name": t + ".thy", "theory_name": "Draft." + t.rsplit("/", 1)[-1]}
              for t in arg.get("theories", [])]
    return encode_reply("OK", {"purged": purged, "retained": []})


async def _session(fake_server_factory, ok: bool = True):
    srv = await fake_server_factory(default_handler({
        "use_theories": _use_theories(ok),
        "purge_theories": _purge_like_isabelle,
    }))
    session = await IsabelleSession.connect("HOL", port=srv.port, password=PASSWORD)
    return session, srv


async def test_load_and_purge_purges_whole_import_graph(fake_server_factory) -> None:
    """Regression: node_name values ('.thy') were rejected; imports must be purged too."""
    session, srv = await _session(fake_server_factory)
    async with session:
        results = await session.load_and_purge(["B"], master_dir=MASTER)
    assert results.ok
    (purge_arg,) = srv.commands("purge_theories")
    assert sorted(purge_arg["theories"]) == [f"{MASTER}/A", f"{MASTER}/B"]


async def test_load_and_purge_forwards_master_dir(fake_server_factory) -> None:
    session, srv = await _session(fake_server_factory)
    async with session:
        await session.load_and_purge(["B"], master_dir=MASTER)
    assert srv.commands("purge_theories")[0].get("master_dir") == MASTER


async def test_load_and_purge_purges_even_on_theory_error(fake_server_factory) -> None:
    session, srv = await _session(fake_server_factory, ok=False)
    async with session:
        with pytest.raises(TheoryLoadError):
            await session.load_and_purge(["B"], master_dir=MASTER, raise_on_error=True)
    assert len(srv.commands("purge_theories")) == 1


async def test_purge_theories_accepts_node_names(fake_server_factory) -> None:
    """Manual §4.4.9: node_name values from use_theories may be passed to purge."""
    session, srv = await _session(fake_server_factory)
    async with session:
        await session.purge_theories([f"{MASTER}/A.thy"])
    assert srv.commands("purge_theories")[0]["theories"] == [f"{MASTER}/A"]


async def test_use_theories_timeout_is_honoured(fake_server_factory) -> None:
    """Regression (M2): the ``timeout`` argument used to be silently ignored."""
    from pysabelle.raw.exceptions import IsabelleTimeoutError

    def never(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        return encode_reply("OK", {"task": srv.new_task()})

    srv = await fake_server_factory(default_handler({"use_theories": never}))
    async with await IsabelleSession.connect("HOL", port=srv.port, password=PASSWORD) as s:
        with pytest.raises(IsabelleTimeoutError):
            await s.use_theories(["B"], timeout=0.1)
    assert len(srv.commands("cancel")) == 1


def _failed_async(message: str):
    def handler(name: str, arg: Any, srv: FakeIsabelleServer) -> bytes:
        t = srv.new_task()
        return encode_reply("OK", {"task": t}) + encode_reply(
            "FAILED", {"task": t, "kind": "error", "message": message,
                       "ok": False, "return_code": 1},
        )
    return handler


async def test_close_releases_resources_when_session_stop_fails(fake_server_factory) -> None:
    """Regression (M3): a failing session_stop leaked the connection/dispatcher."""
    from pysabelle.raw.exceptions import IsabelleCommandError

    srv = await fake_server_factory(default_handler({"session_stop": _failed_async("boom")}))
    session = await IsabelleSession.connect("HOL", port=srv.port, password=PASSWORD)
    with pytest.raises(IsabelleCommandError):
        await session.close()
    assert await srv.wait_disconnect()
    assert session._client._transport.is_closing
    assert await session.close() is not None  # idempotent


async def test_failed_session_start_releases_client(fake_server_factory) -> None:
    """Regression (M4): a failing session_start leaked the client (and server)."""
    from pysabelle.raw.exceptions import IsabelleCommandError

    srv = await fake_server_factory(default_handler({"session_start": _failed_async("no HOL")}))
    with pytest.raises(IsabelleCommandError):
        await IsabelleSession.connect("HOL", port=srv.port, password=PASSWORD)
    assert await srv.wait_disconnect()
