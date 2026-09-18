"""File tools executed inside the sandbox container (standard library only)."""

import json
import os
import subprocess
import sys
from pathlib import Path


def _tool(tool: str, args: dict, limits: dict) -> dict:
    root = Path(os.environ.get("ECHO_WORKSPACE_ROOT", "/workspace")).resolve()
    path = (root / args.get("path", ".")).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path must stay inside {root}")
    if tool == "read":
        offset = max(1, int(args.get("offset", 1)))
        limit = min(
            limits["read_max_lines"], max(1, int(args.get("limit", limits["read_default_lines"])))
        )
        with path.open(errors="replace") as file:
            lines = []
            size = 0
            for number, line in enumerate(file, 1):
                if number < offset:
                    continue
                lines.append(f"{number}: {line[: limits['max_output_bytes']]}")
                size += len(lines[-1])
                if len(lines) >= limit or size >= limits["max_output_bytes"] // 2:
                    break
        return {"output": "".join(lines)[: limits["max_output_bytes"] // 2]}
    if tool == "list":
        return {
            "output": "\n".join(
                sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
            )[: limits["max_output_bytes"] // 2]
        }
    if tool == "search":
        with subprocess.Popen(
            [
                "rg",
                "--line-number",
                f"--max-count={limits['search_max_matches']}",
                "--",
                str(args["pattern"]),
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as process:
            output = process.stdout.read(limits["max_output_bytes"] // 2)
            if len(output) == limits["max_output_bytes"] // 2:
                process.terminate()
                suffix = "\n[search output truncated]"
            else:
                suffix = ""
            process.wait(timeout=5)
        return {"output": output.decode(errors="replace") + suffix, "exit_code": process.returncode}
    if tool == "write":
        content = str(args["content"])
        if len(content.encode()) > limits["max_write_bytes"]:
            raise ValueError(f"Writes are limited to {limits['max_write_bytes']:,} bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text() == content:
            return {"output": "No change: file already has this content. Run checks or finish."}
        path.write_text(content)
        return {"output": f"Wrote {path.relative_to(root)}"}
    if tool == "edit":
        content = path.read_text()
        old, new = args["old"], args["new"]
        if not old or content.count(old) != 1:
            raise ValueError("Edit must match exactly once; read the file and provide more context")
        updated = content.replace(old, new, 1)
        if len(updated.encode()) > limits["max_edit_bytes"]:
            raise ValueError(f"Edited files are limited to {limits['max_edit_bytes']:,} bytes")
        path.write_text(updated)
        return {"output": f"Edited {path.relative_to(root)}"}
    raise ValueError(f"Unknown tool: {tool}")


if __name__ == "__main__":
    try:
        print(
            json.dumps(
                _tool(sys.argv[2], json.load(sys.stdin), json.loads(os.environ["ECHO_TOOL_LIMITS"]))
            )
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
