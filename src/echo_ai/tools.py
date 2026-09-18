"""Small explicit tool schemas shared by validation and the model."""


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
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
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
        "Run bash in the sandbox. Use for tests and repository commands.",
        {"command": STRING, "timeout": {"type": "integer", "minimum": 1, "maximum": 120}},
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
