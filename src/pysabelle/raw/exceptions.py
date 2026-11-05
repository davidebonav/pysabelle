"""Exception hierarchy for the raw protocol layer."""

from __future__ import annotations


class IsabelleError(Exception):
    """Root exception for all pYsabelle errors (protocol, server process, session)."""


class IsabelleConnectionError(IsabelleError):
    """Raised on TCP-level failures: connection refused, EOF, or write error."""


class IsabelleProtocolError(IsabelleError):
    """Raised when a server message violates the §4.2 framing rules."""


class IsabelleCommandError(IsabelleError):
    """Raised when the server replies with ``ERROR`` or a task ends with ``FAILED``."""

    def __init__(self, kind: str, argument: str, payload: object = None) -> None:
        """Initialize the exception.

        Args:
            kind: The reply kind (e.g., "ERROR", "FAILED").
            argument: The raw argument string.
            payload: Parsed JSON payload, if any.
        """
        self.kind = kind
        self.argument = argument
        self.payload = payload
        super().__init__(f"{kind}: {argument or '(no message)'}")


class IsabelleTimeoutError(IsabelleError):
    """Raised when a task does not complete within the allotted time."""

    def __init__(self, task_id: str, timeout: float) -> None:
        """Initialize the exception.

        Args:
            task_id: UUID of the timed-out task.
            timeout: Timeout value in seconds.
        """
        self.task_id = task_id
        self.timeout = timeout
        super().__init__(f"Task {task_id} timed out after {timeout}s")


class IsabelleTaskCancelled(IsabelleError):
    """Raised when a task ends with ``FAILED {"message": "Interrupt"}``."""
