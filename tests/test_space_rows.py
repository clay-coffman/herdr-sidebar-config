import unittest
from sidebar import BLANK, desired_space_rows, sidebar_order, task_of, workstream_of


def space(wid, label, repo=None, linked=True):
    workspace = {"workspace_id": wid, "label": label}
    if repo:
        workspace["worktree"] = {"repo_key": repo, "is_linked_worktree": linked}
    return workspace


class WorkstreamLabelTests(unittest.TestCase):
    def test_workstream_is_the_first_token_without_the_jump_key(self):
        self.assertEqual(workstream_of("[4] IAM · LUM-1018 staff session spine"), "IAM")
        self.assertEqual(workstream_of("ORD · LUM-1163 Junction follow-ups"), "ORD")
        self.assertEqual(task_of("[4] IAM · LUM-1018 staff session spine"), "[4] LUM-1018 staff session spine")
        self.assertEqual(task_of("ORD · LUM-1163 Junction follow-ups"), "LUM-1163 Junction follow-ups")

    def test_labels_without_a_stream_have_none(self):
        for label in ("dotfiles/random", "[1] ehr-coordinator", "IAM · ", " · LUM-1", "", None):
            self.assertIsNone(workstream_of(label), label)


class SidebarOrderTests(unittest.TestCase):
    def test_repository_group_renders_root_then_children_at_first_member(self):
        spaces = [space("w1", "root", "r", linked=False), space("w2", "a", "r"),
                  space("w3", "other"), space("w4", "b", "r"), space("w5", "lone", "s")]
        self.assertEqual([(w["workspace_id"], i) for w, i in sidebar_order(spaces)],
                         [("w1", False), ("w2", True), ("w4", True), ("w3", False), ("w5", False)])

    def test_group_needs_a_root_and_two_members(self):
        spaces = [space("w1", "a", "r"), space("w2", "b", "r")]
        self.assertEqual([i for _, i in sidebar_order(spaces)], [False, False])


class SpaceRowsTests(unittest.TestCase):
    def setUp(self):
        self.spaces = [space("w1", "[1] ehr-coordinator", "r", linked=False),
                       space("w2", "[2] IAM · staff sessions", "r"),
                       space("w3", "[3] IAM · patient sessions", "r"),
                       space("w4", "[4] PAT · follow-ups", "r"),
                       space("w6", "[6] PAT · replay", "r"),
                       space("w7", "[7] TEN · practice config", "r"),
                       space("w5", "dotfiles/random")]

    def test_heading_rides_the_previous_entry_and_labels_drop_the_prefix(self):
        rows = desired_space_rows(self.spaces)
        self.assertEqual(rows["w1"]["hs_stream"], BLANK * 5 + "IAM")
        self.assertEqual(rows["w1"]["hs_space"], "[1] ehr-coordinator")
        self.assertEqual(rows["w2"]["hs_space"], "[2] staff sessions")
        self.assertIsNone(rows["w2"]["hs_stream"])
        self.assertEqual(rows["w3"]["hs_space"], "[3] patient sessions")
        self.assertEqual(rows["w3"]["hs_stream"], "PAT")
        self.assertEqual(rows["w4"]["hs_space"], "[4] follow-ups")
        self.assertIsNone(rows["w4"]["hs_stream"])
        self.assertEqual(rows["w6"]["hs_space"], "[6] replay")
        self.assertEqual(rows["w5"]["hs_space"], "dotfiles/random")
        self.assertIsNone(rows["w5"]["hs_stream"])

    def test_a_stream_of_one_keeps_its_prefix_and_gets_no_heading(self):
        rows = desired_space_rows(self.spaces)
        self.assertEqual(rows["w7"]["hs_space"], "[7] TEN · practice config")
        self.assertIsNone(rows["w6"]["hs_stream"])
        self.assertIsNone(rows["w7"]["hs_stream"])

    def test_heading_dims_only_when_the_whole_stream_is_inactive(self):
        rows = desired_space_rows(self.spaces, inactive_ids={"w2", "w3", "w4", "w6"})
        self.assertEqual(rows["w1"]["hs_stream_dim"], BLANK * 5 + "IAM")
        self.assertIsNone(rows["w1"]["hs_stream"])
        self.assertEqual(rows["w2"]["hs_space_dim"], "[2] staff sessions")
        self.assertIsNone(rows["w2"]["hs_space"])
        partly = desired_space_rows(self.spaces, inactive_ids={"w2"})
        self.assertEqual(partly["w1"]["hs_stream"], BLANK * 5 + "IAM")
        self.assertIsNone(partly["w1"]["hs_stream_dim"])

    def test_first_entry_cannot_carry_a_heading_so_it_keeps_its_prefix(self):
        rows = desired_space_rows([space("w1", "IAM · alone"), space("w2", "IAM · second")])
        self.assertEqual(rows["w1"]["hs_space"], "IAM · alone")
        self.assertEqual(rows["w2"]["hs_space"], "IAM · second")
        self.assertIsNone(rows["w1"]["hs_stream"])

    def test_top_level_stream_is_not_padded(self):
        rows = desired_space_rows([space("w1", "shell"), space("w2", "Tools · board"), space("w3", "Tools · usage")])
        self.assertEqual(rows["w1"]["hs_stream"], "Tools")
        self.assertEqual(rows["w2"]["hs_space"], "board")

    def test_headings_off_restores_plain_labels(self):
        rows = desired_space_rows(self.spaces, headings=False)
        self.assertEqual(rows["w2"]["hs_space"], "[2] IAM · staff sessions")
        self.assertTrue(all(r["hs_stream"] is None and r["hs_stream_dim"] is None for r in rows.values()))


if __name__ == "__main__":
    unittest.main()
