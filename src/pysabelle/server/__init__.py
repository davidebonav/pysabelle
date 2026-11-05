"""Server process management: starting, attaching, stopping Isabelle servers.

This package provides tools to control the lifecycle of `isabelle server`
processes and to obtain connection information for running servers.
"""

from pysabelle.server.exceptions import (
    IsabelleError,
    IsabelleServerError,
    ServerAlreadyRunning,
    ServerNotRunning,
    ServerStartupTimeout,
)
from pysabelle.server.models import ServerInfo
from pysabelle.server.server_process import (
    IsabelleServerProcess,
    is_server_running,
    list_servers,
)

__all__ = [
    # models
    "ServerInfo",
    # process management
    "IsabelleServerProcess",
    "list_servers",
    "is_server_running",
    # exceptions
    "IsabelleError",
    "IsabelleServerError",
    "ServerAlreadyRunning",
    "ServerNotRunning",
    "ServerStartupTimeout",
]
