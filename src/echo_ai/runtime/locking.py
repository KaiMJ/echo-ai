"""Workspace ownership and cooperative handoff between Echo processes."""

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


def read_owner(path):
    try:
        value = json.loads(path.read_text())
        if (
            isinstance(value, dict)
            and value.get("protocol") == 1
            and type(value.get("pid")) is int
            and value["pid"] > 0
            and isinstance(value.get("token"), str)
            and len(value["token"]) == 32
        ):
            return value
    except (OSError, ValueError):
        pass
    return None


@dataclass
class WorkspaceLease:
    path: Path
    owner: dict

    @property
    def request_path(self):
        return self.path.with_name(self.path.name + ".close-request")

    def close_requested(self):
        try:
            return self.request_path.read_text() == self.owner["token"]
        except OSError:
            return False

    def remove_request(self):
        if self.close_requested():
            self.request_path.unlink(missing_ok=True)


class WorkspaceBusy(RuntimeError):
    def __init__(self, path):
        super().__init__("This workspace is open in another Echo process. Close it first.")
        self.path = path
        self.owner = read_owner(path)

    def request_close(self):
        if not self.owner or read_owner(self.path) != self.owner:
            raise RuntimeError("Workspace owner changed. Try resuming again.")
        lease = WorkspaceLease(self.path, self.owner)
        lease.request_path.write_text(self.owner["token"])
        return lease


@contextmanager
def workspace_lock(workspace, lock_path=None):
    """Never unlink the flock file: every process must lock the same inode."""
    path = lock_path or workspace.parent / "workspace.lock"
    with path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkspaceBusy(path) from error
        lease = WorkspaceLease(path, {"protocol": 1, "pid": os.getpid(), "token": uuid.uuid4().hex})
        try:
            lock.seek(0)
            lock.truncate()
            json.dump(lease.owner, lock)
            lock.flush()
            yield lease
        finally:
            lease.remove_request()
            fcntl.flock(lock, fcntl.LOCK_UN)
