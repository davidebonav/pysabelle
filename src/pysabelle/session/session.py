"""High‑level Isabelle session facade with convenience methods."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from pysabelle.client.client import IsabelleClient
from pysabelle.raw.types import (
    Message,
    PurgeTheoriesArgs,
    PurgeTheoriesResults,
    SessionBuildArgs,
    SessionBuildResults,
    SessionId,
    SessionStopResult,
    UseTheoriesArgs,
    UseTheoriesResults,
)
from pysabelle.session.callbacks import (
    NodesStatusCallback,
    ProgressCallback,
    build_note_handler,
    use_theories_note_handler,
)
from pysabelle.session.exceptions import SessionAlreadyClosed, TheoryLoadError

log = logging.getLogger(__name__)


def _purge_name(name: str) -> str:
    """Turn a theory reference into a name accepted by ``purge_theories``.

    ``node_name`` values returned by ``use_theories`` end in ``.thy``, but the
    server resolves purge names like theory imports and rejects that suffix
    ("Malformed theory import", verified with Isabelle2025-2).  Dropping it
    yields the same canonical node, independently of ``master_dir``.
    """
    return name[:-4] if name.endswith(".thy") else name


class IsabelleSession:
    """High‑level session wrapper.

    This class provides a convenient interface to an Isabelle PIDE session.
    It manages the underlying client, dispatcher and server process, and
    offers methods for building, loading theories, purging, etc.

    Use the class methods :meth:`start` (spawn a new server) or :meth:`connect`
    (attach to an existing server) to create an instance. It is designed to be
    used as an async context manager.

    Attributes:
        session_id: The UUID of the session.
        tmp_dir: Temporary directory created for this session.
    """

    def __init__(
        self,
        client: IsabelleClient,
        session_id: SessionId,
        tmp_dir: str,
    ) -> None:
        """Initialize a session.

        Args:
            client: Connected IsabelleClient instance.
            session_id: Session UUID.
            tmp_dir: Session temporary directory.
        """
        self._client = client
        self._session_id = session_id
        self._tmp_dir = tmp_dir
        self._closed = False

    @property
    def session_id(self) -> SessionId:
        """Session UUID."""
        return self._session_id

    @property
    def tmp_dir(self) -> str:
        """Temporary directory path."""
        return self._tmp_dir

    @classmethod
    async def start(
        cls,
        session: str,
        *,
        server_name: str = "isabelle",
        reuse_server: bool = True,
        server_env: dict[str, str] | None = None,
        options: Sequence[str] = (),
        dirs: Sequence[str] = (),
        include_sessions: Sequence[str] = (),
        verbose: bool = False,
        print_mode: Sequence[str] = (),
        on_progress: ProgressCallback | None = None,
        timeout: float | None = None,
    ) -> IsabelleSession:
        """Start a new Isabelle server and create a session.

        Args:
            session: Name of the session to start (e.g., "HOL").
            server_name: Name for the server process.
            reuse_server: If True, attach to an existing server with the same name
                instead of starting a new one.
            server_env: Environment for the ``isabelle server`` subprocesses
                (default: inherit ``os.environ``).
            options: List of Isabelle options (e.g., ["timeout=60"]).
            dirs: Additional directories containing ROOT files.
            include_sessions: Sessions whose theories should be included.
            verbose: Enable verbose output.
            print_mode: Print mode for output (e.g., ["ASCII"]).
            on_progress: Optional callback for progress messages during startup.
            timeout: Optional timeout for the session_start command.

        Returns:
            A new IsabelleSession instance.

        Raises:
            IsabelleConnectionError: If server connection fails.
            IsabelleCommandError: If the session_start command fails.
        """
        client = await IsabelleClient.start(
            name=server_name, reuse_existing=reuse_server, server_env=server_env
        )
        return await cls._open_session(
            client,
            session=session,
            options=list(options),
            dirs=list(dirs),
            include_sessions=list(include_sessions),
            verbose=verbose,
            print_mode=list(print_mode),
            on_progress=on_progress,
            timeout=timeout,
        )

    @classmethod
    async def connect(
        cls,
        session: str,
        *,
        host: str = "127.0.0.1",
        port: int = 4711,
        password: str = "",
        options: Sequence[str] = (),
        dirs: Sequence[str] = (),
        include_sessions: Sequence[str] = (),
        verbose: bool = False,
        print_mode: Sequence[str] = (),
        on_progress: ProgressCallback | None = None,
        timeout: float | None = None,
    ) -> IsabelleSession:
        """Connect to an already‑running Isabelle server and create a session.

        Args:
            session: Name of the session to start.
            host: Server hostname.
            port: Server port.
            password: Password for handshake.
            options: List of Isabelle options.
            dirs: Additional directories.
            include_sessions: Sessions to include.
            verbose: Enable verbose output.
            print_mode: Print mode.
            on_progress: Optional progress callback.
            timeout: Optional timeout for session_start.

        Returns:
            A new IsabelleSession instance.

        Raises:
            IsabelleConnectionError: If connection/handshake fails.
            IsabelleCommandError: If session_start fails.
        """
        client = await IsabelleClient.connect(
            host=host, port=port, password=password
        )
        return await cls._open_session(
            client,
            session=session,
            options=list(options),
            dirs=list(dirs),
            include_sessions=list(include_sessions),
            verbose=verbose,
            print_mode=list(print_mode),
            on_progress=on_progress,
            timeout=timeout,
        )

    @classmethod
    async def _open_session(
        cls,
        client: IsabelleClient,
        *,
        session: str,
        options: list[str],
        dirs: list[str],
        include_sessions: list[str],
        verbose: bool,
        print_mode: list[str],
        on_progress: ProgressCallback | None,
        timeout: float | None,
    ) -> IsabelleSession:
        """Internal: send session_start; release the client if it fails."""
        args = SessionBuildArgs(
            session=session,
            options=options,
            dirs=dirs,
            include_sessions=include_sessions,
            verbose=verbose,
            print_mode=print_mode,
        )
        on_note = build_note_handler(on_progress) if on_progress else None
        try:
            result = await client.cmd.session_start(args, on_note=on_note, timeout=timeout)
        except BaseException:
            try:
                await client.aclose()
            except Exception:  # never mask the original error
                log.warning("Cleanup after failed session_start failed.", exc_info=True)
            raise

        log.info(
            "Session '%s' started: id=%s tmp_dir=%s",
            session, result.session_id, result.tmp_dir,
        )
        return cls(client, result.session_id, result.tmp_dir)

    async def build(
        self,
        session: str,
        *,
        options: Sequence[str] = (),
        dirs: Sequence[str] = (),
        include_sessions: Sequence[str] = (),
        verbose: bool = False,
        on_progress: ProgressCallback | None = None,
        timeout: float | None = None,
    ) -> SessionBuildResults:
        """Build a session hierarchy (without starting it).

        Args:
            session: Session name to build.
            options: List of Isabelle options.
            dirs: Additional directories.
            include_sessions: Sessions to include.
            verbose: Enable verbose output.
            on_progress: Optional progress callback.
            timeout: Optional timeout.

        Returns:
            Build results for all required sessions.

        Raises:
            SessionAlreadyClosed: If the session is already closed.
            IsabelleCommandError: If the build fails.
        """
        self._guard()
        args = SessionBuildArgs(
            session=session,
            options=list(options),
            dirs=list(dirs),
            include_sessions=list(include_sessions),
            verbose=verbose,
        )
        on_note = build_note_handler(on_progress) if on_progress else None
        return await self._client.cmd.session_build(args, on_note=on_note, timeout=timeout)

    async def use_theories(
        self,
        theories: list[str],
        *,
        options: Sequence[str] | None = None,
        master_dir: str | None = None,
        pretty_margin: float | None = None,
        unicode_symbols: bool | None = None,
        export_pattern: str | None = None,
        check_delay: float | None = None,
        check_limit: int | None = None,
        watchdog_timeout: float | None = None,
        nodes_status_delay: float | None = None,
        on_progress: ProgressCallback | None = None,
        on_nodes_status: NodesStatusCallback | None = None,
        raise_on_error: bool = False,
        timeout: float | None = None,
    ) -> UseTheoriesResults:
        """Load and process a list of theories.

        Args:
            theories: List of theory names or file paths.
            options: Option updates for this invocation (Isabelle2026+).
            master_dir: Base directory for resolving relative paths.
            pretty_margin: Output line width.
            unicode_symbols: Use Unicode symbols in output.
            export_pattern: Pattern for theory exports.
            check_delay: Seconds between status checks.
            check_limit: Maximum number of checks (0 = unbounded).
            watchdog_timeout: Seconds of inactivity before abort.
            nodes_status_delay: Seconds between node status updates.
            on_progress: Callback for progress messages.
            on_nodes_status: Callback for periodic node status lists.
            raise_on_error: If True, raise TheoryLoadError when `ok` is False.
            timeout: Optional timeout in seconds for the whole command; on expiry
                the task is cancelled on the server and ``IsabelleTimeoutError``
                is raised.

        Returns:
            UseTheoriesResults containing per‑node status, messages and exports.

        Raises:
            SessionAlreadyClosed: If session is closed.
            TheoryLoadError: If raise_on_error=True and errors occurred.
            IsabelleCommandError: For other command failures.
        """
        self._guard()
        args = UseTheoriesArgs(
            session_id=self._session_id,
            theories=theories,
            options=list(options) if options else None,
            master_dir=master_dir,
            pretty_margin=pretty_margin,
            unicode_symbols=unicode_symbols,
            export_pattern=export_pattern,
            check_delay=check_delay,
            check_limit=check_limit,
            watchdog_timeout=watchdog_timeout,
            nodes_status_delay=nodes_status_delay,
        )
        on_note = use_theories_note_handler(on_progress, on_nodes_status)
        results = await self._client.cmd.use_theories(args, on_note=on_note, timeout=timeout)

        if raise_on_error and not results.ok:
            raise TheoryLoadError(results.errors)

        return results

    async def purge_theories(
        self,
        theories: Sequence[str] = (),
        *,
        master_dir: str | None = None,
        all: bool = False,  # noqa: A002
    ) -> PurgeTheoriesResults:
        """Unload theories from the session.

        Theories are resolved like imports (relative to ``master_dir``).
        ``node_name`` values from :attr:`UseTheoriesResults.nodes` may be passed
        as well (§4.4.9): their ``.thy`` suffix is removed automatically.
        Imported dependencies are *not* added: pass the whole ``nodes`` list
        returned by ``use_theories`` to release them too.

        .. warning::
           With Isabelle2025-2 a purged theory cannot be loaded again in the
           same session (``use_theories`` then reports "Illegal theory
           header"); this also happens with ``all=True``.  Purge only theories
           you will not need again, or start a new session.

        Args:
            theories: Theory names or node names to purge.
            master_dir: Base directory for resolving relative names.
            all: If True, purge all currently loaded theories.

        Returns:
            PurgeTheoriesResults listing purged and retained nodes.

        Raises:
            SessionAlreadyClosed: If session is closed.
            IsabelleCommandError: If the command fails.
        """
        self._guard()
        args = PurgeTheoriesArgs(
            session_id=self._session_id,
            theories=[_purge_name(t) for t in theories],
            master_dir=master_dir,
            all=all,
        )
        return await self._client.cmd.purge_theories(args)

    async def check_theories(
        self,
        theories: list[str],
        **kwargs: Any,
    ) -> list[Message]:
        """Load theories and return only the error messages.

        This is a convenience wrapper around `use_theories` that discards
        success information and returns only the error list.

        Args:
            theories: List of theory names.
            **kwargs: Additional arguments passed to `use_theories`.

        Returns:
            List of error messages (empty if no errors).
        """
        results = await self.use_theories(theories, **kwargs)
        return results.errors

    async def load_and_purge(
        self,
        theories: list[str],
        **kwargs: Any,
    ) -> UseTheoriesResults:
        """Load theories and then immediately purge them, with all their imports.

        Useful for checking theories with minimal memory footprint.  Every node
        reported by ``use_theories`` (the requested theories and their imports
        outside the session image) is purged.  If ``use_theories`` raises (e.g.
        ``raise_on_error=True``), the requested theories are purged anyway and
        the original exception is re-raised.

        .. warning::
           See :meth:`purge_theories`: with Isabelle2025-2 the purged theories
           (including their imports) cannot be reloaded in the same session.

        Args:
            theories: List of theory names.
            **kwargs: Additional arguments passed to `use_theories`;
                ``master_dir`` is also used for purging.

        Returns:
            The results of the `use_theories` command (before purging).
        """
        master_dir = kwargs.get("master_dir")
        try:
            results = await self.use_theories(theories, **kwargs)
        except Exception:
            try:
                await self.purge_theories(theories, master_dir=master_dir)
            except Exception:  # never mask the original error
                log.warning("Purge after failed use_theories also failed.", exc_info=True)
            raise

        names = [entry.node.node_name for entry in results.nodes] or list(theories)
        await self.purge_theories(names, master_dir=master_dir)
        return results

    async def close(self, *, timeout: float | None = 60.0) -> SessionStopResult:
        """Stop the session and clean up resources.

        The connection, the dispatcher and (if owned) the server process are
        always released, even when ``session_stop`` fails or times out.

        Args:
            timeout: Maximum seconds to wait for ``session_stop``.

        Returns:
            SessionStopResult indicating success and return code.

        Raises:
            IsabelleCommandError: If session_stop fails (resources are released anyway).
        """
        if self._closed:
            return SessionStopResult(ok=True, return_code=0)

        self._closed = True
        try:
            result = await self._client.cmd.session_stop(self._session_id, timeout=timeout)
            log.info(
                "Session %s stopped: ok=%s rc=%d",
                self._session_id, result.ok, result.return_code,
            )
            return result
        finally:
            await self._client.aclose()

    async def __aenter__(self) -> IsabelleSession:
        """Enter async context: return self."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context: close the session."""
        await self.close()

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return (
            f"IsabelleSession("
            f"session_id={self._session_id!r}, "
            f"tmp_dir={self._tmp_dir!r}, "
            f"state={state!r})"
        )

    def _guard(self) -> None:
        """Raise :exc:`~pysabelle.session.exceptions.SessionAlreadyClosed` if closed."""
        if self._closed:
            raise SessionAlreadyClosed()
