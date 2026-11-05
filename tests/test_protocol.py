"""Unit tests for message framing and reply parsing (§4.2)."""

from __future__ import annotations

import asyncio

import pytest

from pysabelle.raw.exceptions import IsabelleConnectionError
from pysabelle.raw.protocol import (
    RawReply,
    ReplyKind,
    encode_long_message,
    encode_short_message,
)
from pysabelle.raw.transport import Transport

from .conftest import encode_reply


class TestRawReplyParse:
    def test_kind_and_json(self) -> None:
        r = RawReply.parse('OK {"task": "abc"}')
        assert r.kind is ReplyKind.OK
        assert r.json() == {"task": "abc"}
        assert r.task_id == "abc"

    def test_empty_separator(self) -> None:
        # §4.2.3: the separator may be empty when the argument starts with a bracket
        r = RawReply.parse("OK[1,2]")
        assert r.json() == [1, 2]

    def test_no_argument(self) -> None:
        r = RawReply.parse("OK")
        assert r.argument_raw == ""
        assert r.json() is None

    def test_trailing_crlf(self) -> None:
        assert RawReply.parse("NOTE {}\r\n").is_note

    def test_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="Unknown reply kind"):
            RawReply.parse("BOGUS 1")


class TestEncoding:
    def test_long_message(self) -> None:
        # length counts the trailing newline (n + 1), like Isabelle itself
        assert encode_long_message("echo ü") == b"8\necho \xc3\xbc\n"

    def test_short_message_rejects_newline(self) -> None:
        with pytest.raises(ValueError):
            encode_short_message("a\nb")


async def _transport_for(data: bytes) -> Transport:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()

    class _W:
        def is_closing(self) -> bool:
            return False

    return Transport(reader, _W())  # type: ignore[arg-type]


class TestTransportReceive:
    async def test_short_then_long(self) -> None:
        long_arg = {"message": "x" * 200}
        t = await _transport_for(encode_reply("OK", 1) + encode_reply("NOTE", long_arg))
        assert (await t.receive()).json() == 1
        assert (await t.receive()).json() == long_arg

    async def test_eof(self) -> None:
        t = await _transport_for(b"")
        with pytest.raises(IsabelleConnectionError):
            await t.receive()
