import unittest
from sidebar import AGENT_ROW_KEYS, MAX_AGENT_ROWS, desired_agent_rows, workspace_state


def pane(pid, wid, agent="codex", status="idle", name=None):
    value = {"pane_id": pid, "workspace_id": wid, "tab_id": wid + ":t1"}
    if agent:
        value["agent"] = agent
        value["agent_status"] = status
    if name:
        value["name"] = name
    return value


WORKSPACES = [{"workspace_id": "w1", "label": "[1] task"}, {"workspace_id": "w2", "label": "[2] shell"}]


def rows(panes, inactive=frozenset(), labels=None):
    return desired_agent_rows(panes, WORKSPACES, {}, inactive, labels=labels)


class WorkspaceStateTests(unittest.TestCase):
    def test_a_workspace_is_working_while_any_agent_works(self):
        self.assertEqual(workspace_state(["done", "working", "idle"]), "working")
        self.assertEqual(workspace_state(["done", "done"]), "done")
        self.assertEqual(workspace_state(["idle", "unknown"]), "idle")
        self.assertEqual(workspace_state([]), "unknown")

    def test_a_blocked_agent_outranks_everything(self):
        self.assertEqual(workspace_state(["working", "blocked", "done"]), "blocked")


class AgentRowsTests(unittest.TestCase):
    def test_overall_glyph_and_one_row_per_agent_in_pane_order(self):
        result = rows([pane("w1:p1", "w1", status="done", name="lead"),
                       pane("w1:p2", "w1", status="working", name="build: api"),
                       pane("w1:p3", "w1", status="idle", name="review"),
                       pane("w2:p1", "w2", agent=None)])
        self.assertEqual(result["w1"]["hs_state"], "◐")
        self.assertEqual([result["w1"][key] for key in AGENT_ROW_KEYS],
                         ["● lead", "◐ build: api", "✓ review", None])
        self.assertIsNone(result["w1"]["hs_state_dim"])
        self.assertTrue(all(result["w1"][key + "_dim"] is None for key in AGENT_ROW_KEYS))

    def test_shell_only_workspace_has_the_no_agents_glyph_and_no_rows(self):
        result = rows([pane("w2:p1", "w2", agent=None)])
        self.assertEqual(result["w2"]["hs_state"], "·")
        self.assertTrue(all(result["w2"][key] is None for key in AGENT_ROW_KEYS))
        self.assertEqual(result["w1"]["hs_state"], "·")

    def test_blocked_agent_row_starts_with_the_blocked_glyph(self):
        result = rows([pane("w1:p1", "w1", status="working", name="lead"),
                       pane("w1:p2", "w1", status="blocked", name="build: ui")])
        self.assertEqual(result["w1"]["hs_state"], "◉")
        self.assertEqual(result["w1"]["hs_agent_2"], "◉ build: ui")

    def test_more_agents_than_rows_fold_into_the_last_row(self):
        panes = [pane(f"w1:p{i}", "w1", status="working", name=f"agent {i}") for i in range(1, 7)]
        result = rows(panes)
        self.assertEqual(result["w1"][AGENT_ROW_KEYS[-1]], "… +3 more")
        self.assertEqual(result["w1"]["hs_agent_3"], "◐ agent 3")
        exactly = rows(panes[:MAX_AGENT_ROWS])
        self.assertEqual(exactly["w1"][AGENT_ROW_KEYS[-1]], f"◐ agent {MAX_AGENT_ROWS}")

    def test_inactive_workspace_publishes_the_dim_twins_only(self):
        result = rows([pane("w1:p1", "w1", status="done", name="lead")], inactive={"w1"})
        self.assertIsNone(result["w1"]["hs_state"])
        self.assertEqual(result["w1"]["hs_state_dim"], "●")
        self.assertIsNone(result["w1"]["hs_agent_1"])
        self.assertEqual(result["w1"]["hs_agent_1_dim"], "● lead")

    def test_precomputed_labels_are_used_and_unknown_status_is_normalised(self):
        result = rows([pane("w1:p1", "w1", status="thinking", name="ignored")],
                      labels={"w1:p1": "Fix the sidebar"})
        self.assertEqual(result["w1"]["hs_agent_1"], "○ Fix the sidebar")
        self.assertEqual(result["w1"]["hs_state"], "○")

    def test_every_token_has_a_key_so_clearing_removes_them(self):
        result = rows([pane("w1:p1", "w1", status="working", name="lead")])
        expected = {"hs_state", "hs_state_dim"} | {key for k in AGENT_ROW_KEYS for key in (k, k + "_dim")}
        self.assertEqual(set(result["w1"]), expected)
        self.assertEqual(set(result["w2"]), expected)
