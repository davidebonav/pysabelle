"""Integration tests against a real local Isabelle server (``pytest -m isabelle``).

They start a dedicated server named ``pysabelle-pytest`` and one HOL session,
shared by all tests of this module.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from pysabelle.raw.exceptions import IsabelleCommandError, IsabelleTimeoutError
from pysabelle.raw.types import SessionId
from pysabelle.session import IsabelleSession

pytestmark = [pytest.mark.isabelle, pytest.mark.asyncio(loop_scope="module")]

SERVER_NAME = "pysabelle-pytest"


@pytest.fixture(scope="module")
def theory_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("thys")
    (d / "A.thy").write_text('theory A imports Main begin lemma "True" by simp end\n')
    (d / "B.thy").write_text('theory B imports A begin lemma "True" by simp end\n')
    (d / "Slow.thy").write_text(
        "theory Slow imports Main begin ML \\<open>OS.Process.sleep (seconds 5.0)\\<close> end\n"
    )
    (d / "Opt.thy").write_text('theory Opt imports Main begin lemma "True" by simp end\n')
    (d / "Again.thy").write_text('theory Again imports Main begin lemma "True" by simp end\n')
    (d / "Bad.thy").write_text('theory Bad imports Main begin lemma "False" by simp end\n')
    return d


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def session():
    s = await IsabelleSession.start("HOL", server_name=SERVER_NAME, reuse_server=False)
    try:
        yield s
    finally:
        await s.close()


async def test_echo(session: IsabelleSession) -> None:
    assert await session._client.cmd.echo([1, "x"]) == [1, "x"]


async def test_load_and_purge_leaves_nothing_loaded(session, theory_dir) -> None:
    """Regression for purge_theories with node names (Malformed theory import)."""
    results = await session.load_and_purge(["B"], master_dir=str(theory_dir))
    assert results.ok
    assert {e.node.theory_name for e in results.nodes} == {"Draft.A", "Draft.B"}
    leftover = await session.purge_theories(all=True)
    assert leftover.purged == []


async def test_purge_with_node_names(session, theory_dir) -> None:
    results = await session.use_theories(["B"], master_dir=str(theory_dir))
    purge = await session.purge_theories([e.node.node_name for e in results.nodes])
    assert {n.theory_name for n in purge.purged} == {"Draft.A", "Draft.B"}


async def test_theory_error(session, theory_dir) -> None:
    errors = await session.check_theories(["Bad"], master_dir=str(theory_dir))
    assert errors and all(e.is_error for e in errors)
    await session.purge_theories(all=True)


async def test_failing_async_command_does_not_hang(session) -> None:
    """Regression for the dispatcher race: FAILED arriving right after OK."""
    with pytest.raises(IsabelleCommandError):
        await asyncio.wait_for(
            session._client.cmd.session_stop(SessionId("00000000-0000-0000-0000-000000000000")),
            timeout=30,
        )


async def test_use_theories_timeout_cancels_task(session, theory_dir) -> None:
    """Regression (M1/M2): timeout must be honoured and the server task cancelled."""
    with pytest.raises(IsabelleTimeoutError):
        await session.use_theories(["Slow"], master_dir=str(theory_dir), timeout=1.5)
    # the connection is still usable afterwards
    assert await session._client.cmd.echo("still alive") == "still alive"
    # Note: cancelling the use_theories task does not interrupt ML code that is
    # already running in the prover; wait for it so that session_stop is clean.
    results = await session.use_theories(["Slow"], master_dir=str(theory_dir), timeout=60)
    assert results.ok
    await session.purge_theories(all=True)


async def test_use_theories_with_options(session, theory_dir) -> None:
    """``options`` is an Isabelle2026 field; older servers must simply ignore it."""
    results = await session.load_and_purge(
        ["Opt"], master_dir=str(theory_dir), options=["show_states"]
    )
    assert results.ok


@pytest.mark.xfail(
    strict=False,
    reason="Isabelle2025-2: a purged theory cannot be loaded again in the same session "
    "('Illegal theory header'), even with purge_theories(all=True)",
)
async def test_reload_after_purge(session, theory_dir) -> None:
    assert (await session.load_and_purge(["Again"], master_dir=str(theory_dir))).ok
    results = await session.use_theories(["Again"], master_dir=str(theory_dir))
    await session.purge_theories(all=True)
    assert results.ok
