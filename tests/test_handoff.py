import asyncio
import sys
from contextlib import ExitStack
from types import SimpleNamespace

import pexpect
import pytest

from echo_ai import cli
from echo_ai.runtime.locking import WorkspaceBusy, workspace_lock


@pytest.mark.parametrize("interactive,answer", [(True, False), (False, True)])
async def test_decline_or_batch_does_not_request_shutdown(
    tmp_path, monkeypatch, interactive, answer
):
    asked = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.Confirm, "ask", lambda *a, **kw: asked.append(kw) or answer)
    with workspace_lock(tmp_path) as owner, ExitStack() as locks:
        with pytest.raises(RuntimeError):
            await cli.acquire_session_lock(
                locks,
                SimpleNamespace(workspace=tmp_path, mode="sandbox"),
                tmp_path,
                interactive=interactive,
                handed_off=asyncio.Event(),
            )
        assert not owner.close_requested()
        assert bool(asked) is interactive
        if asked:
            assert asked[0]["default"] is False


async def test_timeout_keeps_lock_and_removes_request(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.Confirm, "ask", lambda *a, **kw: True)
    with workspace_lock(tmp_path) as owner, ExitStack() as locks:
        with pytest.raises(RuntimeError, match="did not close in time"):
            await cli.acquire_session_lock(
                locks,
                SimpleNamespace(workspace=tmp_path, mode="sandbox"),
                tmp_path,
                interactive=True,
                handed_off=asyncio.Event(),
                timeout=0,
            )
        assert not owner.request_path.exists()
        with pytest.raises(WorkspaceBusy), workspace_lock(tmp_path):
            pass


def test_stale_request_does_not_close_new_owner(tmp_path):
    with workspace_lock(tmp_path) as old:
        old_token = old.owner["token"]
    with workspace_lock(tmp_path) as new:
        new.request_path.write_text(old_token)
        assert not new.close_requested()
        new.request_path.unlink()


async def test_legacy_lock_has_manual_recovery_message(tmp_path, monkeypatch):
    import fcntl

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with (tmp_path.parent / "workspace.lock").open("w") as legacy, ExitStack() as locks:
        fcntl.flock(legacy, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="older or unidentified"):
            await cli.acquire_session_lock(
                locks,
                SimpleNamespace(workspace=tmp_path, mode="sandbox"),
                tmp_path,
                interactive=True,
                handed_off=asyncio.Event(),
            )


async def test_confirmed_handoff_waits_for_owner_cleanup(tmp_path, monkeypatch):
    program = """
import asyncio, sys
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
from echo_ai.cli import acquire_session_lock
async def main():
    root = Path(sys.argv[1])
    handed_off = asyncio.Event()
    with ExitStack() as locks:
        await acquire_session_lock(locks, SimpleNamespace(workspace=root, mode='sandbox'), root,
                                   interactive=False, handed_off=handed_off)
        print('owner-ready', flush=True)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert handed_off.is_set()
            await asyncio.sleep(.05)
            (root / 'cleaned').write_text('saved')
    print('owner-closed', flush=True)
asyncio.run(main())
"""
    owner = pexpect.spawn(
        sys.executable, ["-c", program, str(tmp_path)], encoding="utf8", timeout=5
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.Confirm, "ask", lambda *a, **kw: True)
    try:
        owner.expect("owner-ready")
        with ExitStack() as locks:
            await cli.acquire_session_lock(
                locks,
                SimpleNamespace(workspace=tmp_path, mode="sandbox"),
                tmp_path,
                interactive=True,
                handed_off=asyncio.Event(),
            )
            assert (tmp_path / "cleaned").read_text() == "saved"
            with pytest.raises(WorkspaceBusy), workspace_lock(tmp_path):
                pass
            owner.expect("owner-closed")
            owner.expect(pexpect.EOF)
        owner.close()
        assert owner.exitstatus == 0
        with workspace_lock(tmp_path):
            pass
    finally:
        owner.close(force=True)
