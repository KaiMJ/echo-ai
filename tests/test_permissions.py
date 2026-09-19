from echo_ai.runtime.permissions import Permissions, rule_for


async def test_read_only_tools_need_no_approval():
    permissions = Permissions()
    for name in ("list", "read", "search", "delegate"):
        assert await permissions.check(name, {}) == (True, "")


async def test_session_rule_matches_plain_command_prefix_only():
    prompts = []

    async def ask(name, args, label):
        prompts.append((name, args, label))
        return "session", ""

    permissions = Permissions(ask=ask)
    assert await permissions.check("bash", {"command": "pytest tests/unit"}) == (True, "")
    assert prompts[0][2] == "pytest *"
    assert await permissions.check("bash", {"command": "pytest tests/integration"}) == (True, "")
    assert len(prompts) == 1
    assert rule_for("bash", {"command": "pytest tests/unit; rm file"}) == (None, "")
    assert rule_for("bash", {"command": "pytest $(other)"}) == (None, "")
    assert await permissions.check("bash", {"command": "python example.py one"}) == (True, "")
    assert prompts[-1][2] == "python example.py *"


async def test_session_rule_expires_with_permissions_object():
    permissions = Permissions()
    allowed, reason = await permissions.check("edit", {"path": "a.py"})
    assert not allowed and "Permission required" in reason
    assert permissions.blocked
    permissions.rules.add(("edit", "a.py"))
    assert await permissions.check("edit", {"path": "a.py"}) == (True, "")
    assert not (await Permissions().check("edit", {"path": "a.py"}))[0]
