"""Process-local tool approvals. Nothing here is stored with a session."""

import shlex


def rule_for(name, args):
    if name in {"write", "edit"}:
        path = args["path"]
        return (name, path), f"{name} {path}"
    if name != "bash":
        return None, ""
    command = args["command"]
    # Shell syntax can change what a prefix runs. Offer a reusable rule only
    # for a plain command; complex commands can still be allowed once.
    if any(char in command for char in ";|&`$><\n\r\\"):
        return None, ""
    try:
        words = shlex.split(command)
    except ValueError:
        return None, ""
    if not words:
        return None, ""
    prefix = tuple(words[:2] if words[0] in {"python", "python3"} and len(words) > 1 else words[:1])
    return (name, prefix), " ".join(prefix) + " *"


class Permissions:
    def __init__(self, *, yolo=False, ask=None):
        self.yolo = yolo
        self.ask = ask
        self.rules = set()
        self.blocked = False

    async def check(self, name, args):
        if self.yolo or name not in {"bash", "write", "edit"}:
            return True, ""
        rule, label = rule_for(name, args)
        if rule in self.rules and rule is not None:
            return True, ""
        if self.ask is None:
            self.blocked = True
            return False, "Permission required. Run interactively or use --yolo."
        decision, message = await self.ask(name, args, label if rule else None)
        if decision == "session" and rule is not None:
            self.rules.add(rule)
            return True, ""
        if decision == "once":
            return True, ""
        return False, message or "User denied this tool call."
