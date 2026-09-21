"""Incremental model traces in the session's SQLite store."""

import asyncio
import json
from contextvars import ContextVar
from dataclasses import asdict

from echo_ai.config.file import load_environment
from echo_ai.runtime.errors import RequestRejected

_active = ContextVar("model_trace", default=None)


def record(kind, value):
    trace = _active.get()
    if trace is not None:
        trace.write(kind, value)


class Trace:
    def __init__(self, store, session_id, run_id, config):
        self.store, self.session_id, self.run_id = store, session_id, run_id
        self.config = {k: v for k, v in asdict(config).items() if k != "base_url"}
        self.metadata = {"session_id": session_id, "run_id": run_id,
                         "provider": config.provider, "model": config.model,
                         "reasoning_effort": config.reasoning_effort}
        self.secret = load_environment(api_key_env=config.api_key_env).get(config.api_key_env)
        self.endpoint = config.base_url
        self.usage = {}

    def __enter__(self):
        self.call_id = self.store.start_model_call(
            self.session_id, self.run_id, self.redact(self.config),
        )
        self.write("start", self.metadata)
        self.token = _active.set(self)
        return self

    def write(self, kind, value):
        if kind == "usage":
            self.usage = value
        self.store.add_model_event(self.call_id, kind, self.redact(value))

    def redact(self, value):
        line = json.dumps(value)
        if self.secret:
            line = line.replace(json.dumps(self.secret)[1:-1], "[redacted]")
        if self.endpoint:
            line = line.replace(json.dumps(self.endpoint)[1:-1], "[endpoint]")
        return json.loads(line)

    def __exit__(self, error_type, error, traceback):
        try:
            status = "cancelled" if isinstance(error, asyncio.CancelledError) else (
                "failed" if error_type else "completed"
            )
            if isinstance(error, RequestRejected):
                status = "rejected"
            self.write("end", {"status": status,
                               "error_type": error_type.__name__ if error_type else None,
                               "error": str(error) if error_type else None})
        finally:
            _active.reset(self.token)
