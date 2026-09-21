import pytest

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
    assert rule_for("bash", {"command": "/venv/bin/python3.14 example.py one"}) == (
        ("bash", ("/venv/bin/python3.14", "example.py")), "/venv/bin/python3.14 example.py *",
    )


async def test_session_rule_expires_with_permissions_object():
    permissions = Permissions()
    allowed, reason = await permissions.check("edit", {"path": "a.py"})
    assert not allowed and "Permission required" in reason
    assert permissions.blocked
    permissions.rules.add(("edit", "a.py"))
    assert await permissions.check("edit", {"path": "a.py"}) == (True, "")
    assert not (await Permissions().check("edit", {"path": "a.py"}))[0]


@pytest.mark.parametrize("command", [
    "python -c 'print(1)'", "/usr/bin/python3 -c 'print(1)'",
    "python3 -I -c 'print(1)'", "python3", "bash -c 'echo ok'",
    "env python3 example.py", "sudo python3 example.py", "node -e 'console.log(1)'",
])
async def test_interpreters_do_not_create_reusable_approvals(command):
    prompts = []

    async def ask(name, args, label):
        prompts.append(label)
        return "once", ""

    permissions = Permissions(ask=ask)
    assert rule_for("bash", {"command": command}) == (None, "")
    for _ in range(2):
        assert await permissions.check("bash", {"command": command}) == (True, "")
    assert prompts == [None, None]
    assert not permissions.rules
