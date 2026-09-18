import asyncio
from types import SimpleNamespace

from echo_ai.sandbox import Sandbox


async def test_shell_output_streams_before_exit_and_decodes_split_utf8(tmp_path, monkeypatch):
    sandbox = Sandbox(tmp_path)
    output = asyncio.StreamReader()
    seen = []
    exited = False

    class Input:
        def write(self, data):
            pass

        async def drain(self):
            pass

        def close(self):
            pass

    async def wait():
        nonlocal exited
        assert seen == ["first ", "", "€\n"]
        exited = True

    async def spawn(*args, **kwargs):
        return SimpleNamespace(stdin=Input(), stdout=output, wait=wait, returncode=0)

    async def close():
        pass

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(sandbox, "close", close)

    def on_output(text):
        assert not exited or text == ""
        seen.append(text)

    task = asyncio.create_task(sandbox._execute("bash", {"command": "demo"}, on_output=on_output))
    for block in (b"first ", b"\xe2", b"\x82\xac\n"):
        output.feed_data(block)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert not task.done()
    assert seen == ["first ", "", "€\n"]
    output.feed_eof()
    result = await task
    assert result["output"] == "first €\n"
    assert result["exit_code"] == 0
