"""Callback helpers for converting raw NOTE replies into typed callbacks."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pysabelle.raw.protocol import RawReply
from pysabelle.raw.types import Message, NodeWithStatus, NoteCallback, TheoryProgress

log = logging.getLogger(__name__)

#: Callback for progress updates during session build/start.
#: Receives either a :class:`~pysabelle.raw.types.TheoryProgress` or a generic
#: :class:`~pysabelle.raw.types.Message`.
ProgressCallback = Callable[[TheoryProgress | Message], Awaitable[None]]

#: Callback for periodic node status updates during `use_theories`.
#: Receives a list of :class:`~pysabelle.raw.types.NodeWithStatus`.
NodesStatusCallback = Callable[[list[NodeWithStatus]], Awaitable[None]]


def build_note_handler(on_progress: ProgressCallback) -> NoteCallback:
    """Convert a `ProgressCallback` into a `NoteCallback` for session build/start.

    Args:
        on_progress: User‑provided callback that expects either a TheoryProgress
            or a Message.

    Returns:
        A NoteCallback suitable for passing to `session_build` or `session_start`.
    """

    async def _handler(reply: RawReply) -> None:
        payload = reply.json() or {}
        if not isinstance(payload, dict):
            return
        try:
            if TheoryProgress.is_theory_progress(payload):
                await on_progress(TheoryProgress.from_dict(payload))
            elif "message" in payload:
                await on_progress(Message.from_dict(payload))
        except Exception:
            log.exception("ProgressCallback raised during build NOTE.")

    return _handler


def use_theories_note_handler(
    on_progress: ProgressCallback | None,
    on_nodes_status: NodesStatusCallback | None,
) -> NoteCallback | None:
    """Combine optional progress and nodes_status callbacks into a single NoteCallback.

    Args:
        on_progress: Optional progress callback.
        on_nodes_status: Optional nodes‑status callback.

    Returns:
        A NoteCallback that dispatches NOTE messages to the appropriate user callback,
        or None if both callbacks are None.
    """
    if on_progress is None and on_nodes_status is None:
        return None

    async def _handler(reply: RawReply) -> None:
        payload = reply.json() or {}
        if not isinstance(payload, dict):
            return
        try:
            if on_nodes_status is not None and "nodes_status" in payload:
                nodes = [NodeWithStatus.from_dict(n) for n in payload["nodes_status"]]
                await on_nodes_status(nodes)
                return

            if on_progress is None:
                return

            if TheoryProgress.is_theory_progress(payload):
                await on_progress(TheoryProgress.from_dict(payload))
            elif "message" in payload:
                await on_progress(Message.from_dict(payload))

        except Exception:
            log.exception("Callback raised during use_theories NOTE.")

    return _handler
