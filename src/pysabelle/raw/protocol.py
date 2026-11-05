"""Low-level parsing and encoding of Isabelle server messages (§4.2, §4.3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReplyKind(str, Enum):
    """Kind of server reply as defined in §4.2.3."""

    OK = "OK"
    ERROR = "ERROR"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    NOTE = "NOTE"


_NAME_RE: re.Pattern[str] = re.compile(r"^([A-Za-z0-9_.]+)[ \t]*(.*)", re.DOTALL)


@dataclass
class RawReply:
    """A raw server reply before semantic interpretation.

    Attributes:
        kind: The reply kind (OK, ERROR, FINISHED, FAILED, NOTE).
        argument_raw: The raw argument string following the kind tag.
    """

    kind: ReplyKind
    argument_raw: str

    def __post_init__(self) -> None:
        self.__json_cache: Any = _UNSET

    @classmethod
    def parse(cls, line: str) -> RawReply:
        """Parse a single line (or the first line of a long message) into a RawReply.

        Args:
            line: The reply line as received from the server (without trailing newline).

        Returns:
            A RawReply instance.

        Raises:
            ValueError: If the line cannot be parsed or the kind is unknown.
        """
        line = line.rstrip("\r\n")
        if not line:
            raise ValueError("Cannot parse server reply: empty line.")

        m = _NAME_RE.match(line)
        if not m:
            raise ValueError(f"Cannot parse server reply: {line!r}")

        name_str, argument = m.group(1), m.group(2).strip()
        try:
            kind = ReplyKind(name_str)
        except ValueError:
            raise ValueError(
                f"Unknown reply kind {name_str!r} in: {line!r}"
            ) from None

        return cls(kind=kind, argument_raw=argument)

    def json(self) -> Any:
        """Parse `argument_raw` as JSON and cache the result.

        Returns:
            The parsed JSON object, or None if argument_raw is empty.
        """
        if self.__json_cache is _UNSET:
            self.__json_cache = (
                json.loads(self.argument_raw) if self.argument_raw else None
            )
        return self.__json_cache

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience method to extract a key from the JSON payload.

        Args:
            key: The key to look up.
            default: Value to return if the payload is not a dict or key is missing.

        Returns:
            The value for `key`, or `default`.
        """
        obj = self.json()
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    @property
    def task_id(self) -> str | None:
        """Extract the task UUID from the JSON payload, if present."""
        return self.get("task")  # type: ignore[return-value]

    @property
    def is_ok(self) -> bool:
        """True if kind is OK."""
        return self.kind is ReplyKind.OK

    @property
    def is_error(self) -> bool:
        """True if kind is ERROR."""
        return self.kind is ReplyKind.ERROR

    @property
    def is_finished(self) -> bool:
        """True if kind is FINISHED."""
        return self.kind is ReplyKind.FINISHED

    @property
    def is_failed(self) -> bool:
        """True if kind is FAILED."""
        return self.kind is ReplyKind.FAILED

    @property
    def is_note(self) -> bool:
        """True if kind is NOTE."""
        return self.kind is ReplyKind.NOTE

    @property
    def is_terminal(self) -> bool:
        """True for FINISHED or FAILED (terminal async replies)."""
        return self.kind in (ReplyKind.FINISHED, ReplyKind.FAILED)

    @property
    def is_async(self) -> bool:
        """True for NOTE, FINISHED, FAILED (all replies that belong to async tasks)."""
        return self.kind in (ReplyKind.FINISHED, ReplyKind.FAILED, ReplyKind.NOTE)

    def __str__(self) -> str:
        arg = f" {self.argument_raw}" if self.argument_raw else ""
        return f"{self.kind.value}{arg}"

    def __repr__(self) -> str:
        arg = repr(self.argument_raw[:80]) if self.argument_raw else "''"
        return f"RawReply(kind={self.kind!r}, argument_raw={arg})"


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _Unset()


def encode_long_message(text: str) -> bytes:
    """Encode a string as a long message according to §4.2.1.

    Format: ``<length>\\n<text>\\n`` where `<length>` is the decimal byte count
    of `<text>` *including* the trailing newline, exactly as Isabelle's own
    ``Byte_Message.write_line_message`` does.  An uncounted trailing newline
    would be read by the server as a separate empty message (which it answers
    with a spurious ``NOTE``).

    Args:
        text: The message content (may contain newlines).

    Returns:
        Encoded bytes ready to be sent over the wire.

    Raises:
        ValueError: If the text is too long (internal limit not enforced here).
    """
    payload = text.encode("utf-8") + b"\n"
    header = f"{len(payload)}\n".encode("ascii")
    return header + payload


def encode_short_message(text: str) -> bytes:
    """Encode a string as a short message according to §4.2.1.

    Short messages must not contain newline characters. The message is sent
    as a single line terminated by ``\\n``.

    Args:
        text: The message content (no newlines allowed).

    Returns:
        Encoded bytes ready to be sent over the wire.

    Raises:
        ValueError: If the text contains a newline.
    """
    if "\n" in text or "\r" in text:
        raise ValueError(
            f"Short message must not contain newline characters: {text!r}"
        )
    return (text + "\n").encode("utf-8")
