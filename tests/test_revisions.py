import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from echo_ai.config import Config
from echo_ai.runtime.agent import Agent
from echo_ai.runtime.revisions import apply_sandbox, move_turn
from echo_ai.runtime.store import Store
from echo_ai.workspace.local import LocalWorkspace
from echo_ai.workspace.revisions import recover_restore, restore_tool_changes
from echo_ai.workspace.sandbox import Sandbox


@pytest.fixture
def session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "file.txt").write_text("first\nsecond\nthird\n")
    sandbox = LocalWorkspace.create(repo, tmp_path / "state")
    store = Store(tmp_path / "sessions.db")
    key = store.create(repo, {}, repo=repo, mode="local", state_path=sandbox.state_path)
    agent = SimpleNamespace(store=store, session_id=key, sandbox=sandbox)
    yield agent
    store.close()


async def test_undo_and_redo_preserve_unrelated_manual_edits(session):
    store, key, sandbox = session.store, session.session_id, session.sandbox
    path = sandbox.workspace / "file.txt"
    store.add(key, {"role": "user", "content": "Change second"})
    run = store.start(key)
    before = sandbox.checkpoint("file.txt")
    path.write_text("first\nmodel\nthird\n")
    after = sandbox.checkpoint("file.txt")
    store.record_tool_change(key, run, "call1", "edit", before, after,
                             sandbox.checkpoint_diff(before, after), sandbox.checkout_id())
    store.add(key, {"role": "assistant", "content": "Changed second."})
    store.finish(run, "completed", {})
    path.write_text("first\nmodel\nthird\nmanual addition\n")

    assert await move_turn(session, "undo") == ["file.txt"]
    assert path.read_text() == "first\nsecond\nthird\nmanual addition\n"
    assert store.messages(key) == []

    assert await move_turn(session, "redo") == ["file.txt"]
    assert path.read_text() == "first\nmodel\nthird\nmanual addition\n"
    assert store.messages(key)[-1]["content"] == "Changed second."


async def test_undo_conflict_does_not_move_conversation(session):
    store, key, sandbox = session.store, session.session_id, session.sandbox
    path = sandbox.workspace / "file.txt"
    store.add(key, {"role": "user", "content": "Change second"})
    run = store.start(key)
    before = sandbox.checkpoint("file.txt")
    path.write_text("first\nmodel\nthird\n")
    after = sandbox.checkpoint("file.txt")
    store.record_tool_change(key, run, "call1", "edit", before, after,
                             sandbox.checkpoint_diff(before, after), sandbox.checkout_id())
    store.add(key, {"role": "assistant", "content": "Done"})
    store.finish(run, "completed", {})
    head = store.active_head(key)
    path.write_text("first\nmanual\nthird\n")

    with pytest.raises(ValueError, match="conflicts"):
        await move_turn(session, "undo")
    assert store.active_head(key) == head
    assert path.read_text() == "first\nmanual\nthird\n"


async def test_agent_records_actual_edit_and_manual_change_stays_out_of_diff(session):
    responses = iter([
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "edit1", "type": "function", "function": {
                "name": "edit",
                "arguments": '{"path":"file.txt","old":"second","new":"model"}',
            },
        }]},
        {"role": "assistant", "content": "Done"},
    ])

    class Model:
        config = Config()

        async def complete(self, messages, tools, emit):
            return next(responses), {"prompt_tokens": 1, "completion_tokens": 1}

    agent = Agent(Model(), session.store, session.sandbox, session.session_id)
    result = await agent.run("Change second")
    assert result["status"] == "completed"
    changes = session.store.tool_changes(session.session_id)
    assert len(changes) == 1
    assert "-second" in changes[0]["patch"] and "+model" in changes[0]["patch"]
    (session.sandbox.workspace / "file.txt").write_text("first\nmodel\nthird\nmanual\n")
    assert "manual" not in changes[0]["patch"]
    with pytest.raises(ValueError, match="/diff all is unavailable"):
        session.sandbox.diff()


async def test_apply_sandbox_merges_independent_host_edit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    await asyncio.to_thread(subprocess.run, ["git", "init", "--quiet", str(repo)], check=True)
    (repo / "file.txt").write_text("first\nsecond\nthird\n")
    sandbox = Sandbox.create(repo, tmp_path / "state")
    store = Store(tmp_path / "sessions.db")
    key = store.create(sandbox.workspace, {}, repo=repo, mode="sandbox")
    agent = SimpleNamespace(store=store, session_id=key, sandbox=sandbox)
    store.add(key, {"role": "user", "content": "Change second"})
    run = store.start(key)
    before = sandbox.checkpoint("file.txt")
    (sandbox.workspace / "file.txt").write_text("first\nmodel\nthird\n")
    after = sandbox.checkpoint("file.txt")
    store.record_tool_change(key, run, "call1", "edit", before, after,
                             sandbox.checkpoint_diff(before, after))
    store.add(key, {"role": "assistant", "content": "Done"})
    store.finish(run, "completed", {})
    (sandbox.workspace / "bash.txt").write_text("from Bash\n")
    (repo / "file.txt").write_text("first\nsecond\nthird\nmanual addition\n")
    assert await apply_sandbox(agent) == ["file.txt"]
    assert (repo / "file.txt").read_text() == "first\nmodel\nthird\nmanual addition\n"
    assert not (repo / "bash.txt").exists()
    store.close()


async def test_apply_sandbox_skips_undone_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.txt").write_text("old\n")
    sandbox = Sandbox.create(repo, tmp_path / "state")
    store = Store(tmp_path / "sessions.db")
    key = store.create(sandbox.workspace, {}, repo=repo, mode="sandbox")
    agent = SimpleNamespace(store=store, session_id=key, sandbox=sandbox)
    store.add(key, {"role": "user", "content": "Edit"})
    run = store.start(key)
    before = sandbox.checkpoint("file.txt")
    (sandbox.workspace / "file.txt").write_text("new\n")
    after = sandbox.checkpoint("file.txt")
    store.record_tool_change(key, run, "call1", "edit", before, after,
                             sandbox.checkpoint_diff(before, after))
    store.add(key, {"role": "assistant", "content": "Done"})
    store.finish(run, "completed", {})
    assert await move_turn(agent, "undo") == ["file.txt"]
    assert store.active_tool_changes(key) == []
    assert await apply_sandbox(agent) == []
    assert (repo / "file.txt").read_text() == "old\n"
    store.close()


def test_sandbox_file_checkpoint_excludes_other_workspace_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "code.py").write_text("old\n")
    (repo / "other.txt").write_text("initial\n")
    sandbox = Sandbox.create(repo, tmp_path / "state")
    (sandbox.workspace / "other.txt").write_text("bash change\n")
    before = sandbox.checkpoint("code.py")
    (sandbox.workspace / "code.py").write_text("new\n")
    after = sandbox.checkpoint("code.py")
    patch = sandbox.checkpoint_diff(before, after)
    assert "code.py" in patch and "other.txt" not in patch
    assert "other.txt" in sandbox.diff()


def test_interrupted_restore_rolls_back_when_head_did_not_move(session):
    sandbox = session.sandbox
    path = sandbox.workspace / "file.txt"
    before = sandbox.checkpoint("file.txt")
    path.write_text("first\nmodel\nthird\n")
    after = sandbox.checkpoint("file.txt")
    change = {"before_ref": before, "after_ref": after, "checkout": sandbox.checkout_id()}
    restore_tool_changes(sandbox, [change], old_head=10, target_head=9)
    assert path.read_text() == "first\nsecond\nthird\n"
    recover_restore(sandbox, 10)
    assert path.read_text() == "first\nmodel\nthird\n"
    assert not (sandbox.state_path / "restore-pending").exists()


async def test_undo_refuses_changed_checkout(session):
    store, key, sandbox = session.store, session.session_id, session.sandbox
    path = sandbox.workspace / "file.txt"
    store.add(key, {"role": "user", "content": "Edit"})
    run = store.start(key)
    before = sandbox.checkpoint("file.txt")
    path.write_text("first\nmodel\nthird\n")
    after = sandbox.checkpoint("file.txt")
    store.record_tool_change(key, run, "call1", "edit", before, after,
                             sandbox.checkpoint_diff(before, after), sandbox.checkout_id())
    store.add(key, {"role": "assistant", "content": "Done"})
    store.finish(run, "completed", {})
    head = store.active_head(key)
    await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(sandbox.workspace), "checkout", "-b", "other"], check=True,
    )
    with pytest.raises(ValueError, match="branch or HEAD changed"):
        await move_turn(session, "undo")
    assert store.active_head(key) == head
    assert path.read_text() == "first\nmodel\nthird\n"
