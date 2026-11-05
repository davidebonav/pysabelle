"""Exceptions specific to the high‑level session API."""

from __future__ import annotations

from pysabelle.raw.exceptions import IsabelleError
from pysabelle.raw.types import Message


class IsabelleSessionError(IsabelleError):
    """Base class for errors raised by :class:`~pysabelle.session.session.IsabelleSession`."""


class SessionAlreadyClosed(IsabelleSessionError):
    """Raised when a method is called on an already‑closed session."""

    def __init__(self) -> None:
        super().__init__("This session has already been closed.")


class TheoryLoadError(IsabelleSessionError):
    """Raised by :meth:`~pysabelle.session.session.IsabelleSession.use_theories`
    when ``ok=False`` and ``raise_on_error=True``.

    Attributes:
        errors: List of error messages collected during theory loading.
    """

    def __init__(self, errors: list[Message]) -> None:
        self.errors = errors
        lines = "\n".join(
            f"  [{e.pos.file}:{e.pos.line}] {e.message}"
            if e.pos and e.pos.file
            else f"  {e.message}"
            for e in errors
        )
        super().__init__(f"{len(errors)} theory error(s):\n{lines}")
