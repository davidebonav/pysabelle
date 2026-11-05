# pYsabelle

**A modern, async-first Python client for the [Isabelle Server](https://isabelle.in.tum.de) protocol.**

pYsabelle provides a clean, layered API to interact with Isabelle's TCP server (documented in §4 of the [Isabelle System Manual](https://isabelle.in.tum.de/doc/system.pdf)), covering everything from raw byte-level framing all the way up to a high-level session façade with typed dataclasses and async callbacks.

---

## Documentation

The complete project documentation is available on [GitHub Pages](https://davidebonav.github.io/pysabelle/).

---

## Features

- **Full protocol coverage** — implements the complete Isabelle Server protocol (§4.2-§4.4): `help`, `echo`, `shutdown`, `cancel`, `session_build`, `session_start`, `session_stop`, `use_theories`, `purge_theories`
- **Async-native** — built entirely on `asyncio`; no blocking calls on the hot path
- **Typed dataclasses** — all wire types from §4.3 are represented as `frozen` dataclasses (`Position`, `Message`, `TheoryProgress`, `NodeStatus`, `NodeResults`, `UseTheoriesResults`, etc.)
- **Three-layer architecture** — use only the abstraction level you need (raw transport → raw commands → high-level session)
- **Server lifecycle management** — can spawn, attach to, or stop an `isabelle server` subprocess automatically
- **Structured error hierarchy** — `IsabelleConnectionError`, `IsabelleProtocolError`, `IsabelleCommandError`, `IsabelleTimeoutError`, `IsabelleTaskCancelled`
- **Async progress callbacks** — typed `on_progress` and `on_nodes_status` hooks for long-running tasks
- **Timeouts and cancellation** — `timeout=` on long-running commands; on expiry (or when the awaiting asyncio task is cancelled) the server task is cancelled too
- **Python ≥ 3.10**, no runtime dependencies

---

## Architecture

```
pysabelle/
├── raw/
│   ├── transport.py     # asyncio TCP layer, §4.2 byte-message framing
│   ├── protocol.py      # RawReply parser, encode_long/short_message
│   ├── dispatcher.py    # TaskDispatcher — routes OK/NOTE/FINISHED/FAILED
│   ├── commands.py      # RawCommands — one method per server command
│   ├── types.py         # Typed dataclasses for all §4.3/§4.4 wire types
│   └── exceptions.py    # Exception hierarchy
├── server/
│   ├── server_process.py  # IsabelleServerProcess — spawn/attach/stop
│   └── models.py          # ServerInfo dataclass
├── client/
│   └── client.py          # IsabelleClient — connects transport + dispatcher + commands
└── session/
    ├── session.py         # IsabelleSession — high-level façade
    └── callbacks.py       # Typed callback helpers (ProgressCallback, NodesStatusCallback)
```

### Layer overview

| Layer | Class | Responsibility |
|---|---|---|
| Transport | `Transport` | Raw TCP framing per §4.2; `send` / `receive` primitives |
| Dispatcher | `TaskDispatcher` | Multiplexes sync (`OK`/`ERROR`) and async (`NOTE`/`FINISHED`/`FAILED`) replies |
| Commands | `RawCommands` | One `async` method per Isabelle server command; returns typed results |
| Client | `IsabelleClient` | Composes transport + dispatcher + commands; manages server process |
| Session | `IsabelleSession` | High-level entry point with convenience methods and progress callbacks |

---

## Installation

From [PyPI](https://pypi.org/project/pysabelle/):

```bash
pip install pysabelle
```

Or from source:

```bash
git clone https://github.com/davidebonav/pysabelle.git
cd pysabelle
pip install -e .
```

**Requirements:** Python ≥ 3.10, a working `isabelle` binary on `$PATH`.
Tested with Isabelle2025-2; the protocol follows the Isabelle2026 System Manual.

Optional dev dependencies:

```bash
pip install -e ".[test]"   # pytest, pytest-asyncio, pytest-timeout, ruff
pip install -e ".[docs]"   # Sphinx + Read the Docs theme
```

---

## Quick Start

### High-level API — `IsabelleSession`

The recommended entry point. Handles server startup, session lifecycle, and cleanup automatically via async context manager.

```python
import asyncio
from pysabelle import IsabelleSession

async def main():
    async with await IsabelleSession.start("HOL") as session:
        results = await session.use_theories(
            ["~~/src/HOL/Examples/Seq"]
        )
        print(f"ok={results.ok}  nodes={len(results.nodes)}")
        for entry in results.nodes:
            st = entry.results.status
            print(f"  {entry.node.theory_name}  {st.finished}/{st.total} commands")

asyncio.run(main())
```

#### Connect to an already-running server

```python
async with await IsabelleSession.connect(
    "HOL",
    host="127.0.0.1",
    port=4711,
    password="<password>",
) as session:
    ...
```

#### Progress callbacks

```python
from pysabelle.raw.types import TheoryProgress, Message

async def on_progress(event: TheoryProgress | Message) -> None:
    if isinstance(event, TheoryProgress):
        pct = f"{event.percentage}%" if event.percentage is not None else "..."
        print(f"  [{pct:>4s}] {event.theory}")

async with await IsabelleSession.start("HOL", on_progress=on_progress) as session:
    results = await session.use_theories(["~~/src/HOL/Examples/Seq"])
```

#### `nodes_status` callback during `use_theories`

```python
from pysabelle.raw.types import NodeWithStatus

async def on_nodes_status(nodes: list[NodeWithStatus]) -> None:
    in_progress = [n for n in nodes if not n.status.consolidated]
    print(f"  in-progress: {[n.node.theory_name for n in in_progress[:3]]}")

async with await IsabelleSession.start("HOL") as session:
    await session.use_theories(
        ["~~/src/HOL/Examples/Seq"],
        nodes_status_delay=0.5,
        on_nodes_status=on_nodes_status,
    )
```

#### Convenience methods

```python
async with await IsabelleSession.start("HOL") as session:
    # Load and immediately purge the theories and their imports (low memory footprint).
    # Caveat (Isabelle2025-2): a purged theory cannot be loaded again in the same session.
    results = await session.load_and_purge(["~~/src/HOL/Examples/Seq"])

    # Give up after 120 s: the server task is cancelled, IsabelleTimeoutError is raised
    results = await session.use_theories(["~~/src/HOL/Examples/Seq"], timeout=120)

    # Return only errors (empty list = no errors)
    errors = await session.check_theories(["~~/src/HOL/Examples/Seq"])

    # Raise on first error instead of returning error list
    await session.use_theories(
        ["~~/src/HOL/Examples/Seq"],
        raise_on_error=True,   # raises TheoryLoadError
    )

    # Build a session dependency
    build_results = await session.build("HOL-Auth", verbose=True)
```

---

### Mid-level API — `IsabelleClient` + `RawCommands`

Use this when you need direct access to server commands without the session façade.

```python
from pysabelle import IsabelleClient
from pysabelle.raw.types import SessionBuildArgs, UseTheoriesArgs, SessionId

async def main():
    async with await IsabelleClient.start() as client:
        # Synchronous commands
        print(await client.help())
        print(await client.echo({"key": "value"}))

        # Start a PIDE session
        result = await client.session_start(SessionBuildArgs(session="HOL"))
        sid: SessionId = result.session_id

        # Load theories
        use_args = UseTheoriesArgs(
            session_id=sid,
            theories=["~~/src/HOL/Examples/Seq"],
            nodes_status_delay=0.5,
        )
        results = await client.use_theories(use_args)

        await client.session_stop(sid)
```

---

### Low-level API — `Transport` + `TaskDispatcher`

For direct protocol interaction or testing.

```python
from pysabelle.raw.transport import Transport

async def main():
    async with await Transport.open("127.0.0.1", 4711) as t:
        await t.send("<password>", is_long_msg=False)   # handshake
        reply = await t.receive()
        print(reply.is_ok, reply.argument_raw)
```

---

## Server Lifecycle

`IsabelleServerProcess` manages the `isabelle server` subprocess:

```python
from pysabelle.server import IsabelleServerProcess

# Spawn a fresh server
with IsabelleServerProcess(name="my-server", force_start=True) as srv:
    print(srv.info)   # ServerInfo(host, port, password)

# Attach to an existing server (no ownership)
srv = IsabelleServerProcess(name="isabelle", assume_existing=True)
srv.start()

# IsabelleClient.start() wraps this automatically
client = await IsabelleClient.start(name="isabelle", reuse_existing=True)
```

`list_servers()` and `is_server_running()` are also available as standalone utilities.

---

## Error Handling

```python
from pysabelle.raw.exceptions import (
    IsabelleError,             # common root of every pYsabelle exception
    IsabelleConnectionError,   # TCP-level failure
    IsabelleProtocolError,     # Framing violation (§4.2)
    IsabelleCommandError,      # ERROR reply or FAILED task
    IsabelleTimeoutError,      # Task timed out
    IsabelleTaskCancelled,     # Task ended with FAILED {"message": "Interrupt"}
)
from pysabelle.session.exceptions import (
    TheoryLoadError,           # use_theories with raise_on_error=True
    SessionAlreadyClosed,      # Method called on a closed session
)

async with await IsabelleSession.start("HOL") as session:
    try:
        await session.use_theories(["BadTheory"], raise_on_error=True)
    except TheoryLoadError as exc:
        for err in exc.errors:
            pos = f" ({err.pos.file}:{err.pos.line})" if err.pos else ""
            print(f"ERROR: {err.message}{pos}")
    except IsabelleCommandError as exc:
        print(f"Server error: kind={exc.kind}  payload={exc.payload}")
    except IsabelleTimeoutError as exc:
        print(f"Timeout after {exc.timeout}s on task {exc.task_id}")
```

---

## Wire Types Reference

All types mirror §4.3 of the Isabelle System Manual. Key classes:

| Type | Description |
|---|---|
| `Position` | Source position (`line`, `offset`, `end_offset`, `file`) |
| `Message` | Prover output message with `kind` and optional `Position` |
| `ErrorMessage` | Specialised message with `kind = "error"` |
| `TheoryProgress` | Progress NOTE during session build/start (`theory`, `session`, `percentage`) |
| `Timing` | Wall-clock timing (`elapsed`, `cpu`, `gc`) in seconds |
| `NodeStatus` | PIDE processing status: `ok`, `total`, `finished`, `failed`, `consolidated`, `percentage` |
| `Node` | Theory node identity: `node_name` (path) + `theory_name` |
| `NodeWithStatus` | Node + NodeStatus (from `nodes_status` NOTE payloads) |
| `NodeResults` | Per-node: `status` + `messages` + `exports` |
| `NodeResultEntry` | Node + NodeResults (from `use_theories` result) |
| `SessionBuildArgs` | Arguments for `session_build` / `session_start` |
| `SessionBuildResults` | Aggregate result of `session_build` |
| `SessionStartResult` | `session_id` + `tmp_dir` from `session_start` |
| `SessionStopResult` | `ok` + `return_code` from `session_stop` |
| `UseTheoriesArgs` | Arguments for `use_theories` (includes watchdog, check delays, export pattern) |
| `UseTheoriesResults` | `ok` + `errors` + per-node `nodes` |
| `PurgeTheoriesArgs` / `PurgeTheoriesResults` | Arguments and result for `purge_theories` (`purged` / `retained` are lists of `Node`) |
| `TaskId` / `SessionId` | Typed UUID wrappers to prevent accidental swap |

---

## Advanced Options

`IsabelleSession.start()` / `IsabelleSession.connect()` forward Isabelle options directly:

```python
async with await IsabelleSession.start(
    "HOL",
    options=[
        "headless_consolidate_delay=0.5",
        "headless_prune_delay=5",
        "timeout=120",
    ],
    print_mode=["ASCII"],              # disable Unicode symbols
    include_sessions=["HOL-Library"],  # extend the session namespace
    verbose=True,
) as session:
    results = await session.use_theories(["HOL-Library.Multiset"])
```

`use_theories` also exposes fine-grained knobs:

```python
results = await session.use_theories(
    theories=["MyTheory"],
    master_dir="/path/to/project",
    pretty_margin=100,
    unicode_symbols=False,
    export_pattern="*:*",           # retrieve all theory exports
    check_delay=0.2,
    check_limit=0,                  # unbounded
    watchdog_timeout=300,
    nodes_status_delay=1.0,
)
```

---

## Development

```bash
pip install -e ".[test]"
pytest                 # unit tests (an in-process fake server, no Isabelle needed)
pytest -m isabelle     # integration tests: need `isabelle` on PATH and the HOL heap
ruff check src tests
```

Integration tests start a dedicated server named `pysabelle-pytest` and are
skipped automatically when no `isabelle` executable is found.

---

## License

[AGPL-3.0-or-later](LICENSE)