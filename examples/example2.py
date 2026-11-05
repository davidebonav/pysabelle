from __future__ import annotations

import asyncio
import logging

from pysabelle.session import (
    IsabelleSession,
    SessionAlreadyClosed,
    TheoryLoadError,
)
from pysabelle.raw.exceptions import IsabelleConnectionError, IsabelleCommandError
from pysabelle.raw.types import Message, NodeWithStatus, TheoryProgress

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-8s  %(name)s  %(message)s",
)

async def example_01_connection() -> None:
    print("\n─── Example 1: Connection and synchronous commands ───")

    async with await IsabelleSession.start("HOL") as session:
        commands = await session._client.cmd.help()
        print("Available commands:", commands)

        value   = {"hello": "isabelle", "n": 42, "nested": [1, 2, 3]}
        echoed  = await session._client.cmd.echo(value)
        assert echoed == value
        print("Echo OK:", echoed)

async def example_02_session_build() -> None:
    print("\n─── Example 2: session_build ───")

    async def on_progress(event: TheoryProgress | Message) -> None:
        if isinstance(event, TheoryProgress):
            pct = f"{event.percentage}%" if event.percentage is not None else "..."
            print(f"  [{pct:>4s}] {event.theory}")
        else:
            print(f"  [{event.kind}] {event.message}")

    async with await IsabelleSession.start("HOL") as session:
        results = await session.build(
            "HOL-Auth",
            verbose=True,
            on_progress=on_progress,
        )

    print(f"Build ok={results.ok}  rc={results.return_code}")
    for s in results.sessions:
        print(
            f"  {s.session:<30s}  ok={s.ok}  "
            f"elapsed={s.timing.elapsed:.1f}s  timeout={s.timeout}"
        )

async def example_03_use_theories() -> None:
    print("\n─── Example 3: use_theories ───")

    async with await IsabelleSession.start("HOL") as session:
        results = await session.use_theories(
            ["~~/src/HOL/Examples/Seq"],
        )

    print(f"ok={results.ok}  nodes loaded={len(results.nodes)}")
    for entry in results.nodes:
        st = entry.results.status
        print(
            f"  {entry.node.theory_name:<40s}  "
            f"ok={st.ok}  {st.finished}/{st.total}  {st.percentage}%"
        )

async def example_04_use_theories_callbacks() -> None:
    print("\n─── Example 4: use_theories with callbacks ───")

    async def on_progress(event: TheoryProgress | Message) -> None:
        if isinstance(event, TheoryProgress):
            pct = f"{event.percentage}%" if event.percentage is not None else "..."
            print(f"  progress [{pct:>4s}] {event.theory}")

    async def on_nodes_status(nodes: list[NodeWithStatus]) -> None:
        processing = [n for n in nodes if not n.status.consolidated]
        if processing:
            names = ", ".join(n.node.theory_name for n in processing[:3])
            print(f"  nodes_status — in progress: {names}")

    async with await IsabelleSession.start("HOL") as session:
        results = await session.use_theories(
            ["~~/src/HOL/Examples/Seq"],
            nodes_status_delay=0.5,
            on_progress=on_progress,
            on_nodes_status=on_nodes_status,
        )

    print(f"Completed: ok={results.ok}")

async def example_05_purge_theories() -> None:
    print("\n─── Example 5: purge_theories ───")

    async with await IsabelleSession.start("HOL") as session:
        results = await session.use_theories(
            ["~~/src/HOL/Examples/Seq"],
        )

        node_names = [entry.node.node_name for entry in results.nodes]
        purge      = await session.purge_theories(node_names)

        print(f"Purged    ({len(purge.purged)}): {purge.purged[:3]}")
        print(f"Retained  ({len(purge.retained)}): {purge.retained[:3]}")

        purge_all = await session.purge_theories(all=True)
        print(f"Purge all — purged={len(purge_all.purged)}")

async def example_06_load_and_purge() -> None:
    print("\n─── Example 6: load_and_purge ───")

    theories = [
        "~~/src/HOL/Examples/Seq",
        "~~/src/HOL/Examples/Adhoc_Overloading_Examples",
    ]

    async with await IsabelleSession.start("HOL") as session:
        for theory in theories:
            results = await session.load_and_purge([theory])
            status  = "✓" if results.ok else "✗"
            print(f"  {status}  {theory.split('/')[-1]}")

async def example_07_check_theories() -> None:
    print("\n─── Example 7: check_theories ───")

    async with await IsabelleSession.start("HOL") as session:
        errors = await session.check_theories(
            ["~~/src/HOL/Examples/Seq"]
        )

    if errors:
        print(f"{len(errors)} error(s) found:")
        for err in errors:
            pos = f" ({err.pos.file}:{err.pos.line})" if err.pos and err.pos.file else ""
            print(f"  {err.message}{pos}")
    else:
        print("No errors — theories are valid.")

async def example_08_raise_on_error() -> None:
    print("\n─── Example 8: raise_on_error ───")

    BROKEN_THEORY = "~~/src/HOL/Examples/Seq"

    async with await IsabelleSession.start("HOL") as session:
        try:
            await session.use_theories(
                [BROKEN_THEORY],
                raise_on_error=True,
            )
            print("Theories loaded without errors.")
        except TheoryLoadError as exc:
            print(f"TheoryLoadError: {len(exc.errors)} error(s)")
            for err in exc.errors:
                print(f"  {err.message}")

async def example_09_advanced_options() -> None:
    print("\n─── Example 9: Advanced options ───")

    async with await IsabelleSession.start(
        "HOL",
        options=[
            "headless_consolidate_delay=0.5",
            "headless_prune_delay=5",
        ],
        print_mode=["ASCII"],
        include_sessions=["HOL-Library"],
        verbose=True,
    ) as session:
        results = await session.use_theories(
            ["HOL-Library.Multiset"],
        )
        print(f"HOL-Library.Multiset: ok={results.ok}")

async def example_10_error_handling() -> None:
    print("\n─── Example 10: Error handling ───")

    try:
        await IsabelleSession.connect("HOL", host="127.0.0.1", port=9999)
    except IsabelleConnectionError as exc:
        print(f"[expected] Connection failed: {exc}")

    from pysabelle.raw.types import SessionId

    async with await IsabelleSession.start("HOL") as session:
        try:
            await session._client.cmd.session_stop(
                SessionId("00000000-0000-0000-0000-000000000000")
            )
        except IsabelleCommandError as exc:
            print(f"[expected] Command failed: kind={exc.kind}  msg={exc.payload}")

    session = await IsabelleSession.start("HOL")
    await session.close()

    try:
        await session.use_theories(["~~/src/HOL/Examples/Seq"])
    except SessionAlreadyClosed as exc:
        print(f"[expected] Session closed: {exc}")

async def main() -> None:
    examples = [
        example_01_connection,
        example_02_session_build,
        example_03_use_theories,
        example_04_use_theories_callbacks,
        example_05_purge_theories,
        example_06_load_and_purge,
        example_07_check_theories,
        example_08_raise_on_error,
        example_09_advanced_options,
        example_10_error_handling,
    ]

    for fn in examples:
        try:
            await fn()
        except Exception as exc:
            print(f"[ERROR in {fn.__name__}]: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    asyncio.run(main())