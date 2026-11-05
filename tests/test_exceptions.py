"""Exception hierarchy tests."""

from __future__ import annotations

import pysabelle
from pysabelle.raw.exceptions import IsabelleError
from pysabelle.server import ServerAlreadyRunning, ServerNotRunning, ServerStartupTimeout
from pysabelle.session import SessionAlreadyClosed, TheoryLoadError


def test_single_root() -> None:
    """Regression (M6): server errors had a different IsabelleError root."""
    for exc in (ServerStartupTimeout, ServerAlreadyRunning, ServerNotRunning,
                SessionAlreadyClosed, TheoryLoadError, pysabelle.IsabelleConnectionError):
        assert issubclass(exc, IsabelleError), exc
    assert pysabelle.IsabelleError is IsabelleError
