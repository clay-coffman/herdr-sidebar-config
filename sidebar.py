"""Publish compact task rows from native Herdr facts, only when values change."""
import fcntl
import argparse
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path
from inactivity import update_inactivity
from activity_titles import activity_title
from preferences import load as load_preferences
from ordering import order_groups, apply_view
from runtime import PLUGIN_ID, herdr_binary, icon_mode, logo_for, run_herdr

# The status set herdr-bar, sesh and herdr-nav share, so one glyph means one
# thing in every picker and in the sidebar: blocked ◉, working ◐, done ●,
# idle ✓, unknown ○. A workspace without agents is ·, as a plain tab is in
# herdr-bar. Herdr's own `status_indicators = "symbols"` set (× ◐ ✓ ○) is not
# used because ✓ means done there.
STATES = {"working": "◐", "blocked": "◉", "done": "●", "idle": "✓", "unknown": "○"}
NO_AGENTS = "·"
# A workspace's overall status: someone waiting on the user beats work in
# progress, which beats a finished agent, because one finished worker beside
# three working ones is a workspace that is still working. Herdr's own
# workspace glyph ranks a finished agent above a working one.
STATE_PRECEDENCE = ("blocked", "working", "done", "idle", "unknown")
# Agent rows published under a workspace in the Spaces panel; a fifth agent
# and beyond fold into the last row.
MAX_AGENT_ROWS = 4
AGENT_ROW_KEYS = tuple(f"hs_agent_{index}" for index in range(1, MAX_AGENT_ROWS + 1))
# A braille blank occupies a terminal cell but survives metadata trimming.
BLANK = "\u2800"
# Workspace labels of the form "<WORKSTREAM> · <task>" share a heading in the
# Spaces panel. herdr-automatic-rename prefixes labels with a "[N]" jump key.
WORKSTREAM_SEPARATOR = " · "
JUMP_KEY = re.compile(r"^\[\d+\]\s*")
# A heading over one row costs a line and says nothing its prefix does not.
MIN_STREAM = 2
HISTORY = {
    "codex": (".codex/history.jsonl", "session_id", "text"),
    "claude": (".claude/history.jsonl", "sessionId", "display"),
}
VAGUE = re.compile(
    r"^(yes|okay|ok|go ahead|go on|continue|nice|thank|where we at|are you still|"
    r"how(?:'s| is) it going|also i like)\b",
    re.I,
)


def _task_text(value):
    if not isinstance(value, str):
        return None
    for raw in value.splitlines():
        text = re.sub(r"\s+", " ", raw).strip().lstrip("#>*- ")
        text = re.sub(r"^(?:\[Image #\d+\]\s*)+", "", text, flags=re.I)
        if not text or text.startswith(("AGENTS.md instructions", "<environment_context", "<INSTRUCTIONS", "<skill")):
            continue
        if VAGUE.match(text):
            continue
        text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
        return text[:96].rstrip(" ,.;:-")
    return None


def _reverse_history(path, max_bytes=512 * 1024):
    try:
        with path.open("rb") as stream:
            end = stream.seek(0, os.SEEK_END)
            start = max(0, end - max_bytes)
            stream.seek(start)
            data = stream.read()
    except OSError:
        return
    if start:
        data = data.split(b"\n", 1)[-1]
    for raw in reversed(data.splitlines()):
        yield raw.decode("utf-8", "replace")


def latest_history_task(pane):
    source = HISTORY.get(pane.get("agent"))
    session = pane.get("agent_session") or {}
    session_id = session.get("value") if isinstance(session, dict) else None
    if not source or not session_id:
        return None
    relative_path, session_key, text_key = source
    for line in _reverse_history(Path.home() / relative_path):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict) or record.get(session_key) != session_id:
            continue
        text = _task_text(record.get(text_key))
        if text:
            return text
    return None


# Terminal titles of the form "<brand> <separator> <directory>": Pi sets
# "π - <cwd basename>" and never changes it, so it says where the agent is,
# which the space row already shows, and not what it is doing.
BRANDED_DIRECTORY = re.compile(r"^(?:π|pi|omp|codex|claude)?\s*[-–—>:·|]?\s*(.+?)\s*$", re.I)


def _names_own_directory(text, pane):
    cwd = pane.get("cwd") or pane.get("foreground_cwd") or ""
    if not cwd:
        return False
    base = cwd.rstrip("/").rsplit("/", 1)[-1]
    if not base:
        return False
    match = BRANDED_DIRECTORY.match(text)
    return bool(match) and match.group(1).lower() == base.lower()


def task_label(pane, tabs):
    tokens = pane.get("tokens") or {}
    if tokens.get("hs_title"):
        return tokens["hs_title"]
    native = activity_title(pane)
    if native:
        return native
    if pane.get("agent_status") == "working":
        task = latest_history_task(pane)
        if task:
            return task[:1].upper() + task[1:]
    raw = pane.get("terminal_title_stripped") or ""
    parts = [p.strip().rstrip(".… ") for p in raw.split(" | ")]
    candidates = [p for p in parts if p and not p.startswith(("[", "~/", "/", "<"))
                  and not re.match(r"^[A-Za-z]:[/\\]", p)
                  and not _names_own_directory(p, pane)]
    # Claude's named session is more durable than its transient prompt snippets.
    if candidates and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", candidates[0]):
        return candidates[0].replace("-", " ").capitalize()
    for text in reversed(candidates):
        if not VAGUE.match(text):
            text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
            return text[:1].upper() + text[1:]
    # A herdr agent name is chosen by whoever started the agent and says which
    # one this is; a tab label is usually automatic-rename's program name
    # ("agent"), which every agent tab shares.
    name = pane.get("name") or pane.get("label")
    if name:
        return name
    # automatic-rename prefixes tabs with their jump key; the agent row is not
    # a jump target, so the bracket says nothing here.
    tab = re.sub(r"^\[\d+\]\s*", "", tabs.get(pane.get("tab_id"), ""))
    if tab and tab not in {"main", "shell"} and not re.fullmatch(r"(?:💤\s*)?\d+", tab):
        return tab.replace("-", " ")
    return {"agy": "AGY session", "codex": "Codex session", "claude": "Claude session"}.get(
        pane.get("agent"), f"{pane.get('agent', 'Agent')} session")


def desired_headers(panes, workspaces):
    names = {w["workspace_id"]: w["label"] for w in workspaces}
    seen = set()
    result = {}
    for pane in panes:
        workspace = pane["workspace_id"]
        heading = None
        if pane.get("agent") and workspace not in seen:
            heading = names.get(workspace)
            seen.add(workspace)
        result[pane["pane_id"]] = heading
    return result


def agent_status(pane):
    status = pane.get("agent_status", "unknown")
    return status if status in STATES else "unknown"


def workspace_state(statuses):
    """The overall status of a workspace's agents by STATE_PRECEDENCE."""
    statuses = set(statuses)
    return next((state for state in STATE_PRECEDENCE if state in statuses), "unknown")


def names_only_the_agent(label, agent):
    """True when a task label says no more than which agent it is ("pi")."""
    text = (label or "").strip().lower()
    agent = (agent or "").lower()
    return not text or text in {agent, agent + " session"}


def desired_agent_rows(panes, workspaces, tabs, inactive_ids=frozenset(), labels=None):
    """Per-workspace hs_state, hs_task and hs_agent_N tokens for the Spaces panel.

    hs_state is the workspace's overall glyph by STATE_PRECEDENCE. A workspace
    with exactly one agent folds it into its name row: hs_state is already that
    agent's glyph, so its task is published as hs_task for the end of the name
    row, and is left out when it only names the agent ("pi"). With two or more
    agents, hs_agent_1..hs_agent_MAX_AGENT_ROWS are one "<glyph> <task>" row per
    agent in snapshot (tab, then pane) order, the same labels the agents panel
    shows, and more agents than rows fold into the last row as "… +N more". A
    workspace without agents gets hs_state "·" and neither, so Herdr draws no
    agent rows: a row whose tokens are all absent is dropped. Inactive
    workspaces publish the _dim twins instead, like hs_space/hs_space_dim.
    `labels` maps pane_id to a precomputed task label, so a refresh reads each
    pane's title once.
    """
    agents = {workspace["workspace_id"]: [] for workspace in workspaces}
    for pane in panes:
        if pane.get("agent"):
            agents.setdefault(pane["workspace_id"], []).append(pane)
    result = {}
    for wid, members in agents.items():
        values = {"hs_state": None, "hs_state_dim": None, "hs_task": None, "hs_task_dim": None}
        for key in AGENT_ROW_KEYS:
            values[key] = values[key + "_dim"] = None
        statuses = [agent_status(pane) for pane in members]
        tasks = [labels[pane["pane_id"]] if labels and pane["pane_id"] in labels else task_label(pane, tabs)
                 for pane in members]
        suffix = "_dim" if wid in inactive_ids else ""
        values["hs_state" + suffix] = STATES[workspace_state(statuses)] if members else NO_AGENTS
        if len(members) == 1:
            if not names_only_the_agent(tasks[0], members[0].get("agent")):
                values["hs_task" + suffix] = tasks[0]
            result[wid] = values
            continue
        rows = [STATES[status] + " " + task for status, task in zip(statuses, tasks)]
        if len(rows) > MAX_AGENT_ROWS:
            folded = len(rows) - (MAX_AGENT_ROWS - 1)
            rows = rows[:MAX_AGENT_ROWS - 1] + [f"… +{folded} more"]
        for key, row in zip(AGENT_ROW_KEYS, rows):
            values[key + suffix] = row
        result[wid] = values
    return result


def desired_rows(panes, workspaces, tabs, icons="font", inactive_ids=frozenset(), working_glyph=STATES["working"], branch_length="standard", labels=None):
    headers = desired_headers(panes, workspaces)
    groups = {}
    tab_ids = {}
    for pane in panes:
        tab_ids.setdefault(pane["workspace_id"], set()).add(pane.get("tab_id"))
        if pane.get("agent"):
            groups.setdefault(pane["workspace_id"], {}).setdefault(
                pane.get("tab_id"), []
            ).append(pane["pane_id"])
    previous = None
    result = {}
    for pane in panes:
        heading = headers[pane["pane_id"]]
        values = {"hs_group": heading, "hs_tab": None,
                  "hs_gap": None, "hs_logo": None, "hs_terminals": None}
        values.update({f"hs_{state}": None for state in STATES})
        if pane.get("agent"):
            if heading and previous is not None:
                result[previous]["hs_gap"] = BLANK
            if heading:
                shells = [tabs.get(t, "terminal") for t in tab_ids[pane["workspace_id"]]
                          if t not in groups[pane["workspace_id"]]]
                if shells:
                    values["hs_terminals"] = "terminals: " + ", ".join(sorted(shells))
            tab_id = pane.get("tab_id")
            workspace_tabs = groups[pane["workspace_id"]]
            show_tree = len(tab_ids[pane["workspace_id"]]) > 1
            siblings = workspace_tabs[tab_id]
            first_in_tab = pane["pane_id"] == siblings[0]
            last_in_tab = pane["pane_id"] == siblings[-1]
            if show_tree and first_in_tab:
                tab_label = tabs.get(tab_id) or "tab"
                # Continuation rows start two cells to the right of first rows.
                values["hs_tab"] = ("" if heading else BLANK * 2) + tab_label
            logo = logo_for(pane["agent"], icons)
            if show_tree:
                prefix = "" if first_in_tab else BLANK * 2
                prefix += ("└" if last_in_tab else "├") + (" " if branch_length == "short" else "─ ")
            else:
                prefix = "" if heading else BLANK * 2
            values["hs_logo"] = prefix + logo
            status = agent_status(pane)
            mark = working_glyph if status == "working" else STATES[status]
            label = labels[pane["pane_id"]] if labels and pane["pane_id"] in labels else task_label(pane, tabs)
            values[f"hs_{status}"] = mark + " " + label
            previous = pane["pane_id"]
        # Mutually exclusive tokens let static Herdr styles dim a whole group.
        for key in ["hs_group", "hs_tab", "hs_logo", *[f"hs_{s}" for s in STATES]]:
            values[key + "_dim"] = values[key] if pane["workspace_id"] in inactive_ids else None
            if pane["workspace_id"] in inactive_ids:
                values[key] = None
        result[pane["pane_id"]] = values
    return result


def workstream_of(label, separator=WORKSTREAM_SEPARATOR):
    """The label's first separator-delimited token, minus the jump key, or None."""
    body = JUMP_KEY.sub("", label or "")
    head, found, rest = body.partition(separator)
    head = head.strip()
    return head if found and head and rest.strip() else None


def task_of(label, separator=WORKSTREAM_SEPARATOR):
    """The label with its workstream removed and the jump key kept."""
    match = JUMP_KEY.match(label or "")
    key = match.group(0) if match else ""
    return key + label[len(key):].partition(separator)[2].strip()


def sidebar_order(workspaces):
    """(workspace, indented) pairs in the order Herdr's Spaces panel draws them.

    Herdr groups the workspaces of one repository when two or more are open and
    one of them is the repository root: the group renders at the first member's
    position, root first, then the linked worktrees as indented children in
    native order. Mirrors workspace_entries in herdr's client/shell/sidebar.rs.
    """
    members = {}
    for workspace in workspaces:
        key = (workspace.get("worktree") or {}).get("repo_key")
        if key:
            members.setdefault(key, []).append(workspace)
    grouped = {key for key, group in members.items() if len(group) >= 2
               and any(not member["worktree"].get("is_linked_worktree") for member in group)}
    order, emitted = [], set()
    for workspace in workspaces:
        key = (workspace.get("worktree") or {}).get("repo_key")
        if key not in grouped:
            order.append((workspace, False))
            continue
        if key in emitted:
            continue
        emitted.add(key)
        parent = next((m for m in members[key] if not m["worktree"].get("is_linked_worktree")), workspace)
        order.append((parent, False))
        order.extend((member, True) for member in members[key] if member is not parent)
    return order


def desired_space_rows(workspaces, inactive_ids=frozenset(), headings=True, separator=WORKSTREAM_SEPARATOR):
    """Per-workspace hs_space* tokens: the label, and a workstream heading.

    Consecutive workspaces whose labels share a first token form a workstream.
    The heading is published as a trailing row on the entry *before* the
    stream's first workspace, the same way hs_gap precedes a group heading in
    the agents panel: Herdr draws an entry's rows after the first two cells
    further right, so a heading as a first row would push that one workspace's
    icon and label out of line with its neighbours. Under a heading the label
    drops its workstream prefix and keeps its jump key. When the previous entry
    is the repository root (a top-level row) and the stream is its indented
    children, blank padding moves the heading under the children's tree. A
    run shorter than MIN_STREAM keeps its full labels and gets no heading.
    """
    entries = sidebar_order(workspaces)
    result = {}
    for workspace, _ in entries:
        result[workspace["workspace_id"]] = {"hs_space": None, "hs_space_dim": None,
                                              "hs_stream": None, "hs_stream_dim": None}
    runs, current = [], None
    for index, (workspace, indented) in enumerate(entries):
        stream = workstream_of(workspace["label"], separator) if headings else None
        if stream is not None and current is not None and current[0] == stream:
            current[1].append(index)
        else:
            current = [stream, [index]]
            runs.append(current)
    for stream, indices in runs:
        first = indices[0]
        placed = stream is not None and first > 0 and len(indices) >= MIN_STREAM
        if placed:
            previous, previous_indented = entries[first - 1]
            heading = stream
            if not previous_indented and entries[first][1]:
                heading = BLANK * 5 + heading
            key = "hs_stream_dim" if all(entries[i][0]["workspace_id"] in inactive_ids for i in indices) else "hs_stream"
            result[previous["workspace_id"]][key] = heading
        for index in indices:
            workspace = entries[index][0]
            label = task_of(workspace["label"], separator) if placed else workspace["label"]
            key = "hs_space_dim" if workspace["workspace_id"] in inactive_ids else "hs_space"
            result[workspace["workspace_id"]][key] = label
    return result


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def refresh(clear=False, restore_view=False):
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True)
    with (state / "group-headers.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        herdr = herdr_binary()
        snapshot = run_herdr(herdr, "api", "snapshot")["result"]["snapshot"]
        agents = {a["pane_id"]: a for a in snapshot["agents"]}
        panes = [{**p, **agents.get(p["pane_id"], {})} for p in snapshot["panes"]]
        workspaces = snapshot["workspaces"]
        tabs = {t["tab_id"]: t["label"] for t in snapshot["tabs"]}
        settings_path = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", str(state))) / "config.toml"
        settings = load_preferences(settings_path)
        activity = update_inactivity([w["workspace_id"] for w in workspaces], panes,
                                     read_state(state / "activity.json"), now=time.time(),
                                     timeout=settings.get("inactive_after_seconds", 600))
        from animation import glyph, cache_rows
        ordered_panes, ranks = order_groups(panes, workspaces, settings["order"])
        animated = settings["animated_loaders"] and not clear
        labels = {pane["pane_id"]: task_label(pane, tabs) for pane in panes if pane.get("agent")}
        desired = desired_rows(ordered_panes, workspaces, tabs, icon_mode(), activity.inactive_ids,
                               working_glyph=glyph(time.monotonic(), settings["loader_style"]) if animated else STATES["working"],
                               branch_length=settings["branch_length"], labels=labels)
        for pane in panes:
            desired[pane["pane_id"]]["hs_workspace_rank"] = ranks.get(pane["workspace_id"]) if pane.get("agent") else None
        rows = cache_rows(panes, desired, settings["loader_style"]) if animated else []
        saved = dict(activity.state, next_deadline=None if clear else activity.next_deadline,
                     animation_rows=rows)
        temporary = state / "activity.tmp"
        temporary.write_text(json.dumps(saved))
        temporary.replace(state / "activity.json")
        source = "plugin:" + os.environ.get("HERDR_PLUGIN_ID", PLUGIN_ID)
        for pane in panes:
            wanted = dict.fromkeys(desired[pane["pane_id"]]) if clear else desired[pane["pane_id"]]
            changes = changed_tokens(pane.get("tokens") or {}, wanted)
            if not changes:
                continue
            args = ["pane", "report-metadata", pane["pane_id"], "--source", source]
            for key, value in changes.items():
                args += ["--token", key + "=" + value] if value is not None else ["--clear-token", key]
            run_herdr(herdr, *args)
        space_rows = desired_space_rows(workspaces, activity.inactive_ids,
                                        headings=settings["workstream_headings"])
        agent_rows = desired_agent_rows(panes, workspaces, tabs, activity.inactive_ids, labels=labels)
        for workspace in workspaces:
            wid = workspace["workspace_id"]
            wanted = {**space_rows[wid], **agent_rows.get(wid, {})}
            if clear:
                wanted = dict.fromkeys(wanted)
            changes = changed_tokens(workspace.get("tokens") or {}, wanted)
            if changes:
                args = ["workspace", "report-metadata", wid, "--source", source]
                for key, value in changes.items():
                    args += ["--token", key + "=" + value] if value is not None else ["--clear-token", key]
                run_herdr(herdr, *args)
        mode = "workspace" if clear else settings["order"]
        view_path = state / "view.json"
        if clear or restore_view or read_state(view_path).get("order") != mode:
            apply_view(mode)
            view_path.write_text(json.dumps({"order": mode}))
        pending = not clear and (activity.next_deadline is not None or bool(rows))
        if pending or (state / "deadline.lock").exists():
            from deadline import ensure_timer
            ensure_timer(state, start=pending)


def changed_tokens(existing, desired):
    return {key: value for key, value in desired.items() if existing.get(key) != value}


def main():
    parser = argparse.ArgumentParser(description="Refresh the Herdr workspace/tab/agent sidebar.")
    parser.add_argument("--clear", action="store_true", help="clear this plugin's display tokens")
    parser.add_argument("--settings", action="store_true", help="run the settings popup")
    parser.add_argument("--settings-open", action="store_true", help="open the settings popup")
    parser.add_argument("--restore-view", action="store_true", help="restore saved ordering on startup")
    args = parser.parse_args()
    if not os.environ.get("HERDR_PLUGIN_STATE_DIR"):
        raise RuntimeError("Run through Herdr: herdr plugin action invoke refresh --plugin " + PLUGIN_ID)
    if args.settings or args.settings_open:
        import settings_ui
        settings_ui.open_popup() if args.settings_open else settings_ui.main()
        return
    refresh(args.clear, restore_view=args.restore_view)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Herdr Sidebar: {error}", file=sys.stderr)
        sys.exit(1)
