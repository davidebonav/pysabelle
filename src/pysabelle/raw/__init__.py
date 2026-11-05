"""Raw protocol layer: transport, dispatcher, commands and types.

This package contains the low-level implementation of the Isabelle Server protocol.
All public symbols are re-exported here for convenience.
"""

from __future__ import annotations

from pysabelle.raw.commands import RawCommands
from pysabelle.raw.dispatcher import TaskDispatcher
from pysabelle.raw.exceptions import (
    IsabelleCommandError,
    IsabelleConnectionError,
    IsabelleError,
    IsabelleProtocolError,
    IsabelleTaskCancelled,
    IsabelleTimeoutError,
)
from pysabelle.raw.protocol import (
    RawReply,
    ReplyKind,
    encode_long_message,
    encode_short_message,
)
from pysabelle.raw.transport import Transport
from pysabelle.raw.types import (
    UUID,
    # §4.3 common
    Export,
    Message,
    MessageKind,
    Node,
    NodeResultEntry,
    NodeResults,
    NodeStatus,
    NodeWithStatus,
    NoteCallback,
    Position,
    # §4.4.9
    PurgeTheoriesArgs,
    PurgeTheoriesResults,
    # §4.4.5 / §4.4.6
    SessionBuildArgs,
    SessionBuildResult,
    SessionBuildResults,
    SessionId,
    SessionStartResult,
    # §4.4.7
    SessionStopResult,
    TaskId,
    TheoryProgress,
    Timing,
    # §4.4.8
    UseTheoriesArgs,
    UseTheoriesResults,
)

__all__ = [
    # exceptions
    "IsabelleError",
    "IsabelleConnectionError",
    "IsabelleProtocolError",
    "IsabelleCommandError",
    "IsabelleTaskCancelled",
    "IsabelleTimeoutError",
    # primitive aliases
    "UUID",
    "NoteCallback",
    "TaskId",
    "SessionId",
    # §4.3 common types
    "Position",
    "MessageKind",
    "Message",
    "TheoryProgress",
    "Timing",
    "NodeStatus",
    "Node",
    "NodeWithStatus",
    "Export",
    "NodeResults",
    "NodeResultEntry",
    # command arg / result types
    "SessionBuildArgs",
    "SessionBuildResult",
    "SessionBuildResults",
    "SessionStartResult",
    "SessionStopResult",
    "UseTheoriesArgs",
    "UseTheoriesResults",
    "PurgeTheoriesArgs",
    "PurgeTheoriesResults",
    # protocol
    "ReplyKind",
    "RawReply",
    "encode_long_message",
    "encode_short_message",
    # transport
    "Transport",
    # dispatcher
    "TaskDispatcher",
    # commands
    "RawCommands",
]
