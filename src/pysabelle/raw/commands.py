"""Raw command wrappers corresponding to each Isabelle server command.

Each method sends the appropriate command and returns a typed result.
"""

from __future__ import annotations

import logging
from typing import Any

from pysabelle.raw.dispatcher import TaskDispatcher
from pysabelle.raw.types import (
    NoteCallback,
    PurgeTheoriesArgs,
    PurgeTheoriesResults,
    SessionBuildArgs,
    SessionBuildResults,
    SessionId,
    SessionStartResult,
    SessionStopResult,
    TaskId,
    UseTheoriesArgs,
    UseTheoriesResults,
)

logger = logging.getLogger(__name__)


class RawCommands:
    """Low-level interface to Isabelle server commands.

    Each method corresponds to one command defined in §§4.4 of the Isabelle
    System Manual. Synchronous commands return a :class:`~pysabelle.raw.protocol.RawReply`
    whose payload has been parsed into the appropriate dataclass.
    Asynchronous commands accept an optional `on_note` callback for progress updates
    and return the final result after the task completes.

    Args:
        dispatcher: The :class:`~pysabelle.raw.dispatcher.TaskDispatcher` used
            to send commands and wait for replies.
    """

    def __init__(self, dispatcher: TaskDispatcher) -> None:
        self._d = dispatcher

    async def help(self) -> list[str]:
        """Send the `help` command.

        Returns:
            List of available command names.
        """
        reply = await self._d.run_sync("help")
        return reply.json() or []

    async def echo(self, value: Any) -> Any:
        """Send the `echo` command.

        Args:
            value: Any JSON-serializable value to echo.

        Returns:
            The same value, as echoed by the server.
        """
        reply = await self._d.run_sync("echo", value)
        return reply.json()

    async def shutdown(self) -> None:
        """Send the `shutdown` command.

        Shuts down the server. No reply is expected.
        """
        await self._d.run_sync("shutdown")

    async def cancel(self, task_id: TaskId) -> None:
        """Send the `cancel` command to interrupt a running task.

        Args:
            task_id: Identifier of the task to cancel.
        """
        await self._d.run_sync("cancel", {"task": task_id.task})

    async def session_build(
        self,
        args: SessionBuildArgs,
        on_note: NoteCallback | None = None,
        timeout: float | None = None,
    ) -> SessionBuildResults:
        """Send the `session_build` command to build a session hierarchy.

        Args:
            args: Build arguments (session name, options, …).
            on_note: Optional callback invoked for each NOTE message during the build.
            timeout: Optional limit in seconds (raises ``IsabelleTimeoutError``).

        Returns:
            Aggregated build results for all required sessions.
        """
        final = await self._d.run_async(
            "session_build", args.to_dict(), on_note=on_note, timeout=timeout
        )
        return SessionBuildResults.from_dict(final.json() or {})

    async def session_start(
        self,
        args: SessionBuildArgs,
        on_note: NoteCallback | None = None,
        timeout: float | None = None,
    ) -> SessionStartResult:
        """Send the `session_start` command to start a new PIDE session.

        Args:
            args: Start arguments (session name, options, print mode, …).
            on_note: Optional callback invoked for each NOTE message during startup.
            timeout: Optional limit in seconds (raises ``IsabelleTimeoutError``).

        Returns:
            Result containing the new session ID and temporary directory.
        """
        final = await self._d.run_async(
            "session_start", args.to_dict(), on_note=on_note, timeout=timeout
        )
        return SessionStartResult.from_dict(final.json() or {})

    async def session_stop(
        self,
        session_id: SessionId,
        on_note: NoteCallback | None = None,
        timeout: float | None = None,
    ) -> SessionStopResult:
        """Send the `session_stop` command to terminate a running session.

        Args:
            session_id: Identifier of the session to stop.
            on_note: Optional callback for NOTE messages during shutdown.
            timeout: Optional limit in seconds (raises ``IsabelleTimeoutError``).

        Returns:
            Stop result indicating success and return code.
        """
        final = await self._d.run_async(
            "session_stop",
            {"session_id": session_id.session_id},
            on_note=on_note,
            timeout=timeout,
        )
        return SessionStopResult.from_dict(final.json() or {})

    async def use_theories(
        self,
        args: UseTheoriesArgs,
        on_note: NoteCallback | None = None,
        timeout: float | None = None,
    ) -> UseTheoriesResults:
        """Send the `use_theories` command to load and check theories.

        Args:
            args: Use-theories arguments (session ID, theory list, options, …).
            on_note: Optional callback for NOTE messages (progress, nodes status).
            timeout: Optional limit in seconds (raises ``IsabelleTimeoutError``).

        Returns:
            Results containing per-node status, messages and exports.
        """
        final = await self._d.run_async(
            "use_theories", args.to_dict(), on_note=on_note, timeout=timeout
        )
        return UseTheoriesResults.from_dict(final.json() or {})

    async def purge_theories(
        self,
        args: PurgeTheoriesArgs,
    ) -> PurgeTheoriesResults:
        """Send the `purge_theories` command to unload theories from a session.

        Args:
            args: Purge arguments (session ID, theory list, all flag).

        Returns:
            Result listing which theories were purged and which retained.
        """
        reply = await self._d.run_sync("purge_theories", args.to_dict())
        return PurgeTheoriesResults.from_dict(reply.json() or {})
