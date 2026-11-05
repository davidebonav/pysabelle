"""High-level client that composes transport, dispatcher and raw commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pysabelle.raw.commands import RawCommands
from pysabelle.raw.dispatcher import TaskDispatcher
from pysabelle.raw.exceptions import IsabelleConnectionError
from pysabelle.raw.transport import Transport
from pysabelle.server.server_process import IsabelleServerProcess, is_server_running

log = logging.getLogger(__name__)


class IsabelleClient:
    """A connected Isabelle server client with command interface.

    This class composes a :class:`~pysabelle.raw.transport.Transport`,
    a :class:`~pysabelle.raw.dispatcher.TaskDispatcher` and a
    :class:`~pysabelle.raw.commands.RawCommands` instance. It can manage its own
    server process or connect to an existing one.

    Attributes:
        cmd (RawCommands): The raw command interface. All server commands
            (help, echo, session_start, …) are available as methods on this object.
    """

    def __init__(
        self,
        transport: Transport,
        dispatcher: TaskDispatcher,
        commands: RawCommands,
        *,
        server: IsabelleServerProcess | None = None,
        default_timeout: float = 60.0,
    ) -> None:
        """Initialize the client with its components.

        Args:
            transport: Open transport to the server.
            dispatcher: Task dispatcher for async replies.
            commands: RawCommands instance bound to the dispatcher.
            server: Optional server process manager (if the client owns the server).
            default_timeout: Default timeout for async commands (not yet used).
        """
        self._transport = transport
        self._dispatcher = dispatcher
        self._server = server
        self.cmd = commands
        self._timeout = default_timeout

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        password: str,
        *,
        _server: IsabelleServerProcess | None = None,
    ) -> IsabelleClient:
        """Connect to an already-running Isabelle server.

        Performs the password handshake and returns a ready client.

        Args:
            host: Server hostname or IP address.
            port: Server TCP port.
            password: Password obtained from the server's startup message.
            _server: Internal use - server process manager if the client
                should also manage the server.

        Returns:
            A connected IsabelleClient instance.

        Raises:
            IsabelleConnectionError: If the handshake fails or the connection
                cannot be established.
        """
        transport = await cls._open_transport(host, port, password)
        dispatcher = TaskDispatcher(transport)
        commands = RawCommands(dispatcher)
        return cls(transport, dispatcher, commands, server=_server)

    @classmethod
    async def start(
        cls,
        name: str = "isabelle",
        reuse_existing: bool = True,
        server_env: dict[str, str] | None = None,
    ) -> IsabelleClient:
        """Start a new Isabelle server (or reuse an existing one) and connect.

        Args:
            name: Name of the server instance (as used by `isabelle server`).
            reuse_existing: If True, attach to a running server with the given name
                instead of starting a new one.
            server_env: Environment for the ``isabelle server`` subprocesses
                (default: inherit ``os.environ``).

        Returns:
            A connected IsabelleClient instance that owns the server process
            (unless reuse_existing attached to an existing server).

        Raises:
            IsabelleServerError: If server startup fails.
            IsabelleConnectionError: If the handshake fails.
        """
        # blocking subprocess calls: keep the event loop responsive
        srv = await asyncio.to_thread(cls._resolve_server, name, reuse_existing, server_env)
        await asyncio.to_thread(srv.start)
        log.debug("Isabelle server running: host=%s port=%s", srv.info.host, srv.info.port)

        return await cls.connect(
            host=srv.info.host,
            port=srv.info.port,
            password=srv.info.password,
            _server=srv,
        )

    @staticmethod
    def _resolve_server(
        name: str, reuse_existing: bool, env: dict[str, str] | None
    ) -> IsabelleServerProcess:
        """Determine which server process to use.

        Returns:
            A server process manager ready to be started.
        """
        if reuse_existing and is_server_running(name=name, env=env):
            return IsabelleServerProcess(name=name, assume_existing=True, env=env)
        return IsabelleServerProcess(name=name, force_start=True, env=env)

    @staticmethod
    async def _open_transport(host: str, port: int, password: str) -> Transport:
        """Open a transport and perform the password handshake."""
        transport = await Transport.open(host, port)
        await transport.send(password, is_long_msg=False)

        reply = await transport.receive()
        if not reply.is_ok:
            await transport.close()
            raise IsabelleConnectionError(f"Handshake failed: {reply}")

        log.debug("Connected to Isabelle server: %s", reply.argument_raw)
        return transport

    async def stop_server(self) -> None:
        """Stop the managed server process, if any.

        Does nothing if the client does not own the server (e.g., attached via connect).
        """
        if self._server is not None:
            await asyncio.to_thread(self._server.stop)
            log.debug("Isabelle server stopped.")

    async def aclose(self) -> None:
        """Release every resource: dispatcher, TCP connection and managed server.

        Each step is attempted even if a previous one fails; the first error
        (if any) is re-raised at the end.  The server is stopped in a worker
        thread because ``isabelle server -x`` is a blocking subprocess call.
        """
        first_error: BaseException | None = None
        steps = (
            self._dispatcher.stop,
            self._transport.close,
            self.stop_server,
        )
        for step in steps:
            try:
                await step()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error while closing Isabelle client: %s", exc, exc_info=True)
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    def __getattr__(self, name: str) -> Any:
        """Forward attribute access to `self.cmd` for convenience."""
        cmd = self.__dict__.get("cmd")  # avoid infinite recursion before __init__ ran
        try:
            return getattr(cmd, name)
        except AttributeError:
            raise AttributeError(
                f"'{type(self).__name__}' and 'RawCommands' have no attribute '{name}'"
            ) from None

    async def __aenter__(self) -> IsabelleClient:
        """Enter async context: start the dispatcher."""
        await self._dispatcher.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context: stop dispatcher, close transport and server."""
        await self.aclose()
