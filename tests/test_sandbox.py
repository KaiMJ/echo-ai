"""Integration checks use the same Docker image and limits as real sessions."""

import asyncio
import shutil
import subprocess

import pytest

from echo_ai.sandbox import IMAGE, Sandbox


@pytest.fixture
def sandbox(tmp_path):
    if (
        not shutil.which("docker")
        or subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
        ).returncode
    ):
        pytest.skip("Build the sandbox image to run Docker integration tests")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "hello.py").write_text("print('hello')\n")
    (repo / ".gitignore").write_text("secret\n")
    (repo / "secret").write_text("do not copy")
    (repo / "escape").symlink_to("/etc/passwd")
    instance = Sandbox.create(repo, tmp_path / "sessions")
    yield instance
    asyncio.run(instance.close())


def test_tools_and_isolation(sandbox):
    async def run():
        assert not (sandbox.workspace / "secret").exists()
        assert not (sandbox.workspace / "escape").exists()
        assert "hello" in (await sandbox.execute("read", {"path": "hello.py"}))["output"]
        result = await sandbox.execute("edit", {"path": "hello.py", "old": "hello", "new": "world"})
        assert "error" not in result
        assert "world" in (await sandbox.execute("search", {"pattern": "world"}))["output"]
        result = await sandbox.execute("bash", {"command": "python hello.py"})
        assert result["exit_code"] == 0 and result["output"].strip() == "world"
        assert "hello" in (sandbox.workspace.parent.parent.parent / "repo/hello.py").read_text()
        assert (await sandbox.execute("read", {"path": "/etc/passwd"}))["error"]
        await sandbox.execute("bash", {"command": "ln -s /etc/passwd outside"})
        assert (await sandbox.execute("read", {"path": "outside"}))["error"]
        result = await sandbox.execute(
            "bash",
            {
                "command": "test ! -e /var/run/docker.sock && test ! -e /workspace/.git && touch /denied"
            },
        )
        assert result["exit_code"] != 0
        assert (await sandbox.execute("bash", {"command": "exit 17"}))["exit_code"] == 17
        assert "world" in sandbox.diff()
        resumed = Sandbox.resume(sandbox.workspace)
        assert "world" in (await resumed.execute("read", {"path": "hello.py"}))["output"]

    asyncio.run(run())


def test_cancellation_and_timeout(sandbox):
    async def run():
        result = await sandbox.execute("bash", {"command": "sleep 20; touch late", "timeout": 1})
        assert "timed out" in result["error"]
        task = asyncio.create_task(
            sandbox.execute("bash", {"command": "touch started; sleep 20; touch late"})
        )
        for _ in range(100):
            if (sandbox.workspace / "started").exists():
                break
            await asyncio.sleep(0.05)
        assert (sandbox.workspace / "started").exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not (sandbox.workspace / "late").exists()
        assert (await sandbox.execute("bash", {"command": "echo alive"}))[
            "output"
        ].strip() == "alive"

    asyncio.run(run())


def test_output_and_background_processes(sandbox):
    async def run():
        result = await sandbox.execute("bash", {"command": "python -c 'print(\"x\" * 100000)'"})
        assert result["truncated"] and len(result["output"]) < 33_000
        await sandbox.execute("bash", {"command": "(sleep 1; touch background) >/dev/null 2>&1 &"})
        await asyncio.sleep(1.2)
        assert not (sandbox.workspace / "background").exists()
        result = await sandbox.execute("edit", {"path": "hello.py", "old": "missing", "new": "x"})
        assert "exactly once" in result["error"]

    asyncio.run(run())


def test_cancel_during_container_start(sandbox):
    async def run():
        task = asyncio.create_task(sandbox.execute("bash", {"command": "sleep 30"}))
        for _ in range(100):
            if sandbox._container:
                break
            await asyncio.sleep(0.001)
        name = sandbox._container
        assert name
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        code, _ = await sandbox._docker("inspect", name)
        assert code != 0

    asyncio.run(run())


def test_binary_patch_applies_to_original_checkout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    original = b"\x00\x01original\xff"
    changed = b"\x00\x02changed\xfe"
    added = b"\x00new binary\xff"
    (repo / "existing.bin").write_bytes(original)
    sandbox = Sandbox.create(repo, tmp_path / "sessions")
    (sandbox.workspace / "existing.bin").write_bytes(changed)
    (sandbox.workspace / "added.bin").write_bytes(added)
    patch = sandbox.diff()
    assert "GIT binary patch" in patch
    assert (repo / "existing.bin").read_bytes() == original
    subprocess.run(
        ["git", "-C", str(repo), "apply", "--check", "-"], input=patch, text=True, check=True
    )
    subprocess.run(["git", "-C", str(repo), "apply", "-"], input=patch, text=True, check=True)
    assert (repo / "existing.bin").read_bytes() == changed
    assert (repo / "added.bin").read_bytes() == added
