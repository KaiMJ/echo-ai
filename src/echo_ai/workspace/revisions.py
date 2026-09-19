"""Restore recorded tool changes against the current workspace."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from echo_ai.workspace.sandbox import _git_env


def _git_bytes(workspace, *args):
    return subprocess.check_output(
        ["git", f"--git-dir={workspace.parent / 'baseline.git'}",
         f"--work-tree={workspace}", *args],
        env=_git_env(), stderr=subprocess.PIPE,
    )


def _blob(workspace, revision, name):
    result = subprocess.run(
        ["git", f"--git-dir={workspace.parent / 'baseline.git'}",
         f"--work-tree={workspace}", "show", f"{revision}:{name}"],
        env=_git_env(), capture_output=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _tree_mode(workspace, revision, name):
    listing = _git_bytes(workspace, "ls-tree", "-z", revision, "--", name)
    if not listing:
        return None
    mode = int(listing.split(b" ", 1)[0], 8)
    return mode & 0o777 if mode in {0o100644, 0o100755} else mode


def _file_mode(path):
    return stat.S_IMODE(path.stat().st_mode) if path.is_file() else None


def _merge(current, base, desired):
    with tempfile.TemporaryDirectory() as directory:
        paths = [Path(directory) / name for name in ("current", "base", "desired")]
        for path, content in zip(paths, (current, base, desired)):
            path.write_bytes(content)
        result = subprocess.run(
            ["git", "merge-file", "--stdout", *(str(path) for path in paths)],
            env=_git_env(), capture_output=True, check=False,
        )
    return result.stdout if result.returncode == 0 else None


def _safe_path(root, name):
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe checkpoint path: {name}")
    return path


def _install(path, content, mode=None):
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, mode if mode is not None else 0o644)
        os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_durable(path, content):
    with path.open("wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _journal_dir(sandbox):
    return (sandbox.state_path if sandbox.mode == "local" else sandbox.workspace.parent) / "restore-pending"


def recover_restore(sandbox, active_head):
    directory = _journal_dir(sandbox)
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        if directory.exists():
            shutil.rmtree(directory)
        return
    manifest = json.loads(manifest_path.read_text())
    root = Path(manifest["target_root"])
    if active_head == manifest["old_head"]:
        version = "original"
    elif active_head == manifest["target_head"]:
        version = "desired"
    else:
        raise ValueError("Interrupted restore has an unexpected conversation head")
    for item in manifest["files"]:
        path = _safe_path(root, item["name"])
        current = path.read_bytes() if path.is_file() else None
        current_mode = _file_mode(path)
        known = [
            (directory / f"{item['index']}.{kind}").read_bytes()
            if item[f"{kind}_exists"] else None
            for kind in ("original", "desired")
        ]
        known_modes = [item[f"{kind}_mode"] for kind in ("original", "desired")]
        if (current, current_mode) not in zip(known, known_modes):
            raise ValueError(
                f"Interrupted restore conflicts with a later edit to {item['name']}"
            )
    for item in manifest["files"]:
        content = ((directory / f"{item['index']}.{version}").read_bytes()
                   if item[f"{version}_exists"] else None)
        _install(_safe_path(root, item["name"]), content, item[f"{version}_mode"])
    shutil.rmtree(directory)


def finish_restore(sandbox):
    directory = _journal_dir(sandbox)
    if directory.exists():
        shutil.rmtree(directory)


def restore_tool_changes(
    sandbox, changes, *, reverse=True, force=False, old_head=None, target_head=None,
    target_root=None, action="undo",
):
    """Plan all files first, then apply inverse/forward tool changes."""
    workspace = sandbox.workspace if sandbox.mode == "sandbox" else sandbox.state_path / "workspace"
    root = Path(target_root).resolve() if target_root else sandbox.workspace
    current_checkout = getattr(sandbox, "checkout_id", lambda: None)()
    planned = {}
    planned_modes = {}
    conflicts = set()
    for change in reversed(changes) if reverse else changes:
        if change["checkout"] and change["checkout"] != current_checkout:
            raise ValueError("Checkout branch or HEAD changed; return to the recorded checkout.")
        source = change["after_ref"] if reverse else change["before_ref"]
        target = change["before_ref"] if reverse else change["after_ref"]
        names = _git_bytes(workspace, "diff", "--name-only", "-z", source, target)
        for raw in filter(None, names.split(b"\0")):
            name = os.fsdecode(raw)
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid checkpoint path")
            path = _safe_path(root, name)
            actual = planned[name] if name in planned else (path.read_bytes() if path.is_file() else None)
            base, desired = _blob(workspace, source, name), _blob(workspace, target, name)
            base_mode, desired_mode = (
                _tree_mode(workspace, source, name), _tree_mode(workspace, target, name)
            )
            if any(mode not in {None, 0o644, 0o755} for mode in (base_mode, desired_mode)):
                conflicts.add(name)
                continue
            actual_mode = planned_modes.get(name, _file_mode(path))
            if actual_mode != base_mode and base_mode != desired_mode and not force:
                conflicts.add(name)
                continue
            final_mode = desired_mode
            if base_mode == desired_mode and actual_mode is not None:
                final_mode = actual_mode
            if actual == base:
                planned[name] = desired
                planned_modes[name] = final_mode
            elif actual == desired:
                planned[name] = actual
                planned_modes[name] = actual_mode
            elif force:
                planned[name] = desired
                planned_modes[name] = final_mode
            elif all(value is not None and b"\0" not in value for value in (actual, base, desired)):
                merged = _merge(actual, base, desired)
                if merged is None:
                    conflicts.add(name)
                else:
                    planned[name] = merged
                    planned_modes[name] = final_mode
            else:
                conflicts.add(name)
    if conflicts:
        raise ValueError(
            f"{action.capitalize()} conflicts in: " + ", ".join(sorted(conflicts))
            + f". Files were not changed. Run /{action} force to replace those files."
        )
    originals = {name: (_safe_path(root, name).read_bytes()
                        if _safe_path(root, name).is_file() else None)
                 for name in planned}
    original_modes = {name: _file_mode(_safe_path(root, name)) for name in planned}
    directory = _journal_dir(sandbox)
    if directory.exists():
        raise ValueError("An interrupted restore must be recovered before another restore")
    directory.mkdir()
    manifest = {"old_head": old_head, "target_head": target_head,
                "target_root": str(root), "files": []}
    for index, (name, content) in enumerate(planned.items()):
        original = originals[name]
        item = {"index": index, "name": name, "original_exists": original is not None,
                "desired_exists": content is not None,
                "original_mode": original_modes[name], "desired_mode": planned_modes[name]}
        manifest["files"].append(item)
        if original is not None:
            _write_durable(directory / f"{index}.original", original)
        if content is not None:
            _write_durable(directory / f"{index}.desired", content)
    _write_durable(directory / "manifest.json", json.dumps(manifest).encode())
    _fsync_directory(directory)
    try:
        for name, content in planned.items():
            path = _safe_path(root, name)
            if ((path.read_bytes() if path.is_file() else None) != originals[name]
                    or _file_mode(path) != original_modes[name]):
                raise ValueError(f"File changed during restore: {name}")
            _install(path, content, planned_modes[name])
    except Exception:
        for name, content in originals.items():
            _install(_safe_path(root, name), content, original_modes[name])
        finish_restore(sandbox)
        raise
    return list(planned)
