"""Typed dataclasses mirroring the JSON types defined in §4.3 of the Isabelle System Manual.

All types are pure data containers with `from_dict` / `to_dict` methods for
JSON (de)serialisation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pysabelle.raw.protocol import RawReply  # no cycle: protocol does not import types

# ---------------------------------------------------------------------------
# Primitive aliases
# ---------------------------------------------------------------------------

#: Isabelle UUID — a plain string on the wire.
UUID = str


# ---------------------------------------------------------------------------
# §4.3 — task and session_id wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskId:
    """Wraps the UUID of a running asynchronous task (§4.3 ``type task``).

    Using a dedicated type prevents accidentally passing a task UUID where
    a session UUID is expected, and vice versa.

    Attributes:
        task: Raw UUID string from an ``OK {"task": "<uuid>"}`` reply.
    """

    task: UUID

    def __str__(self) -> str:
        return self.task


@dataclass(frozen=True)
class SessionId:
    """Wraps the UUID of an active PIDE session (§4.3 ``type session_id``).

    Attributes:
        session_id: Raw UUID string from a ``FINISHED {"session_id": "<uuid>", …}`` reply.
    """

    session_id: UUID

    def __str__(self) -> str:
        return self.session_id


# ---------------------------------------------------------------------------
# Callback alias
# ---------------------------------------------------------------------------

#: Async callable invoked once for every ``NOTE`` message belonging to a task.
#: Receives the raw :class:`~pysabelle.raw.protocol.RawReply` so the caller can
#: decode it into :class:`TheoryProgress`, a generic :class:`Message`, or
#: any other appropriate type.
NoteCallback = Callable[[RawReply], Awaitable[None]]


# ---------------------------------------------------------------------------
# §4.3 — common types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """Source position within Isabelle text (§4.3 ``type position``).

    All fields are optional; only ``line`` and ``file`` are directly
    meaningful to external programs.  Offset fields are counted in
    Isabelle symbol units, not bytes.

    Attributes:
        line: 1‑based line number.
        offset: Start offset in Isabelle symbol units.
        end_offset: End offset in Isabelle symbol units.
        file: Canonical file path.
        id: PIDE command‑transaction identifier (rarely needed externally).
    """

    line: int | None = None
    offset: int | None = None
    end_offset: int | None = None
    file: str | None = None
    id: int | None = None  # noqa: A003

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Position:
        """Deserialise from a JSON object."""
        return cls(
            line=d.get("line"),
            offset=d.get("offset"),
            end_offset=d.get("end_offset"),
            file=d.get("file"),
            id=d.get("id"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON‑compatible dict; ``None`` fields are omitted."""
        return {k: v for k, v in {
            "line": self.line,
            "offset": self.offset,
            "end_offset": self.end_offset,
            "file": self.file,
            "id": self.id,
        }.items() if v is not None}


class MessageKind(str, Enum):
    """Kind tag for Isabelle output messages (§4.3)."""

    WRITELN = "writeln"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Message:
    """General Isabelle output message (§4.3 ``type message``).

    Attributes:
        kind: Message category — ``"writeln"``, ``"warning"``, or ``"error"``.
        message: Human‑readable text.
        pos: Optional source position associated with the message.
    """

    kind: str
    message: str
    pos: Position | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        """Deserialise from a JSON object."""
        pos_raw = d.get("pos")
        return cls(
            kind=d["kind"],
            message=d["message"],
            pos=Position.from_dict(pos_raw) if pos_raw else None,
        )

    @property
    def is_error(self) -> bool:
        """``True`` if ``kind == "error"``."""
        return self.kind == MessageKind.ERROR


@dataclass(frozen=True)
class ErrorMessage:
    """Error message whose ``kind`` is always ``"error"`` (§4.3 ``type error_message``).

    Attributes:
        message: Error description.
    """

    message: str
    kind: str = field(default=MessageKind.ERROR, init=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ErrorMessage:
        """Deserialise from a JSON object.

        The ``kind`` field in *d* is intentionally ignored — it is always
        ``"error"`` by definition.
        """
        return cls(message=d["message"])


@dataclass(frozen=True)
class TheoryProgress:
    """Theory‑loading progress notification (§4.3 ``type theory_progress``).

    Arrives as a ``NOTE`` message during ``session_build`` and
    ``session_start`` tasks.  ``kind`` is always ``"writeln"``.

    Attributes:
        message: Human‑readable progress description.
        theory: Qualified theory name, e.g. ``"HOL.Nat"``.
        session: Session name, e.g. ``"HOL"``.
        percentage: Loading percentage in the range 0–100 (optional).
    """

    message: str
    theory: str
    session: str
    kind: str = field(default=MessageKind.WRITELN, init=False)
    percentage: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TheoryProgress:
        """Deserialise from a JSON object.

        The ``kind`` field in *d* is intentionally ignored.
        """
        return cls(
            message=d["message"],
            theory=d["theory"],
            session=d["session"],
            percentage=d.get("percentage"),
        )

    @classmethod
    def is_theory_progress(cls, d: dict[str, Any]) -> bool:
        """Return ``True`` if *d* contains the fields of a ``theory_progress`` payload."""
        return "theory" in d and "session" in d


@dataclass(frozen=True)
class Timing:
    """Wall‑clock timing reported by Isabelle in seconds (§4.3 ``type timing``).

    Attributes:
        elapsed: Total wall‑clock time.
        cpu: CPU time consumed.
        gc: Time spent in garbage collection.
    """

    elapsed: float
    cpu: float
    gc: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Timing:
        """Deserialise from a JSON object."""
        return cls(elapsed=d["elapsed"], cpu=d["cpu"], gc=d["gc"])


@dataclass(frozen=True)
class NodeStatus:
    """PIDE document‑model processing status for a theory node (§4.3 ``type node_status``).

    Attributes:
        ok: ``True`` iff ``failed == 0``.
        total: Total number of commands in the node.
        unprocessed: Commands not yet started.
        running: Commands currently executing.
        warned: Commands that produced warnings.
        failed: Commands that failed.
        finished: Commands that completed successfully.
        canceled: ``True`` if any command was spontaneously interrupted.
        consolidated: ``True`` once the outermost theory structure has
            finished or failed and the final ``end`` command is checked.
        percentage: Progress indicator in the range 0–100; reaches 100
            when the node is consolidated.
    """

    ok: bool
    total: int
    unprocessed: int
    running: int
    warned: int
    failed: int
    finished: int
    canceled: bool
    consolidated: bool
    percentage: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeStatus:
        """Deserialise from a JSON object."""
        return cls(
            ok=d["ok"],
            total=d["total"],
            unprocessed=d["unprocessed"],
            running=d["running"],
            warned=d["warned"],
            failed=d["failed"],
            finished=d["finished"],
            canceled=d["canceled"],
            consolidated=d["consolidated"],
            percentage=d["percentage"],
        )


@dataclass(frozen=True)
class Node:
    """Internal theory node reference (§4.3 ``type node``).

    Attributes:
        node_name: Canonical file‑system path after normalisation,
            e.g. ``"~~/src/HOL/Examples/Seq.thy"``.
        theory_name: Session‑qualified theory name,
            e.g. ``"HOL-Examples.Seq"``.
    """

    node_name: str
    theory_name: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Node:
        """Deserialise from a JSON object."""
        return cls(node_name=d["node_name"], theory_name=d["theory_name"])


@dataclass(frozen=True)
class NodeWithStatus:
    """Theory node identity combined with its current processing status.

    This is the element type of the ``nodes_status`` list emitted in
    ``NOTE`` messages when ``nodes_status_delay >= 0`` is configured in
    :class:`UseTheoriesArgs`.  Corresponds to the spec type
    ``node ⊕ {status: node_status}``.

    Attributes:
        node: Theory node identity.
        status: Current processing status.
    """

    node: Node
    status: NodeStatus

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeWithStatus:
        """Deserialise from a flat merged JSON object (``node ⊕ {status: …}``)."""
        return cls(
            node=Node.from_dict(d),
            status=NodeStatus.from_dict(d["status"]),
        )


# ---------------------------------------------------------------------------
# §4.4.5 / §4.4.6  session_build / session_start
# ---------------------------------------------------------------------------


@dataclass
class SessionBuildArgs:
    """Arguments shared by ``session_build`` (§4.4.5) and ``session_start`` (§4.4.6).

    ``print_mode`` is accepted here for convenience; it is only meaningful
    for ``session_start`` and is silently ignored by ``session_build``.

    Attributes:
        session: Target session name, e.g. ``"HOL"`` or ``"HOL-Analysis"``.
        preferences: Raw preferences text (the file content, not a path).
        options: Individual option updates, e.g. ``["timeout=60"]``.
        dirs: Additional directories containing ROOT or ROOTS files.
        include_sessions: Sessions whose theories should be included in
            the name space (for use with session‑qualified theory names).
        verbose: Enable verbose build output.
        print_mode: Print mode identifiers for ``session_start``,
            e.g. ``["ASCII"]``.
    """

    session: str
    preferences: str | None = None
    options: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    include_sessions: list[str] = field(default_factory=list)
    verbose: bool = False
    print_mode: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON‑compatible dict; empty and false fields are omitted."""
        d: dict[str, Any] = {"session": self.session}
        if self.preferences is not None:
            d["preferences"] = self.preferences
        if self.options:
            d["options"] = self.options
        if self.dirs:
            d["dirs"] = self.dirs
        if self.include_sessions:
            d["include_sessions"] = self.include_sessions
        if self.verbose:
            d["verbose"] = True
        if self.print_mode:
            d["print_mode"] = self.print_mode
        return d


@dataclass(frozen=True)
class SessionBuildResult:
    """Build outcome for a single session within a ``session_build`` task (§4.4.5).

    Attributes:
        session: Session name.
        ok: ``True`` iff ``return_code == 0``.
        return_code: POSIX process exit code.
        timeout: ``True`` if the build was aborted after exceeding the timeout.
        timing: Wall‑clock timing for this session's build.
    """

    session: str
    ok: bool
    return_code: int
    timeout: bool
    timing: Timing

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionBuildResult:
        """Deserialise from a JSON object."""
        return cls(
            session=d["session"],
            ok=d["ok"],
            return_code=d["return_code"],
            timeout=d.get("timeout", False),
            timing=Timing.from_dict(d["timing"]),
        )


@dataclass(frozen=True)
class SessionBuildResults:
    """Aggregate result of a completed ``session_build`` task (§4.4.5).

    Attributes:
        ok: ``True`` iff all required sessions were built successfully.
        return_code: Highest POSIX return code across all sessions.
        sessions: Individual build results, one per session in the hierarchy.
    """

    ok: bool
    return_code: int
    sessions: list[SessionBuildResult]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionBuildResults:
        """Deserialise from a JSON object."""
        return cls(
            ok=d["ok"],
            return_code=d["return_code"],
            sessions=[SessionBuildResult.from_dict(s) for s in d.get("sessions", [])],
        )


@dataclass(frozen=True)
class SessionStartResult:
    """Result of a successful ``session_start`` task (§4.4.6).

    Attributes:
        session_id: Identifier of the newly created PIDE session.
        tmp_dir: Path to a temporary directory created for this session;
            deleted when the session is stopped.
    """

    session_id: SessionId
    tmp_dir: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionStartResult:
        """Deserialise from a JSON object."""
        return cls(session_id=SessionId(d["session_id"]), tmp_dir=d["tmp_dir"])


# ---------------------------------------------------------------------------
# §4.4.7  session_stop
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionStopResult:
    """Result of a ``session_stop`` task (§4.4.7).

    Attributes:
        ok: ``True`` iff the underlying ML process terminated cleanly.
        return_code: POSIX process exit code.
    """

    ok: bool
    return_code: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionStopResult:
        """Deserialise from a JSON object."""
        return cls(ok=d["ok"], return_code=d["return_code"])


# ---------------------------------------------------------------------------
# §4.4.8  use_theories
# ---------------------------------------------------------------------------


@dataclass
class UseTheoriesArgs:
    """Arguments for the ``use_theories`` command (§4.4.8).

    Attributes:
        session_id: Identifier of the target session.
        theories: Theory names or absolute file paths to load.
        options: Individual option updates for this invocation, e.g.
            ``["show_states"]`` (Isabelle2026, §4.4.8; ignored by older servers).
        master_dir: Base directory for resolving relative theory paths;
            defaults to the session ``tmp_dir``.
        pretty_margin: Line width used for pretty‑printing output messages;
            default is 76.
        unicode_symbols: When ``True``, render Isabelle symbols as Unicode
            in output rather than keeping their symbolic representation.
        export_pattern: Pattern selecting theory exports (e.g. ``"*:*"``);
            empty or ``None`` disables export retrieval.
        check_delay: Seconds between consolidation status checks; default 0.5.
        check_limit: Maximum number of checks; 0 means unbounded.
        watchdog_timeout: Seconds of PIDE inactivity before aborting;
            default 600; 0 disables the watchdog.
        nodes_status_delay: Seconds between ``NOTE nodes_status`` messages;
            negative disables them (default −1).
    """

    session_id: SessionId
    theories: list[str]
    options: list[str] | None = None
    master_dir: str | None = None
    pretty_margin: float | None = None
    unicode_symbols: bool | None = None
    export_pattern: str | None = None
    check_delay: float | None = None
    check_limit: int | None = None
    watchdog_timeout: float | None = None
    nodes_status_delay: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON‑compatible dict; ``None`` fields are omitted."""
        d: dict[str, Any] = {
            "session_id": self.session_id.session_id,
            "theories": self.theories,
        }
        if self.options:
            d["options"] = self.options
        if self.master_dir is not None:
            d["master_dir"] = self.master_dir
        if self.pretty_margin is not None:
            d["pretty_margin"] = self.pretty_margin
        if self.unicode_symbols is not None:
            d["unicode_symbols"] = self.unicode_symbols
        if self.export_pattern is not None:
            d["export_pattern"] = self.export_pattern
        if self.check_delay is not None:
            d["check_delay"] = self.check_delay
        if self.check_limit is not None:
            d["check_limit"] = self.check_limit
        if self.watchdog_timeout is not None:
            d["watchdog_timeout"] = self.watchdog_timeout
        if self.nodes_status_delay is not None:
            d["nodes_status_delay"] = self.nodes_status_delay
        return d


@dataclass(frozen=True)
class Export:
    """Single theory export item returned by ``use_theories`` (§4.4.8).

    Attributes:
        name: Compound export name in ``"theory/name"`` format.
        base64: ``True`` if ``body`` is base64‑encoded binary; ``False``
            if it is plain UTF‑8 text.
        body: Export content — either UTF‑8 text or a base64 string.
    """

    name: str
    base64: bool  # noqa: A003
    body: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Export:
        """Deserialise from a JSON object."""
        return cls(name=d["name"], base64=d["base64"], body=d["body"])


@dataclass(frozen=True)
class NodeResults:
    """Processing results for a single theory node (§4.4.8 ``type node_results``).

    Attributes:
        status: Final processing status of the node.
        messages: All prover messages produced while checking this node.
        exports: Theory exports matching the requested pattern.
    """

    status: NodeStatus
    messages: list[Message]
    exports: list[Export]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeResults:
        """Deserialise from a JSON object."""
        return cls(
            status=NodeStatus.from_dict(d["status"]),
            messages=[Message.from_dict(m) for m in d.get("messages", [])],
            exports=[Export.from_dict(e) for e in d.get("exports", [])],
        )


@dataclass(frozen=True)
class NodeResultEntry:
    """One entry in ``use_theories_results.nodes`` (§4.4.8).

    The spec type is ``node ⊕ node_results`` — a flat JSON merge of node
    identity and processing results.  This class separates the two concerns
    into typed fields for clarity.

    Attributes:
        node: Theory node identity.
        results: Processing results for that node.
    """

    node: Node
    results: NodeResults

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeResultEntry:
        """Deserialise from a flat merged JSON object (``node ⊕ node_results``)."""
        return cls(
            node=Node.from_dict(d),
            results=NodeResults.from_dict(d),
        )


@dataclass(frozen=True)
class UseTheoriesResults:
    """Final result of a completed ``use_theories`` task (§4.4.8).

    Attributes:
        ok: ``True`` iff all nodes were processed without errors.
        errors: All error messages across every node (with position info).
        nodes: Per‑node identity and detailed processing results.
    """

    ok: bool
    errors: list[Message]
    nodes: list[NodeResultEntry]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UseTheoriesResults:
        """Deserialise from a JSON object."""
        return cls(
            ok=d["ok"],
            errors=[Message.from_dict(e) for e in d.get("errors", [])],
            nodes=[NodeResultEntry.from_dict(n) for n in d.get("nodes", [])],
        )


# ---------------------------------------------------------------------------
# §4.4.9  purge_theories
# ---------------------------------------------------------------------------


@dataclass
class PurgeTheoriesArgs:
    """Arguments for the ``purge_theories`` command (§4.4.9).

    Attributes:
        session_id: Identifier of the target session.
        theories: Theory node names to remove — use ``node_name`` values
            from :attr:`NodeResultEntry.node` for precision.
        master_dir: Base directory for relative paths; defaults to the
            session ``tmp_dir``.
        all: When ``True``, attempt to purge all currently loaded theories.
    """

    session_id: SessionId
    theories: list[str] = field(default_factory=list)
    master_dir: str | None = None
    all: bool = False  # noqa: A003

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON‑compatible dict; empty and false fields are omitted."""
        d: dict[str, Any] = {"session_id": self.session_id.session_id}
        if self.theories:
            d["theories"] = self.theories
        if self.master_dir is not None:
            d["master_dir"] = self.master_dir
        if self.all:
            d["all"] = True
        return d


@dataclass(frozen=True)
class PurgeTheoriesResults:
    """Result of a ``purge_theories`` command (§4.4.9).

    The manual gives the type as ``{purged: [string]}``, but the server
    (verified with Isabelle2025-2) returns lists of ``node`` objects for both
    fields; plain strings are still accepted for robustness.

    Attributes:
        purged: Theory nodes that were actually removed from the session.
        retained: Remaining loaded nodes (the complement of ``purged``), e.g.
            those still imported by other theories or used by pending tasks.
    """

    purged: list[Node]
    retained: list[Node]

    @staticmethod
    def _node(x: Any) -> Node:
        if isinstance(x, dict):
            return Node.from_dict(x)
        return Node(node_name=str(x), theory_name="")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PurgeTheoriesResults:
        """Deserialise from a JSON object."""
        return cls(
            purged=[cls._node(x) for x in d.get("purged", [])],
            retained=[cls._node(x) for x in d.get("retained", [])],
        )
