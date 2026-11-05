"""IsabelleServerProcess tests using a fake ``isabelle`` executable."""

from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

from pysabelle.server import (
    IsabelleServerError,
    IsabelleServerProcess,
    ServerStartupTimeout,
    list_servers,
)

FAKE = Path(__file__).with_name("fake_isabelle.py")


@pytest.fixture
def fake_bin(tmp_path: Path) -> str:
    script = tmp_path / "isabelle"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    state = tmp_path / "state"
    state.mkdir()
    # NOT exported to os.environ: only reachable through the ``env`` argument
    return {**os.environ, "FAKE_ISABELLE_STATE": str(state)}


def _wait_for(path: Path, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def test_env_is_used_for_list_and_stop(fake_bin: str, env: dict[str, str]) -> None:
    """Regression (M7): ``-l``/``-x`` ignored ``env`` -> wrong servers.db / orphan server."""
    srv = IsabelleServerProcess(name="t", isabelle_bin=fake_bin, env=env)
    info = srv.start()
    assert (info.name, info.port, info.password) == ("t", 4711, "pw-t")
    assert srv.is_running
    srv.stop()
    assert list_servers(fake_bin, env) == []


def test_server_output_is_drained_after_ready(fake_bin: str, env: dict[str, str]) -> None:
    """Regression (C3): undrained stdout pipe blocked the server once it filled up."""
    env = {**env, "FAKE_ISABELLE_SPEW": str(1024 * 1024)}  # 1 MiB of "log" on stderr
    with IsabelleServerProcess(name="spew", isabelle_bin=fake_bin, env=env):
        assert _wait_for(Path(env["FAKE_ISABELLE_STATE"]) / "spew.alive"), "server blocked"


def test_startup_timeout_kills_process(fake_bin: str, env: dict[str, str]) -> None:
    env = {**env, "FAKE_ISABELLE_NEVER_READY": "1"}
    srv = IsabelleServerProcess(name="slow", isabelle_bin=fake_bin, env=env, startup_timeout=0.5)
    with pytest.raises(ServerStartupTimeout):
        srv.start()
    assert srv._proc is not None and srv._proc.poll() is not None


def test_missing_executable() -> None:
    with pytest.raises(IsabelleServerError, match="not found"):
        list_servers("/nonexistent/isabelle")


def test_empty_env_is_respected(fake_bin: str) -> None:
    """``env={}`` used to be silently replaced by the whole os.environ."""
    srv = IsabelleServerProcess(name="t", isabelle_bin=fake_bin, env={})
    assert srv._env == {}
