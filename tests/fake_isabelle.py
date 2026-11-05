"""Stand-in for the ``isabelle`` executable, used by tests/test_server_process.py.

Supports ``server [-n NAME] [-l | -x]``.  State lives in ``$FAKE_ISABELLE_STATE``
(missing variable -> exit code 2, which lets tests check that ``env`` is used).
After printing the ready line, a spawned server writes ``$FAKE_ISABELLE_SPEW``
bytes of log output to stderr and then touches ``<state>/<name>.alive``.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import signal
import sys
import time

if "FAKE_ISABELLE_STATE" not in os.environ:
    print("FAKE_ISABELLE_STATE not set", file=sys.stderr)
    sys.exit(2)

state = pathlib.Path(os.environ["FAKE_ISABELLE_STATE"])
db = state / "servers.json"


def load() -> dict:
    return json.loads(db.read_text()) if db.exists() else {}


def save(d: dict) -> None:
    db.write_text(json.dumps(d))


def ready_line(name: str, port: int) -> str:
    return f'server "{name}" = 127.0.0.1:{port} (password "pw-{name}")'


args = sys.argv[1:]
assert args and args[0] == "server", args
args = args[1:]
name = args[args.index("-n") + 1] if "-n" in args else "isabelle"

if "-l" in args:
    for n, s in load().items():
        print(ready_line(n, s["port"]))
    sys.exit(0)

if "-x" in args:
    d = load()
    s = d.pop(name, None)
    save(d)
    if s:
        with contextlib.suppress(ProcessLookupError):
            os.kill(s["pid"], signal.SIGTERM)
    sys.exit(0)

d = load()
if name in d:  # like the real tool: report the existing server and terminate
    print(ready_line(name, d[name]["port"]), flush=True)
    sys.exit(0)

if os.environ.get("FAKE_ISABELLE_NEVER_READY"):
    time.sleep(3600)

d[name] = {"port": 4711, "pid": os.getpid()}
save(d)
print(ready_line(name, 4711), flush=True)

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
spew = int(os.environ.get("FAKE_ISABELLE_SPEW", "0"))
line = "x" * 1023 + "\n"
for _ in range(spew // 1024):
    sys.stderr.write(line)
sys.stderr.flush()
(state / f"{name}.alive").touch()
while True:
    time.sleep(0.1)
