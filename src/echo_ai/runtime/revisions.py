"""Coordinate file restoration with conversation branch movement."""

import asyncio
from pathlib import Path

from echo_ai.workspace.local import LocalWorkspace
from echo_ai.workspace.revisions import finish_restore, recover_restore, restore_tool_changes


async def move_turn(agent, direction, *, force=False):
    store, key = agent.store, agent.session_id
    await asyncio.to_thread(recover_restore, agent.sandbox, store.active_head(key))
    session = store.session(key)
    if direction == "undo":
        run = store.latest_completed_run(key)
        if run is None or run["start_head"] is None:
            raise ValueError("No completed turn at the current conversation head to undo")
        target = store.parent_head(key, run["start_head"])
        redo = session["active_head"]
    elif direction == "redo":
        target = session["redo_head"]
        run = store.run_ending_at(key, target) if target is not None else None
        if run is None or store.parent_head(key, run["start_head"]) != session["active_head"]:
            raise ValueError("No turn available to redo")
        redo = None
    else:
        raise ValueError(f"Unknown direction: {direction}")
    changes = store.changes_for_run(run["id"])
    paths = await asyncio.to_thread(
        restore_tool_changes, agent.sandbox, changes, reverse=direction == "undo",
        force=force, old_head=session["active_head"], target_head=target, action=direction,
    )
    store.move_head(key, target, redo=redo)
    await asyncio.to_thread(finish_restore, agent.sandbox)
    return paths


async def apply_sandbox(agent, *, force=False):
    if agent.sandbox.mode != "sandbox":
        raise ValueError("Apply is available only for sandbox sessions")
    session = agent.store.session(agent.session_id)
    if not session["repo"]:
        raise ValueError("This session has no recorded source repository")
    checkout = await asyncio.to_thread(
        LocalWorkspace(Path(session["repo"]), agent.sandbox.workspace.parent, agent.sandbox.config)
        .checkout_id
    )
    if session["checkout"] and session["checkout"] != checkout:
        raise ValueError("Source checkout branch or HEAD changed; apply in the original checkout.")
    await asyncio.to_thread(recover_restore, agent.sandbox, session["active_head"])
    changes = agent.store.active_tool_changes(agent.session_id)
    paths = await asyncio.to_thread(
        restore_tool_changes, agent.sandbox, changes, reverse=False, force=force,
        old_head=session["active_head"], target_head=session["active_head"],
        target_root=session["repo"], action="apply",
    )
    await asyncio.to_thread(finish_restore, agent.sandbox)
    return paths
