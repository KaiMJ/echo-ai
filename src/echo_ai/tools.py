"""Small explicit tool schemas shared by validation and the model."""

from copy import deepcopy

from .config import Config


def function(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


STRING = {"type": "string"}
TOOLS = [
    function("list", "List workspace directory entries.", {"path": STRING}, []),
    function(
        "read",
        "Read text with line numbers. Offset is one-based.",
        {
            "path": STRING,
            "offset": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": Config().read_max_lines},
        },
        ["path"],
    ),
    function(
        "search",
        "Search file contents using ripgrep regex.",
        {"pattern": STRING, "path": STRING},
        ["pattern"],
    ),
    function(
        "write",
        "Create or replace a UTF-8 file.",
        {"path": STRING, "content": STRING},
        ["path", "content"],
    ),
    function(
        "edit",
        "Replace exactly one occurrence of old text; fails if ambiguous.",
        {"path": STRING, "old": STRING, "new": STRING},
        ["path", "old", "new"],
    ),
    function(
        "bash",
        "Run bash in the active workspace. Use for tests and repository commands.",
        {
            "command": STRING,
            "timeout": {"type": "integer", "minimum": 1, "maximum": Config().tool_max_timeout},
        },
        ["command"],
    ),
]
DELEGATE = function(
    "delegate",
    "Ask a child agent to inspect, search, or review the current workspace. "
    "Child cannot edit or execute bash; returns findings. No nested delegation.",
    {"task": STRING},
    ["task"],
)


def tools_for(config: Config):
    tools = deepcopy(TOOLS)
    for tool in tools:
        spec = tool["function"]
        props = spec["parameters"]["properties"]
        if spec["name"] == "read":
            props["limit"]["maximum"] = config.read_max_lines
        elif spec["name"] == "bash":
            props["timeout"]["maximum"] = config.tool_max_timeout
    return tools
