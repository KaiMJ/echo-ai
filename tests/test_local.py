import asyncio
import subprocess
from dataclasses import replace

import pytest

from echo_ai.cli import session_lock
from echo_ai.workspace.local import LocalWorkspace


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


@pytest.fixture
def local(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")
    (repo / "file.txt").write_text("initial\n")
    (repo / ".gitignore").write_text("ignored/\n")
    git(repo, "add", "file.txt")
    (repo / "file.txt").write_text("user edit\n")
    instance = LocalWorkspace.create(repo, tmp_path / "sessions")
    yield instance
    asyncio.run(instance.close())


async def test_local_tools_diff_and_resume_preserve_user_index(local):
    index = (local.workspace / ".git/index").read_bytes()
    head = git(local.workspace, "symbolic-ref", "HEAD")
    assert local.diff() == ""
    result = await local.execute(
        "edit", {"path": "file.txt", "old": "user edit", "new": "agent edit"}
    )
    assert "error" not in result
    assert (local.workspace / "file.txt").read_text() == "agent edit\n"
    await local.execute("write", {"path": "added.txt", "content": "new\n"})
    result = await local.execute("bash", {"command": "pwd"})
    assert result["output"].strip() == str(local.workspace)
    patch = local.diff()
    assert "-user edit" in patch and "+agent edit" in patch and "+new" in patch
    assert (local.workspace / ".git/index").read_bytes() == index
    assert git(local.workspace, "symbolic-ref", "HEAD") == head
    resumed = LocalWorkspace.resume(local.workspace, local.state_path)
    assert resumed.mode == "local" and resumed.diff() == patch
    assert "agent edit" in (await resumed.execute("read", {"path": "file.txt"}))["output"]
    assert "error" in await local.execute("read", {"path": "../outside"})
    await resumed.close()


async def test_local_timeout_cancel_output_and_background_cleanup(local):
    local.config = replace(local.config, max_output_bytes=100)
    result = await local.execute("bash", {"command": "printf '%1000s' x"})
    assert result["truncated"] and len(result["output"]) < 130
    result = await local.execute("bash", {"command": "sleep 10; touch late", "timeout": 1})
    assert "timed out" in result["error"]
    task = asyncio.create_task(
        local.execute("bash", {"command": "touch started; sleep 10; touch late"})
    )
    for _ in range(100):
        if (local.workspace / "started").exists():
            break
        await asyncio.sleep(0.01)
    assert (local.workspace / "started").exists()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (local.workspace / "late").exists()
    await local.execute("bash", {"command": "(sleep .2; touch background) >/dev/null 2>&1 &"})
    await asyncio.sleep(0.3)
    assert not (local.workspace / "background").exists()
    assert (await local.execute("bash", {"command": "echo alive"}))["exit_code"] == 0


def test_local_sessions_for_same_checkout_share_lock(local, tmp_path):
    root = tmp_path / "sessions"
    second = LocalWorkspace.create(local.workspace, root)
    with (
        session_lock(local, root),
        pytest.raises(RuntimeError, match="another Echo"),
        session_lock(second, root),
    ):
        pass
    with session_lock(second, root):
        pass
