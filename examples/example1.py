from __future__ import annotations

import logging
import asyncio

from pysabelle.client.client import IsabelleClient
from pysabelle.raw.exceptions import (
    IsabelleCommandError,
    IsabelleConnectionError,
)
from pysabelle.raw.protocol import RawReply
from pysabelle.raw.transport import Transport
from pysabelle.raw.types import (
    PurgeTheoriesArgs,
    SessionBuildArgs,
    SessionId,
    TheoryProgress,
    UseTheoriesArgs,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

async def example_help_echo() -> None:
    async with await IsabelleClient.start() as cmd:
        names = await cmd.help()
        print("Available commands:", names)

        value = {"hello": "isabelle", "n": 42}
        result = await cmd.echo(value)
        assert result == value
        print("Echo OK:", result)

async def example_session_build() -> None:
    async def on_note(reply: RawReply) -> None:
        payload = reply.json() or {}
        if TheoryProgress.is_theory_progress(payload):
            tp  = TheoryProgress.from_dict(payload)
            pct = f"{tp.percentage}%" if tp.percentage is not None else "..."
            print(f"  [{pct:>4s}] {tp.theory}")
        else:
            print(f"  NOTE: {payload.get('message', reply.argument_raw)}")

    async with await IsabelleClient.start() as cmd:
        args = SessionBuildArgs(session="HOL-Auth", verbose=True)

        print("Starting session_build HOL.Auth ...")
        results = await cmd.session_build(args, on_note=on_note)

        print("Build OK:", results.ok)
        for s in results.sessions:
            print(
                f"  {s.session}: ok={s.ok}  "
                f"elapsed={s.timing.elapsed:.1f}s  timeout={s.timeout}"
            )

async def example_session_lifecycle() -> None:
    async with await IsabelleClient.start() as cmd:
        print("Starting HOL session ...")
        result = await cmd.session_start(SessionBuildArgs(session="HOL-Auth"))

        sid: SessionId = result.session_id
        print(f"Session started — id={sid}  tmp={result.tmp_dir}")

        stop = await cmd.session_stop(sid)
        print(f"Session stopped  — ok={stop.ok}  rc={stop.return_code}")

async def example_use_theories() -> None:
    async def on_note(reply: RawReply) -> None:
        payload = reply.json() or {}
        for entry in payload.get("nodes_status", []):
            status = entry.get("status", {})
            print(
                f"  {entry.get('theory_name', '?'):40s}  "
                f"{status.get('percentage', 0):3d}%"
            )

    async with await IsabelleClient.start() as cmd:
        result = await cmd.session_start(SessionBuildArgs(session="HOL"))
        sid    = result.session_id

        use_args = UseTheoriesArgs(
            session_id=sid,
            theories=["~~/src/HOL/Examples/Seq"],
            nodes_status_delay=0.5,
        )

        print("Loading Seq ...")
        results = await cmd.use_theories(use_args, on_note=on_note)

        if results.ok:
            print("Theories loaded.")
        else:
            for err in results.errors:
                pos = f" ({err.pos.file}:{err.pos.line})" if err.pos else ""
                print(f"  ERROR: {err.message}{pos}")

        for entry in results.nodes:
            st = entry.results.status
            print(
                f"  {entry.node.theory_name:40s}  "
                f"ok={st.ok}  {st.finished}/{st.total} commands"
            )

        await cmd.session_stop(sid)

async def example_purge_theories() -> None:
    async with await IsabelleClient.start() as cmd:
        result = await cmd.session_start(SessionBuildArgs(session="HOL"))
        sid    = result.session_id

        await cmd.use_theories(UseTheoriesArgs(
            session_id=sid,
            theories=["~~/src/HOL/Examples/Seq"],
        ))

        purge = await cmd.purge_theories(PurgeTheoriesArgs(
            session_id=sid,
            all=True,
        ))

        print("Purged:  ", purge.purged)
        print("Retained:", purge.retained)

        await cmd.session_stop(sid)

async def example_error_handling() -> None:
    try:
        await Transport.open("127.0.0.1", 9999, timeout=2.0)
    except IsabelleConnectionError as e:
        print(f"[expected] Connection failed: {e}")

    async with await IsabelleClient.start() as cmd:
        try:
            await cmd.session_stop(
                SessionId("00000000-0000-0000-0000-000000000000")
            )
        except IsabelleCommandError as e:
            print(f"[expected] Command failed: kind={e.kind}  payload={e.payload}")

if __name__ == "__main__":
    asyncio.run(example_use_theories())
    asyncio.run(example_purge_theories())