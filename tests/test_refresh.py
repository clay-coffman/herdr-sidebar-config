import os
import tempfile
import unittest
from unittest.mock import patch

import sidebar

SOURCE = "plugin:testy-cool.herdr-sidebar"


def snapshot(workspace_tokens=None):
    tokens = workspace_tokens or {}
    panes = [{"pane_id": f"w1:p{i}", "workspace_id": "w1", "tab_id": "w1:t1",
              "tokens": {"hs_title": f"agent {i}"}} for i in range(1, 7)]
    panes.append({"pane_id": "w2:p1", "workspace_id": "w2", "tab_id": "w2:t1", "tokens": {}})
    statuses = ["done", "working", "blocked", "idle", "working", "unknown"]
    agents = [{"pane_id": f"w1:p{i}", "agent": "codex", "agent_status": status}
              for i, status in enumerate(statuses, start=1)]
    return {"result": {"snapshot": {
        "panes": panes, "agents": agents,
        "tabs": [{"tab_id": "w1:t1", "label": "agent"}, {"tab_id": "w2:t1", "label": "shell"}],
        "workspaces": [{"workspace_id": "w1", "label": "[1] task", "tokens": dict(tokens.get("w1", {}))},
                       {"workspace_id": "w2", "label": "[2] shell", "tokens": {"pr": "#1 ✓", **tokens.get("w2", {})}}],
    }}}


def parse(args):
    """(workspace_id, {token: value or None}) from a `workspace report-metadata` argv."""
    wid, tokens, i = args[2], {}, 3
    while i < len(args):
        if args[i] == "--token":
            key, _, value = args[i + 1].partition("=")
            tokens[key] = value
            i += 2
        elif args[i] == "--clear-token":
            tokens[args[i + 1]] = None
            i += 2
        else:
            i += 1
    return wid, tokens


class RefreshWiringTests(unittest.TestCase):
    def run_refresh(self, snap, clear=False):
        calls = []

        def fake_run_herdr(_binary, *args):
            calls.append(args)
            if args[:2] == ("api", "snapshot"):
                return snap
            return {}

        with tempfile.TemporaryDirectory() as state, \
                patch.dict(os.environ, {"HERDR_PLUGIN_STATE_DIR": state, "HERDR_PLUGIN_CONFIG_DIR": state}), \
                patch("sidebar.run_herdr", fake_run_herdr), patch("sidebar.herdr_binary", return_value="herdr"), \
                patch("sidebar.icon_mode", return_value="text"), patch("sidebar.apply_view"), \
                patch("deadline.ensure_timer"):
            sidebar.refresh(clear=clear)
        return [parse(c) for c in calls if c[:2] == ("workspace", "report-metadata")]

    def test_first_refresh_publishes_state_and_agent_rows_per_workspace(self):
        writes = dict(self.run_refresh(snapshot()))
        self.assertEqual(writes["w1"]["hs_state"], "?")
        self.assertEqual([writes["w1"][f"hs_agent_{i}"] for i in range(1, 5)],
                         ["✓ agent 1", "◔ agent 2", "? agent 3", "… +3 more"])
        self.assertEqual(writes["w1"]["hs_space"], "[1] task")
        self.assertEqual(writes["w2"]["hs_state"], "·")
        self.assertFalse(any(key.startswith("hs_agent") for key in writes["w2"]))
        self.assertNotIn("pr", writes["w2"], "another plugin's token is never written or cleared")
        for tokens in writes.values():
            self.assertFalse(any(value == "" for value in tokens.values()), "no empty-string token is ever sent")

    def test_an_unchanged_second_refresh_writes_nothing(self):
        first = dict(self.run_refresh(snapshot()))
        live = {wid: {k: v for k, v in tokens.items() if v is not None} for wid, tokens in first.items()}
        self.assertEqual(self.run_refresh(snapshot(live)), [])

    def test_clear_removes_only_this_plugins_tokens(self):
        first = dict(self.run_refresh(snapshot()))
        live = {wid: {k: v for k, v in tokens.items() if v is not None} for wid, tokens in first.items()}
        cleared = dict(self.run_refresh(snapshot(live), clear=True))
        self.assertEqual(set(cleared["w1"]), set(live["w1"]))
        self.assertTrue(all(value is None for value in cleared["w1"].values()))
        self.assertNotIn("pr", cleared["w2"])
