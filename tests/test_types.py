"""(De)serialisation tests for the §4.3/§4.4 wire types."""

from __future__ import annotations

from pysabelle.raw.types import (
    Node,
    PurgeTheoriesResults,
    SessionId,
    UseTheoriesArgs,
    UseTheoriesResults,
)

from .conftest import node_entry


def test_purge_results_are_nodes() -> None:
    """Regression (M8): the server returns node objects, not strings."""
    r = PurgeTheoriesResults.from_dict({
        "purged": [{"node_name": "/x/A.thy", "theory_name": "Draft.A"}],
        "retained": [],
    })
    assert r.purged == [Node("/x/A.thy", "Draft.A")]


def test_purge_results_accept_strings() -> None:
    r = PurgeTheoriesResults.from_dict({"purged": ["/x/A.thy"]})
    assert r.purged[0].node_name == "/x/A.thy"
    assert r.retained == []


def test_use_theories_args_options() -> None:
    args = UseTheoriesArgs(SessionId("s"), ["A"], options=["show_states"], nodes_status_delay=0)
    assert args.to_dict() == {
        "session_id": "s", "theories": ["A"], "options": ["show_states"], "nodes_status_delay": 0,
    }
    assert "options" not in UseTheoriesArgs(SessionId("s"), ["A"]).to_dict()


def test_use_theories_results_flat_merge() -> None:
    r = UseTheoriesResults.from_dict({
        "ok": False,
        "errors": [{"kind": "error", "message": "bad", "pos": {"line": 3, "file": "/x/A.thy"}}],
        "nodes": [node_entry("/x/A.thy", "Draft.A", ok=False)],
    })
    assert r.errors[0].pos.line == 3 and r.errors[0].is_error
    assert r.nodes[0].node.theory_name == "Draft.A"
    assert r.nodes[0].results.status.failed == 1
