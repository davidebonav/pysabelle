"""Async TCP transport for the Isabelle server protocol.

Async TCP transport implementing the Isabelle byte-message framing protocol
(§4.2.1 - §4.2.2).

:class:`Transport` wraps an ``asyncio`` ``StreamReader`` / ``StreamWriter``
pair and exposes two primitives:

* :meth:`~Transport.send`    — encode and write one command to the server.
* :meth:`~Transport.receive` — read and decode one server reply.

Both short messages (single LF-terminated line) and long messages
(decimal byte-count prefix followed by a body block) are handled
transparently on receive, as required by §4.2.1.

Obtain an instance via the async factory :meth:`Transport.open`, or supply
an already-connected stream pair directly to the constructor.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Final

from pysabelle.raw.exceptions import (
    IsabelleConnectionError,
    IsabelleProtocolError,
)
from pysabelle.raw.protocol import (
    RawReply,
    encode_long_message,
    encode_short_message,
)

logger = logging.getLogger(__name__)

#: Hard limit on long-message body size.  Guards against rogue or
#: pathological servers sending unreasonably large payloads.
_MAX_BODY_BYTES: Final[int] = 64 * 1024 * 1024  # 64 MiB

#: Set of ASCII digit byte values used to detect long-message length headers.
_DIGITS: Final[frozenset[int]] = frozenset(b"0123456789")


class Transport:
    """Async byte-level transport for the Isabelle server protocol (§4.2).

    Do not instantiate directly — use :meth:`Transport.open` or supply an
    existing ``(reader, writer)`` pair to the constructor.

    Supports use as an async context manager::

        async with await Transport.open(host, port) as t:
            await t.send(password, is_long_msg=False)
            reply = await t.receive()

    Args:
        reader: An ``asyncio.StreamReader`` connected to the server.
        writer: An ``asyncio.StreamWriter`` connected to the server.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader: asyncio.StreamReader = reader
        self._writer: asyncio.StreamWriter = writer

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def open(
        cls,
        host:    str   = "127.0.0.1",
        port:    int   = 4711,
        timeout: float = 30.0,
    ) -> Transport:
        """Open a TCP connection to the Isabelle server.

        Args:
            host: Server hostname or IP address (default ``"127.0.0.1"``).
            port: TCP port (default ``4711``).
            timeout: Connection-establishment timeout in seconds.

        Returns:
            A connected :class:`Transport`.

        Raises:
            IsabelleConnectionError: If the connection cannot be established
                within *timeout* seconds, or if the OS refuses it.
        """
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise IsabelleConnectionError(
                f"Connection to {host}:{port} timed out after {timeout}s."
            ) from exc
        except OSError as exc:
            raise IsabelleConnectionError(
                f"Cannot connect to Isabelle server at {host}:{port}: {exc}"
            ) from exc

        logger.debug("TCP connection established to %s:%d.", host, port)
        return cls(reader, writer)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(self, command: str, *, is_long_msg: bool = True) -> None:
        """Write one command string to the server.

        Args:
            command: Full command text, e.g. ``'session_start {"session": "HOL"}'``.
            is_long_msg: When ``True`` (default) the message is framed as a
                *long message* (§4.2.1).  Set ``False`` **only** for the
                initial password exchange (§4.2.4), which requires a plain
                LF-terminated line.

        Raises:
            IsabelleConnectionError: On write errors.
        """
        data = (
            encode_long_message(command)
            if is_long_msg
            else encode_short_message(command)
        )
        preview = command[:100] + ("…" if len(command) > 100 else "")
        logger.debug("→ %r (%d bytes on wire)", preview, len(data))

        try:
            self._writer.write(data)
            await self._writer.drain()
        except OSError as exc:
            raise IsabelleConnectionError(
                f"Failed to write to Isabelle server: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def receive(self, timeout: float | None = None) -> RawReply:
        """Read and decode one server reply message.

        Handles both §4.2.1 message framings transparently:

        * **Short message** — the first line is the complete reply.
        * **Long message** — the first line is a decimal byte-count;
          the body follows immediately.

        Args:
            timeout: Optional per-call timeout in seconds.  ``None`` waits
                indefinitely.

        Returns:
            Decoded :class:`~pysabelle.raw.protocol.RawReply`.

        Raises:
            IsabelleConnectionError: If the server closes the connection.
            IsabelleProtocolError: If the data violates §4.2 framing rules
                or contains an unknown reply name-tag.
            asyncio.TimeoutError: If *timeout* is exceeded.
        """
        if timeout is not None:
            return await asyncio.wait_for(self._read_one(), timeout=timeout)
        return await self._read_one()

    async def _read_one(self) -> RawReply:
        """Core receive logic — reads exactly one message from the wire.

        Long-message bodies may include a trailing ``\\n`` within the
        declared byte count; ``decode`` + ``rstrip`` handles this uniformly
        without consuming bytes that belong to the next message.
        """
        first_line = await self._reader.readline()
        if not first_line:
            raise IsabelleConnectionError("Isabelle server closed the connection.")

        stripped = first_line.rstrip(b"\r\n")

        if stripped and all(b in _DIGITS for b in stripped):
            length = int(stripped.decode("ascii"))
            if length > _MAX_BODY_BYTES:
                raise IsabelleProtocolError(
                    f"Long message body too large: {length} bytes "
                    f"(limit {_MAX_BODY_BYTES})"
                )
            body = await self._reader.readexactly(length)
            text = body.decode("utf-8")
        else:
            text = stripped.decode("utf-8")

        logger.debug("← %r", text[:200])

        try:
            return RawReply.parse(text)
        except ValueError as exc:
            raise IsabelleProtocolError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the TCP connection gracefully."""
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except OSError:
            pass
        logger.debug("TCP connection closed.")

    @property
    def is_closing(self) -> bool:
        """``True`` if the underlying transport is closing or already closed."""
        return self._writer.is_closing()

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Transport:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
