"""File tools executed inside the sandbox container (standard library only)."""

import json
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 32_768


def _tool(tool: str, args: dict) -> dict:
    root = Path("/workspace")
    path = (root / args.get("path", ".")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path must stay inside /workspace")
    if tool == "read":
        offset = max(1, int(args.get("offset", 1)))
        limit = min(500, max(1, int(args.get("limit", 200))))
        with path.open(errors="replace") as file:
            lines = []
            size = 0
            for number, line in enumerate(file, 1):
                if number < offset:
                    continue
                lines.append(f"{number}: {line[:MAX_OUTPUT]}")
                size += len(lines[-1])
                if len(lines) >= limit or size >= MAX_OUTPUT // 2:
                    break
        return {"output": "".join(lines)[: MAX_OUTPUT // 2]}
    if tool == "list":
        return {
            "output": "\n".join(
                sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
            )[: MAX_OUTPUT // 2]
        }
    if tool == "search":
        with subprocess.Popen(
            ["rg", "--line-number", "--max-count=50", "--", str(args["pattern"]), str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ) as process:
            output = process.stdout.read(MAX_OUTPUT // 2)
            if len(output) == MAX_OUTPUT // 2:
                process.terminate()
                suffix = "\n[search output truncated]"
            else:
                suffix = ""
            process.wait(timeout=5)
        return {"output": output.decode(errors="replace") + suffix, "exit_code": process.returncode}
    if tool == "write":
        content = str(args["content"])
        if len(content.encode()) > 1024 * 1024:
            raise ValueError("Writes are limited to 1 MiB")
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
        path.write_text(content.replace(old, new, 1))
        return {"output": f"Edited {path.relative_to(root)}"}
    raise ValueError(f"Unknown tool: {tool}")


if __name__ == "__main__":
    try:
        print(json.dumps(_tool(sys.argv[2], json.load(sys.stdin))))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"error": str(exc)}))
