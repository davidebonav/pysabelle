"""Asynchronous task dispatcher for multiplexing replies.

The dispatcher runs a background reader loop that receives raw replies from the
transport, classifies them (OK, ERROR, NOTE, FINISHED, FAILED) and routes them to
the appropriate waiting futures or callbacks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from pysabelle.raw.exceptions import (
    IsabelleCommandError,
    IsabelleConnectionError,
    IsabelleProtocolError,
    IsabelleTaskCancelled,
    IsabelleTimeoutError,
)
from pysabelle.raw.protocol import RawReply
from pysabelle.raw.transport import Transport
from pysabelle.raw.types import UUID, NoteCallback

logger = logging.getLogger(__name__)

#: Per-task registry entry: terminal Future paired with an optional NOTE callback.
_TaskEntry = tuple[asyncio.Future[RawReply], NoteCallback | None]


class TaskDispatcher:
    """Multiplexes incoming server replies to waiting callers.

    The dispatcher owns a background task that continuously reads from the transport.
    It maintains:
    - a single `_sync_reply` future for the next synchronous reply (OK/ERROR)
    - a dictionary `_pending` mapping task UUIDs to (future, callback) for async tasks

    For asynchronous commands the task is registered in `_pending` by the reader
    loop itself, at the moment it reads the immediate ``OK {"task": id}`` reply.
    This guarantees that ``NOTE``/``FINISHED``/``FAILED`` messages that follow
    immediately on the wire (possibly in the same TCP segment) are never lost.

    Once the reader loop has crashed (e.g. connection lost) or the dispatcher
    has been stopped, new commands fail immediately with
    :class:`~pysabelle.raw.exceptions.IsabelleConnectionError`.

    Use `run_sync()` for commands that return a single immediate reply.
    Use `run_async()` for commands that first return an OK with a task ID, then later
    a FINISHED/FAILED, possibly with intermediate NOTE messages.

    Args:
        transport: Open transport to the server.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._pending: dict[UUID, _TaskEntry] = {}
        self._sync_reply: asyncio.Future[RawReply] | None = None
        #: Task entry to register when the pending sync reply is ``OK {"task": …}``.
        self._sync_task_entry: _TaskEntry | None = None
        self._cmd_lock = asyncio.Lock()
        self._loop_task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self._stopped = False
        #: Tasks given up by the client (timeout / cancellation); their late
        #: terminal reply is expected and silently discarded.
        self._abandoned: set[UUID] = set()
        self._background: set[asyncio.Task[None]] = set()

    def _ensure_running(self) -> None:
        """Raise if the connection is unusable; otherwise make sure the reader runs."""
        if self._failure is not None:
            raise IsabelleConnectionError(
                f"Connection to the Isabelle server is no longer usable: {self._failure}"
            ) from self._failure
        if self._stopped:
            raise IsabelleConnectionError("The dispatcher has been stopped.")
        self._start()

    def _start(self) -> None:
        """Start the background reader loop if not already running."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(
                self._reader_loop(), name="isabelle-dispatcher"
            )
            logger.debug("Reader loop started.")

    async def _stop(self) -> None:
        """Stop the reader loop and cancel all pending tasks."""
        if self._background:
            # let in-flight best-effort ``cancel`` commands reach the server
            await asyncio.wait(set(self._background), timeout=2.0)
        self._stopped = True
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            logger.debug("Reader loop stopped.")

        n_pending = len(self._pending)
        if n_pending:
            logger.warning("Shutting down with %d in-flight task(s) — cancelling.", n_pending)
        self._cancel_all(reason="dispatcher stopped")

    async def start(self) -> None:
        """Public API to start the dispatcher."""
        self._start()
        await asyncio.sleep(0)  # yield so the reader task is actually scheduled

    async def stop(self) -> None:
        """Public API to stop the dispatcher."""
        await self._stop()

    async def __aenter__(self) -> TaskDispatcher:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    async def _reader_loop(self) -> None:
        """Background task: read replies from transport and dispatch."""
        logger.debug("Reader loop running.")
        try:
            while True:
                reply = await self._transport.receive()
                logger.debug("Received: kind=%s task=%s", reply.kind.value, reply.task_id or "-")
                await self._dispatch(reply)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Reader loop crashed (%s: %s) — failing all pending futures.",
                type(exc).__name__, exc,
                exc_info=True,
            )
            self._fail_all(exc)

    async def _dispatch(self, reply: RawReply) -> None:
        """Route a single reply to the appropriate waiter."""
        if reply.is_ok or reply.is_error:
            # Synchronous reply
            if self._sync_reply is not None and not self._sync_reply.done():
                entry = self._sync_task_entry
                task_id = reply.task_id if reply.is_ok else None
                if entry is not None and task_id:
                    # Register *before* reading the next message from the wire.
                    self._pending[task_id] = entry
                    logger.debug(
                        "Registered async task %s. (%d task(s) now pending.)",
                        task_id, len(self._pending),
                    )
                self._sync_reply.set_result(reply)
                self._sync_reply = None
                self._sync_task_entry = None
            else:
                logger.warning(
                    "Received %s but no sync waiter is registered — dropping.",
                    reply.kind.value,
                )
            return

        # Intermediate notification (NOTE)
        if reply.is_note:
            task_id = reply.task_id
            entry = self._pending.get(task_id) if task_id else None
            if entry is None:
                logger.debug("NOTE for untracked task %r — dropping.", task_id)
                return
            _, on_note = entry
            if on_note is not None:
                try:
                    await on_note(reply)
                except Exception:
                    logger.exception("NOTE callback raised for task %s.", task_id)
            return

        # Terminal async reply (FINISHED / FAILED)
        if reply.is_terminal:
            task_id = reply.task_id
            entry = self._pending.pop(task_id, None) if task_id else None
            if entry is None and task_id in self._abandoned:
                self._abandoned.discard(task_id)
                logger.debug("%s for abandoned task %s.", reply.kind.value, task_id)
                return
            if entry is None:
                logger.warning(
                    "%s for untracked task %r — dropping.",
                    reply.kind.value, task_id,
                )
                return
            fut, _ = entry
            logger.debug(
                "Task %s %s. (%d task(s) still pending.)",
                task_id, reply.kind.value, len(self._pending),
            )
            if not fut.done():
                fut.set_result(reply)
            return

        logger.warning("Unroutable reply (kind=%s) — dropping.", reply.kind.value)

    def _fail_all(self, exc: Exception) -> None:
        """Fail all pending futures with the given exception."""
        self._failure = exc
        self._sync_task_entry = None
        if self._sync_reply and not self._sync_reply.done():
            self._sync_reply.set_exception(exc)
            self._sync_reply = None

        for task_id, (fut, _) in self._pending.items():
            if not fut.done():
                logger.debug("Failing task %s: %s", task_id, exc)
                fut.set_exception(exc)
        self._pending.clear()

    def _cancel_all(self, reason: str = "") -> None:
        """Cancel all pending futures."""
        self._sync_task_entry = None
        if self._sync_reply and not self._sync_reply.done():
            self._sync_reply.cancel(reason)
            self._sync_reply = None

        for task_id, (fut, _) in self._pending.items():
            if not fut.done():
                logger.debug("Cancelling task %s: %s", task_id, reason)
                fut.cancel(reason)
        self._pending.clear()

    def _arm_sync_reply(self, task_entry: _TaskEntry | None = None) -> asyncio.Future[RawReply]:
        """Prepare a future for the next synchronous reply.

        Args:
            task_entry: For asynchronous commands, the ``(terminal future, on_note)``
                pair that the reader loop registers under the task id carried by
                the immediate ``OK`` reply.
        """
        fut = asyncio.get_running_loop().create_future()
        self._sync_reply = fut
        self._sync_task_entry = task_entry
        return fut

    async def _send_and_wait_sync(
        self, wire: str, task_entry: _TaskEntry | None = None
    ) -> RawReply:
        """Send one command and wait for its immediate OK/ERROR reply."""
        async with self._cmd_lock:
            self._ensure_running()
            sync_fut = self._arm_sync_reply(task_entry)
            try:
                await self._transport.send(wire)
                return await sync_fut
            finally:
                if self._sync_reply is sync_fut:  # send failed or we were cancelled
                    self._sync_reply = None
                    self._sync_task_entry = None

    def _abandon(self, task_id: UUID) -> None:
        """Forget a task the caller no longer waits for and ask the server to cancel it."""
        entry = self._pending.pop(task_id, None)
        if entry is not None and not entry[0].done():
            entry[0].cancel()
        self._abandoned.add(task_id)
        if self._failure is not None or self._stopped:
            return
        bg = asyncio.get_running_loop().create_task(self._send_cancel(task_id))
        self._background.add(bg)
        bg.add_done_callback(self._background.discard)

    async def _send_cancel(self, task_id: UUID) -> None:
        """Best-effort ``cancel {"task": id}`` (§4.4.4); errors are only logged."""
        try:
            await self.run_sync("cancel", {"task": task_id})
            logger.debug("Sent cancel for task %s.", task_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not cancel task %s: %s", task_id, exc)

    async def run_sync(
        self,
        command: str,
        arg: Any = None,
    ) -> RawReply:
        """Execute a synchronous command and return its immediate reply.

        The command is sent while holding the command lock. The reply must be
        either OK or ERROR; any other kind is considered a protocol error.

        Args:
            command: Name of the command (e.g., "help", "echo").
            arg: Optional JSON-serializable argument.

        Returns:
            The raw reply (OK or ERROR).

        Raises:
            IsabelleCommandError: If the server replies with ERROR.
            IsabelleProtocolError: If the reply is neither OK nor ERROR.
        """
        wire = f"{command} {json.dumps(arg, ensure_ascii=False)}" if arg is not None else command
        logger.debug("sync → %s", wire[:120])

        reply = await self._send_and_wait_sync(wire)

        logger.debug("sync ← %s %s", reply.kind.value, (reply.argument_raw or "")[:120])

        if reply.is_error:
            raise IsabelleCommandError(
                kind=reply.kind.value,
                argument=reply.argument_raw,
                payload=reply.json(),
            )
        return reply

    async def run_async(
        self,
        command: str,
        arg: Any = None,
        on_note: NoteCallback | None = None,
        timeout: float | None = None,
    ) -> RawReply:
        """Execute an asynchronous command and wait for its terminal reply.

        The command is sent; the first reply must be OK containing a task ID.
        Subsequent NOTE messages are delivered to `on_note`, and the future
        returned completes when FINISHED or FAILED arrives.

        Args:
            command: Name of the command (e.g., "session_build").
            arg: Optional JSON-serializable argument.
            on_note: Callback invoked for each NOTE message belonging to this task.
            timeout: Maximum seconds to wait for the terminal reply.  On timeout,
                and also when the awaiting coroutine is cancelled, a best-effort
                ``cancel`` command is sent to the server for this task.

        Returns:
            The terminal reply (FINISHED or FAILED).

        Raises:
            IsabelleCommandError: If the immediate reply is ERROR or the task fails.
            IsabelleProtocolError: If the immediate reply is OK but lacks a task ID.
            IsabelleTimeoutError: If the terminal reply does not arrive within `timeout`.
            IsabelleTaskCancelled: If the task ends with FAILED {"message": "Interrupt"}.
        """
        wire = f"{command} {json.dumps(arg, ensure_ascii=False)}" if arg is not None else command
        logger.debug("async → %s", wire[:120])

        # send + await immediate OK; the reader loop registers terminal_fut
        # under the task id as soon as it reads that OK.
        terminal_fut: asyncio.Future[RawReply] = asyncio.get_running_loop().create_future()
        immediate = await self._send_and_wait_sync(wire, (terminal_fut, on_note))

        if immediate.is_error:
            raise IsabelleCommandError(
                kind=immediate.kind.value,
                argument=immediate.argument_raw,
                payload=immediate.json(),
            )
        if not immediate.is_ok:
            raise IsabelleProtocolError(
                f"Expected OK for async command {command!r}, got {immediate.kind.value}."
            )

        task_id = immediate.task_id
        if not task_id:
            raise IsabelleProtocolError(
                f"Async command {command!r} returned OK without a task id: "
                f"{immediate.argument_raw!r}"
            )

        # await FINISHED / FAILED
        try:
            terminal: RawReply = await asyncio.wait_for(
                asyncio.shield(terminal_fut), timeout=timeout
            )
        except asyncio.TimeoutError:
            self._abandon(task_id)
            raise IsabelleTimeoutError(task_id, timeout) from None  # type: ignore[arg-type]
        except asyncio.CancelledError:
            self._abandon(task_id)
            raise

        logger.debug("Task %s → %s", task_id, terminal.kind.value)

        if terminal.is_failed:
            payload = terminal.json()
            if isinstance(payload, dict) and payload.get("message") == "Interrupt":
                raise IsabelleTaskCancelled(f"Task {task_id} cancelled.")
            raise IsabelleCommandError(
                kind=terminal.kind.value,
                argument=terminal.argument_raw,
                payload=payload,
            )

        return terminal
