import unittest
from sidebar import (AGENT_ROW_KEYS, MAX_AGENT_ROWS, desired_agent_rows, display_width, fit_name_row,
                     fit_task, names_only_the_agent, workspace_state)


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
        self.assertIsNone(result["w1"]["hs_task"], "several agents keep their own rows")

    def test_a_single_agent_folds_into_the_name_row(self):
        result = rows([pane("w1:p1", "w1", status="working", name="lead")],
                      labels={"w1:p1": "Fix the sidebar"})
        self.assertEqual(result["w1"]["hs_state"], "◐")
        self.assertEqual(result["w1"]["hs_task"], "Fix the sidebar")
        self.assertTrue(all(result["w1"][key] is None for key in AGENT_ROW_KEYS))

    def test_a_single_agent_whose_task_only_names_it_shows_no_task(self):
        for label in ["pi", "Pi", "pi session", ""]:
            result = rows([pane("w1:p1", "w1", agent="pi", status="working")], labels={"w1:p1": label})
            self.assertIsNone(result["w1"]["hs_task"], label)
            self.assertEqual(result["w1"]["hs_state"], "◐")
        result = rows([pane("w1:p1", "w1", agent="codex", status="idle")])
        self.assertIsNone(result["w1"]["hs_task"], "the generic 'Codex session' fallback")

    def test_names_only_the_agent_keeps_real_tasks(self):
        self.assertTrue(names_only_the_agent("Claude session", "claude"))
        self.assertFalse(names_only_the_agent("pi latency experiment", "pi"))
        self.assertFalse(names_only_the_agent("review", "pi"))

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
        self.assertIsNone(result["w1"]["hs_task"])
        self.assertEqual(result["w1"]["hs_task_dim"], "lead")
        several = rows([pane("w1:p1", "w1", status="done", name="lead"),
                        pane("w1:p2", "w1", status="idle", name="review")], inactive={"w1"})
        self.assertIsNone(several["w1"]["hs_agent_1"])
        self.assertEqual(several["w1"]["hs_agent_1_dim"], "● lead")

    def test_precomputed_labels_are_used_and_unknown_status_is_normalised(self):
        result = rows([pane("w1:p1", "w1", status="thinking", name="ignored")],
                      labels={"w1:p1": "Fix the sidebar"})
        self.assertEqual(result["w1"]["hs_task"], "Fix the sidebar")
        self.assertEqual(result["w1"]["hs_state"], "○")

    def test_every_token_has_a_key_so_clearing_removes_them(self):
        result = rows([pane("w1:p1", "w1", status="working", name="lead")])
        expected = {"hs_state", "hs_state_dim", "hs_task", "hs_task_dim"} | {key for k in AGENT_ROW_KEYS for key in (k, k + "_dim")}
        self.assertEqual(set(result["w1"]), expected)
        self.assertEqual(set(result["w2"]), expected)


class FitTaskTests(unittest.TestCase):
    # At 46 columns a top-level name row has 41 cells: "◐ · [1] ~ · " takes 12.
    def test_a_task_that_fits_is_kept_whole(self):
        self.assertEqual(fit_task("pi latency experiment", ["◐", "[1] ~"], False, 46), "pi latency experiment")

    def test_a_long_task_is_cut_to_the_room_left_so_the_name_stays_whole(self):
        task = "Fold a workspace's only agent into its Spaces name row"
        fitted = fit_task(task, ["◐", "[1] ~"], False, 46)
        self.assertEqual(display_width(fitted), 29)
        self.assertTrue(fitted.endswith("…") and task.startswith(fitted[:-1]))
        indented = fit_task(task, ["◐", "[1] ~"], True, 46)
        self.assertEqual(display_width(indented), 24, "a worktree's tree prefix costs five more cells")

    def test_too_little_room_leaves_the_task_out(self):
        name = "[7] LUM-2291 Restricted-access charts review"
        self.assertIsNone(fit_task("Fix it", ["◐", name], False, 46))

    def test_the_cut_does_not_end_on_punctuation_and_counts_wide_characters(self):
        self.assertEqual(fit_task("abcd, efghijklmnop", ["◐", "x" * 27], False, 46), "abcd…")
        self.assertEqual(display_width("💤 漢字"), 7)
        self.assertEqual(display_width(fit_task("漢字漢字漢字漢字漢字", ["◐", "x" * 26], False, 46)), 7)

    def test_the_git_stack_mark_and_dim_twin_are_counted(self):
        values = {"hs_state": None, "hs_state_dim": "◐", "hs_space": None, "hs_space_dim": "[1] ~",
                  "hs_task": None, "hs_task_dim": "x" * 40}
        fit_name_row(values, "▲2", False, 46)
        self.assertIsNone(values["hs_task"])
        self.assertEqual(display_width(values["hs_task_dim"]), 24)
