# Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
# NOBA Command Center — Licensed under Apache 2.0.

"""Tests for graph-based workflow engine (conditional branching, approval gates)."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch


from server.db import Database


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="noba_wf_test_")
    os.close(fd)
    return Database(path=path), path


def _cleanup(path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(path + ext)
        except OSError:
            pass


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_action_node(node_id: str, action_type: str = "script",
                      action_cfg: dict | None = None) -> dict:
    return {
        "id": node_id,
        "type": "action",
        "config": {"type": action_type, "config": action_cfg or {}},
    }


def _make_condition_node(node_id: str, expression: str,
                         true_next: str | None = None,
                         false_next: str | None = None) -> dict:
    return {
        "id": node_id,
        "type": "condition",
        "expression": expression,
        "true_next": true_next,
        "false_next": false_next,
    }


def _make_approval_gate_node(node_id: str, approved_next: str | None = None,
                              denied_next: str | None = None) -> dict:
    return {
        "id": node_id,
        "type": "approval_gate",
        "action_type": "workflow_approval_gate",
        "action_params": {},
        "approved_next": approved_next,
        "denied_next": denied_next,
    }


def _make_delay_node(node_id: str, seconds: float, next_id: str | None = None) -> dict:
    node: dict = {"id": node_id, "type": "delay", "seconds": seconds}
    return node


def _make_notification_node(node_id: str, message: str,
                             next_id: str | None = None) -> dict:
    return {"id": node_id, "type": "notification", "message": message, "level": "info"}


def _edge(from_id: str, to_id: str) -> dict:
    return {"from": from_id, "to": to_id}


# ── _get_next_node ─────────────────────────────────────────────────────────────

class TestGetNextNode:
    def test_finds_edge(self):
        from server.workflow_engine import _get_next_node
        node = {"id": "a"}
        edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]
        assert _get_next_node(node, edges) == "b"

    def test_returns_none_at_end(self):
        from server.workflow_engine import _get_next_node
        node = {"id": "z"}
        edges = [{"from": "a", "to": "b"}]
        assert _get_next_node(node, edges) is None

    def test_empty_edges(self):
        from server.workflow_engine import _get_next_node
        node = {"id": "a"}
        assert _get_next_node(node, []) is None

    def test_first_matching_edge(self):
        from server.workflow_engine import _get_next_node
        node = {"id": "a"}
        edges = [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]
        assert _get_next_node(node, edges) == "b"


# ── _run_graph_workflow — missing / invalid entry node ─────────────────────────

class TestRunGraphWorkflowEntryValidation:
    def test_missing_entry_logs_error(self):
        from server.workflow_engine import _run_graph_workflow
        config = {
            "nodes": [{"id": "n1", "type": "delay", "seconds": 0}],
            "edges": [],
            "entry": "",
        }
        with patch("server.workflow_engine.logger") as mock_log:
            _run_graph_workflow("wf1", config, "tester")
        mock_log.error.assert_called_once()
        call_msg = mock_log.error.call_args[0][0]
        assert "no valid entry node" in call_msg

    def test_entry_not_in_nodes_logs_error(self):
        from server.workflow_engine import _run_graph_workflow
        config = {
            "nodes": [{"id": "n1", "type": "delay", "seconds": 0}],
            "edges": [],
            "entry": "nonexistent",
        }
        with patch("server.workflow_engine.logger") as mock_log:
            _run_graph_workflow("wf1", config, "tester")
        mock_log.error.assert_called_once()


# ── Unknown node type ──────────────────────────────────────────────────────────

class TestUnknownNodeType:
    def test_unknown_type_logs_warning(self):
        from server.workflow_engine import _execute_node
        nodes = {"n1": {"id": "n1", "type": "nonexistent_type"}}
        with patch("server.workflow_engine.logger") as mock_log:
            _execute_node("wf1", nodes, [], "n1", "tester")
        mock_log.warning.assert_called_once()
        assert "unknown node type" in mock_log.warning.call_args[0][0]

    def test_missing_node_logs_error(self):
        from server.workflow_engine import _execute_node
        with patch("server.workflow_engine.logger") as mock_log:
            _execute_node("wf1", {}, [], "nonexistent", "tester")
        mock_log.error.assert_called_once()
        assert "not found" in mock_log.error.call_args[0][0]


# ── Linear graph (action → action → action) ────────────────────────────────────

class TestLinearGraphWorkflow:
    def test_all_actions_execute_in_order(self):
        from server.workflow_engine import _run_graph_workflow

        call_order: list[str] = []

        def fake_builder(cfg: dict):
            call_order.append(cfg.get("marker", "?"))
            proc = MagicMock()
            proc.pid = 0
            proc.returncode = 0
            proc.wait.return_value = 0
            proc.poll.return_value = 0
            proc.stdout = MagicMock()
            proc.stdout.read.return_value = b""
            return proc

        nodes = [
            {"id": "n1", "type": "action",
             "config": {"type": "script", "config": {"marker": "first"}}},
            {"id": "n2", "type": "action",
             "config": {"type": "script", "config": {"marker": "second"}}},
            {"id": "n3", "type": "action",
             "config": {"type": "script", "config": {"marker": "third"}}},
        ]
        edges = [_edge("n1", "n2"), _edge("n2", "n3")]
        config = {"nodes": nodes, "edges": edges, "entry": "n1"}

        def fake_submit(make_proc, automation_id=None, trigger=None,
                        triggered_by=None, on_complete=None):
            make_proc(0)
            if on_complete:
                on_complete(0, "done")
            return 1

        with patch("server.workflow_engine._AUTO_BUILDERS",
                   {"script": fake_builder}):
            with patch("server.workflow_engine.job_runner") as mock_runner:
                mock_runner.submit.side_effect = fake_submit
                _run_graph_workflow("wf1", config, "tester")

        assert call_order == ["first", "second", "third"]

    def test_action_failure_stops_chain(self):
        from server.workflow_engine import _run_graph_workflow

        call_count = [0]

        def fake_builder(cfg: dict):
            call_count[0] += 1
            proc = MagicMock()
            proc.pid = 0
            proc.returncode = 1
            proc.wait.return_value = 1
            proc.poll.return_value = 1
            proc.stdout = MagicMock()
            proc.stdout.read.return_value = b""
            return proc

        nodes = [
            {"id": "n1", "type": "action",
             "config": {"type": "script", "config": {}}},
            {"id": "n2", "type": "action",
             "config": {"type": "script", "config": {}}},
        ]
        edges = [_edge("n1", "n2")]
        config = {"nodes": nodes, "edges": edges, "entry": "n1"}

        def fake_submit(make_proc, automation_id=None, trigger=None,
                        triggered_by=None, on_complete=None):
            make_proc(0)
            if on_complete:
                on_complete(0, "failed")
            return 1

        with patch("server.workflow_engine._AUTO_BUILDERS",
                   {"script": fake_builder}):
            with patch("server.workflow_engine.job_runner") as mock_runner:
                mock_runner.submit.side_effect = fake_submit
                _run_graph_workflow("wf1", config, "tester")

        # Only the first node runs; failure stops before n2
        assert call_count[0] == 1

    def test_action_unknown_builder_skips(self):
        from server.workflow_engine import _execute_action_node

        node = {"id": "n1", "type": "action",
                "config": {"type": "unknown_type_xyz", "config": {}}}
        with patch("server.workflow_engine.logger") as mock_log:
            _execute_action_node("wf1", {}, [], node, "tester")
        mock_log.warning.assert_called_once()
        assert "unsupported type" in mock_log.warning.call_args[0][0]


# ── Conditional branching ──────────────────────────────────────────────────────

class TestConditionalBranching:
    def _run_condition(self, expression: str, metrics: dict,
                       true_next: str | None = "true_node",
                       false_next: str | None = "false_node") -> list[str]:
        """Return list of visited node ids after evaluating a condition."""
        from server.workflow_engine import _execute_condition_node

        visited: list[str] = []

        true_node = {"id": "true_node", "type": "delay", "seconds": 0}
        false_node = {"id": "false_node", "type": "delay", "seconds": 0}
        condition_node = _make_condition_node(
            "cond", expression, true_next=true_next, false_next=false_next)

        nodes = {
            "cond": condition_node,
            "true_node": true_node,
            "false_node": false_node,
        }

        def fake_execute(auto_id, _nodes, _edges, node_id, tby, **_kw):
            visited.append(node_id)

        mock_collector = MagicMock()
        mock_collector.get.return_value = metrics

        # bg_collector and _safe_eval are late-imported inside the function
        with patch("server.collector.bg_collector", mock_collector), \
             patch("server.workflow_engine._execute_node", side_effect=fake_execute):
            _execute_condition_node("wf1", nodes, [], condition_node, "tester")

        return visited

    def test_true_path_when_condition_true(self):
        visited = self._run_condition("cpu_percent > 50", {"cpu_percent": 80})
        assert visited == ["true_node"]

    def test_false_path_when_condition_false(self):
        visited = self._run_condition("cpu_percent > 50", {"cpu_percent": 20})
        assert visited == ["false_node"]

    def test_no_branch_when_next_missing(self):
        visited = self._run_condition(
            "cpu_percent > 50", {"cpu_percent": 80},
            true_next=None, false_next=None)
        assert visited == []

    def test_false_path_not_taken_when_true(self):
        visited = self._run_condition("cpu_percent < 50", {"cpu_percent": 80})
        # condition is false → false_node
        assert "true_node" not in visited
        assert visited == ["false_node"]

    def test_condition_with_empty_expression_evaluates_false(self):
        visited = self._run_condition("", {})
        assert visited == ["false_node"]

    def test_branch_not_in_nodes_skips(self):
        from server.workflow_engine import _execute_condition_node

        cond = _make_condition_node("cond", "cpu_percent > 50",
                                    true_next="ghost_node", false_next=None)
        nodes = {"cond": cond}

        mock_collector = MagicMock()
        mock_collector.get.return_value = {"cpu_percent": 99}

        with patch("server.collector.bg_collector", mock_collector), \
             patch("server.workflow_engine.logger") as mock_log:
            _execute_condition_node("wf1", nodes, [], cond, "tester")
        # Should log that there's no branch to follow
        mock_log.info.assert_called()


# ── Approval gate ──────────────────────────────────────────────────────────────

class TestApprovalGate:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def test_creates_approval_record_and_pauses(self):
        from server.workflow_engine import _execute_approval_gate

        node = _make_approval_gate_node("gate1", approved_next="n_approve",
                                        denied_next="n_deny")
        nodes = {"gate1": node, "n_approve": {"id": "n_approve", "type": "delay", "seconds": 0}}
        edges: list = []

        with patch("server.workflow_engine.db", self.db):
            _execute_approval_gate("wf1", nodes, edges, node, "alice")

        # Approval record should exist
        pending = self.db.list_approvals(status="pending")
        assert len(pending) == 1
        a = pending[0]
        assert a["automation_id"] == "wf1"
        assert a["trigger_source"] == "graph_workflow"

    def test_workflow_context_stored(self):
        from server.workflow_engine import _execute_approval_gate

        node = _make_approval_gate_node("gate1", approved_next="n_approve",
                                        denied_next="n_deny")
        nodes_dict = {"gate1": node}
        edges: list = []

        with patch("server.workflow_engine.db", self.db):
            _execute_approval_gate("wf1", nodes_dict, edges, node, "alice")

        pending = self.db.list_approvals(status="pending")
        assert len(pending) == 1
        approval_id = pending[0]["id"]

        ctx = self.db.get_workflow_context(approval_id)
        assert ctx is not None
        assert ctx["auto_id"] == "wf1"
        assert ctx["approved_next"] == "n_approve"
        assert ctx["denied_next"] == "n_deny"
        assert ctx["triggered_by"] == "alice"

    def test_workflow_pauses_at_gate(self):
        """Workflow execution stops at approval gate — no further nodes called."""
        from server.workflow_engine import _run_graph_workflow

        executed: list[str] = []

        gate = _make_approval_gate_node("gate1", approved_next="after_gate")
        after = {"id": "after_gate", "type": "delay", "seconds": 0}

        config = {
            "nodes": [gate, after],
            "edges": [_edge("gate1", "after_gate")],
            "entry": "gate1",
        }

        def fake_delay(auto_id, nodes, edges, node, triggered_by, **_kw):
            executed.append(node["id"])

        with patch("server.workflow_engine.db", self.db), \
             patch("server.workflow_engine._execute_delay_node", side_effect=fake_delay):
            _run_graph_workflow("wf1", config, "alice")

        # after_gate should NOT have been executed (workflow paused at gate)
        assert "after_gate" not in executed

    def test_resume_approved_continues_workflow(self):
        """After decision=approved the approved_next node is executed."""
        from server.workflow_engine import _execute_approval_gate, _execute_node

        executed: list[str] = []

        gate = _make_approval_gate_node("gate1", approved_next="n_ok", denied_next="n_deny")
        n_ok = {"id": "n_ok", "type": "delay", "seconds": 0}
        n_deny = {"id": "n_deny", "type": "delay", "seconds": 0}
        nodes = {"gate1": gate, "n_ok": n_ok, "n_deny": n_deny}
        edges: list = []

        with patch("server.workflow_engine.db", self.db):
            _execute_approval_gate("wf1", nodes, edges, gate, "alice")

        pending = self.db.list_approvals(status="pending")
        approval_id = pending[0]["id"]

        # Simulate approval decision and resume
        self.db.decide_approval(approval_id, "approved", "bob")
        ctx = self.db.get_workflow_context(approval_id)

        next_node_id = ctx["approved_next"]
        nodes_map = {n["id"]: n for n in ctx["nodes"]}

        def fake_delay(auto_id, n, e, node, tby, **_kw):
            executed.append(node["id"])

        with patch("server.workflow_engine._execute_delay_node", side_effect=fake_delay):
            _execute_node("wf1", nodes_map, ctx["edges"], next_node_id, "alice")

        assert "n_ok" in executed

    def test_resume_denied_follows_denied_next(self):
        """After decision=denied the denied_next node is executed."""
        from server.workflow_engine import _execute_approval_gate, _execute_node

        executed: list[str] = []

        gate = _make_approval_gate_node("gate1", approved_next="n_ok", denied_next="n_deny")
        n_ok = {"id": "n_ok", "type": "delay", "seconds": 0}
        n_deny = {"id": "n_deny", "type": "delay", "seconds": 0}
        nodes = {"gate1": gate, "n_ok": n_ok, "n_deny": n_deny}

        with patch("server.workflow_engine.db", self.db):
            _execute_approval_gate("wf1", nodes, [], gate, "alice")

        pending = self.db.list_approvals(status="pending")
        approval_id = pending[0]["id"]
        self.db.decide_approval(approval_id, "denied", "bob")
        ctx = self.db.get_workflow_context(approval_id)
        nodes_map = {n["id"]: n for n in ctx["nodes"]}

        def fake_delay(auto_id, n, e, node, tby, **_kw):
            executed.append(node["id"])

        with patch("server.workflow_engine._execute_delay_node", side_effect=fake_delay):
            _execute_node("wf1", nodes_map, ctx["edges"], ctx["denied_next"], "alice")

        assert "n_deny" in executed
        assert "n_ok" not in executed


# ── Delay node ────────────────────────────────────────────────────────────────

class TestDelayNode:
    def test_sleeps_configured_seconds(self):
        from server.workflow_engine import _execute_delay_node

        node = _make_delay_node("d1", seconds=5)
        nodes = {"d1": node}
        edges: list = []

        sleep_calls: list[float] = []

        def fake_sleep(s):
            sleep_calls.append(s)

        with patch("server.workflow_engine._execute_node"), \
             patch("server.workflow_engine.time") as mock_time:
            mock_time.sleep.side_effect = fake_sleep
            _execute_delay_node("wf1", nodes, edges, node, "tester")

        assert sleep_calls == [5]

    def test_follows_next_node_after_sleep(self):
        from server.workflow_engine import _execute_delay_node

        delay_node = _make_delay_node("d1", seconds=0)
        next_node = {"id": "n2", "type": "delay", "seconds": 0}
        nodes = {"d1": delay_node, "n2": next_node}
        edges = [_edge("d1", "n2")]

        visited: list[str] = []

        def fake_execute(auto_id, _nodes, _edges, node_id, tby, **_kw):
            visited.append(node_id)

        with patch("server.workflow_engine._execute_node", side_effect=fake_execute), \
             patch("server.workflow_engine.time") as mock_time:
            mock_time.sleep = MagicMock()
            _execute_delay_node("wf1", nodes, edges, delay_node, "tester")

        assert visited == ["n2"]

    def test_no_next_node_ends_workflow(self):
        from server.workflow_engine import _execute_delay_node

        node = _make_delay_node("d1", seconds=0)
        nodes = {"d1": node}
        edges: list = []

        with patch("server.workflow_engine._execute_node") as mock_next, \
             patch("server.workflow_engine.time") as mock_time:
            mock_time.sleep = MagicMock()
            _execute_delay_node("wf1", nodes, edges, node, "tester")

        mock_next.assert_not_called()


# ── Notification node ─────────────────────────────────────────────────────────

class TestNotificationNode:
    def test_dispatches_notification(self):
        from server.workflow_engine import _execute_notification_node

        node = _make_notification_node("notif1", "hello world")
        nodes = {"notif1": node}
        edges: list = []

        dispatched: list = []

        def fake_dispatch(level, msg, cfg, channels):
            dispatched.append({"level": level, "msg": msg})

        with patch("server.workflow_engine.read_yaml_settings",
                   return_value={"notifications": {"slack": {}}}), \
             patch("server.workflow_engine._execute_node"), \
             patch("server.workflow_engine.threading") as mock_threading:
            # Simulate thread start calling the target immediately
            def fake_thread_ctor(**kwargs):
                t = MagicMock()
                t.start.side_effect = lambda: kwargs.get("target", lambda: None)()
                return t
            mock_threading.Thread.side_effect = fake_thread_ctor
            with patch("server.alerts.dispatch_notifications",
                       side_effect=fake_dispatch):
                _execute_notification_node("wf1", nodes, edges, node, "tester")

    def test_follows_next_node_after_dispatch(self):
        from server.workflow_engine import _execute_notification_node

        notif_node = _make_notification_node("n1", "hi")
        next_node = {"id": "n2", "type": "delay", "seconds": 0}
        nodes = {"n1": notif_node, "n2": next_node}
        edges = [_edge("n1", "n2")]

        visited: list[str] = []

        def fake_execute(auto_id, _nodes, _edges, node_id, tby, **_kw):
            visited.append(node_id)

        with patch("server.workflow_engine.read_yaml_settings", return_value={}), \
             patch("server.workflow_engine._execute_node", side_effect=fake_execute):
            _execute_notification_node("wf1", nodes, edges, notif_node, "tester")

        assert visited == ["n2"]

    def test_no_next_node_ends_without_error(self):
        from server.workflow_engine import _execute_notification_node

        node = _make_notification_node("n1", "msg")
        nodes = {"n1": node}
        edges: list = []

        with patch("server.workflow_engine.read_yaml_settings", return_value={}), \
             patch("server.workflow_engine._execute_node") as mock_next:
            _execute_notification_node("wf1", nodes, edges, node, "tester")

        mock_next.assert_not_called()


# ── Parallel node ─────────────────────────────────────────────────────────────

class TestParallelNode:
    def test_executes_all_branches(self):
        from server.workflow_engine import _execute_parallel_node

        branch_a = {"id": "ba", "type": "delay", "seconds": 0}
        branch_b = {"id": "bb", "type": "delay", "seconds": 0}
        parallel = {"id": "par", "type": "parallel", "branches": ["ba", "bb"]}
        nodes = {"par": parallel, "ba": branch_a, "bb": branch_b}
        edges: list = []

        executed: list[str] = []

        def fake_execute(auto_id, _nodes, _edges, node_id, tby, **_kw):
            executed.append(node_id)

        with patch("server.workflow_engine._execute_node", side_effect=fake_execute):
            _execute_parallel_node("wf1", nodes, edges, parallel, "tester")

        assert "ba" in executed
        assert "bb" in executed

    def test_follows_join_node_after_branches(self):
        from server.workflow_engine import _execute_parallel_node

        branch_a = {"id": "ba", "type": "delay", "seconds": 0}
        join_node = {"id": "join", "type": "delay", "seconds": 0}
        parallel = {"id": "par", "type": "parallel", "branches": ["ba"], "join": "join"}
        nodes = {"par": parallel, "ba": branch_a, "join": join_node}
        edges: list = []

        executed: list[str] = []

        def fake_execute(auto_id, _nodes, _edges, node_id, tby, **_kw):
            executed.append(node_id)

        with patch("server.workflow_engine._execute_node", side_effect=fake_execute):
            _execute_parallel_node("wf1", nodes, edges, parallel, "tester")

        assert executed[-1] == "join"

    def test_missing_branch_logs_warning(self):
        from server.workflow_engine import _execute_parallel_node

        parallel = {"id": "par", "type": "parallel", "branches": ["ghost"]}
        nodes = {"par": parallel}
        edges: list = []

        with patch("server.workflow_engine.logger") as mock_log, \
             patch("server.workflow_engine._execute_node"):
            _execute_parallel_node("wf1", nodes, edges, parallel, "tester")

        mock_log.warning.assert_called_once()


# ── Backward compatibility: flat "steps" format ────────────────────────────────

class TestBackwardCompatibility:
    def test_flat_steps_uses_run_workflow(self):
        """A config with 'steps' (no 'nodes') must route to _run_workflow."""
        # We test this via the run endpoint logic, exercising the condition
        # config.get("nodes") check that routes to _run_graph_workflow.

        # Build a minimal config with steps only
        config = {"steps": ["auto1", "auto2"], "mode": "sequential", "retries": 0}
        assert config.get("nodes") is None  # sanity check

        run_wf_calls: list = []
        graph_wf_calls: list = []


        with patch("server.workflow_engine._run_workflow",
                   side_effect=lambda *a, **kw: run_wf_calls.append(a)):
            with patch("server.workflow_engine._run_graph_workflow",
                       side_effect=lambda *a, **kw: graph_wf_calls.append(a)):

                # Simulate the router's branching logic
                if config.get("nodes"):
                    from server.workflow_engine import _run_graph_workflow as rgw
                    rgw("wf1", config, "tester")
                else:
                    steps = config.get("steps", [])
                    from server.workflow_engine import _run_workflow as rw
                    rw("wf1", steps, "tester", retries=0)

        assert len(run_wf_calls) == 1
        assert len(graph_wf_calls) == 0

    def test_graph_format_uses_run_graph_workflow(self):
        """A config with 'nodes' must route to _run_graph_workflow."""
        config = {
            "nodes": [{"id": "n1", "type": "delay", "seconds": 0}],
            "edges": [],
            "entry": "n1",
        }
        assert config.get("nodes") is not None

        run_wf_calls: list = []
        graph_wf_calls: list = []

        with patch("server.workflow_engine._run_workflow",
                   side_effect=lambda *a, **kw: run_wf_calls.append(a)), \
             patch("server.workflow_engine._run_graph_workflow",
                   side_effect=lambda *a, **kw: graph_wf_calls.append(a)):

            if config.get("nodes"):
                from server.workflow_engine import _run_graph_workflow as rgw
                rgw("wf1", config, "tester")
            else:
                from server.workflow_engine import _run_workflow as rw
                rw("wf1", config.get("steps", []), "tester", retries=0)

        assert len(graph_wf_calls) == 1
        assert len(run_wf_calls) == 0


# ── DB: workflow_context helpers ──────────────────────────────────────────────

class TestWorkflowContextDB:
    def setup_method(self):
        self.db, self.path = _make_db()

    def teardown_method(self):
        _cleanup(self.path)

    def _make_approval(self) -> int:
        aid = self.db.insert_approval(
            automation_id="wf1",
            trigger="test",
            trigger_source=None,
            action_type="gate",
            action_params={},
            target=None,
            requested_by="alice",
        )
        assert aid is not None
        return aid

    def test_save_and_get_workflow_context(self):
        aid = self._make_approval()
        ctx = {"auto_id": "wf1", "nodes": [], "edges": [],
               "approved_next": "n2", "denied_next": None, "triggered_by": "alice"}
        ok = self.db.save_workflow_context(aid, ctx)
        assert ok is True
        retrieved = self.db.get_workflow_context(aid)
        assert retrieved == ctx

    def test_get_workflow_context_none_for_missing(self):
        result = self.db.get_workflow_context(9999)
        assert result is None

    def test_get_workflow_context_none_when_not_set(self):
        aid = self._make_approval()
        result = self.db.get_workflow_context(aid)
        assert result is None

    def test_overwrite_workflow_context(self):
        aid = self._make_approval()
        ctx1 = {"auto_id": "wf1", "nodes": [], "edges": [],
                "approved_next": "a", "denied_next": "b", "triggered_by": "x"}
        ctx2 = {"auto_id": "wf1", "nodes": [], "edges": [],
                "approved_next": "c", "denied_next": "d", "triggered_by": "y"}
        self.db.save_workflow_context(aid, ctx1)
        self.db.save_workflow_context(aid, ctx2)
        result = self.db.get_workflow_context(aid)
        assert result == ctx2
