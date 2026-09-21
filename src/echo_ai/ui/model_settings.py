"""Compact, keyboard- and mouse-accessible settings for the current session."""

import sqlite3
from dataclasses import replace

from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, ScrollablePane, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import Button, Dialog, Label, TextArea

from echo_ai.config.file import (
    builtin_profile_names,
    environment_path,
    load_environment,
    read_model_profile,
)
from echo_ai.config.models import reasoning_choices, reasoning_value, select_profile


class Choice:
    def __init__(self, options, value, changed=lambda: None):
        self.options, self.value, self.changed = options, value, changed
        keys = KeyBindings()

        @keys.add("right")
        @keys.add("enter")
        @keys.add(" ")
        def next_choice(event):
            self.move(1)

        @keys.add("left")
        def previous_choice(event):
            self.move(-1)

        self.control = FormattedTextControl(self.text, focusable=True, key_bindings=keys)
        self.window = Window(self.control, height=1, style="class:composer")

    def move(self, delta):
        values = [value for value, _ in self.options]
        self.value = values[(values.index(self.value) + delta) % len(values)]
        self.changed()

    def text(self):
        def previous(event):
            if event.event_type == MouseEventType.MOUSE_UP:
                get_app().layout.focus(self.control)
                self.move(-1)

        def next_(event):
            if event.event_type == MouseEventType.MOUSE_UP:
                get_app().layout.focus(self.control)
                self.move(1)

        label = dict(self.options)[self.value]
        style = "class:selection" if get_app().layout.has_focus(self.control) else ""
        return [("class:accent", " ‹ ", previous), (style, f"{label} ", next_),
                ("class:accent", "› ", next_)]

    def __pt_container__(self):
        return self.window


class ModelSettings:
    def __init__(self, config, save, cancel):
        self.original = self.config = config
        self.on_save, self.on_cancel = save, cancel
        self.error = ""
        self.loaded_profile = "current"
        self.fields = {
            name: TextArea(multiline=False, wrap_lines=False, height=1, style="class:composer")
            for name in ("model", "max_tokens", "context_tokens", "temperature", "top_p", "timeout", "base_url")
        }
        presets = [("current", "Current selection")]
        for name in sorted(builtin_profile_names(), key=lambda name: (name != "xai", name)):
            values, _ = read_model_profile(f"builtin:{name}")
            key = values.get("api_key_env", "ECHO_API_KEY")
            availability = "local server" if values.get("provider") == "hosted_vllm" else (
                "key available" if load_environment(api_key_env=key).get(key) else "key missing"
            )
            presets.append((name, f"{name} · {availability}"))
        self.profile = Choice(presets, "current", self.change_profile)
        self.scope = Choice([(True, "This session + future sessions"),
                             (False, "This session only")], True)
        self.reasoning = Choice(reasoning_choices(config), "")
        self.fill(config)
        self.fields["model"].buffer.on_text_changed += self.model_changed
        keys = KeyBindings()

        @keys.add("escape", eager=True)
        @keys.add("c-c", eager=True)
        def close(event):
            self.on_cancel()

        @keys.add("c-s", eager=True)
        def apply(event):
            self.save()

        rows = [Label("Choose a model. Save applies to your next turn."),
                Label("←/→ choose · Tab next · Ctrl+S save · Esc cancel"),
                Window(height=1)]
        for label, widget in (
            ("Preset", self.profile), ("Model ID", self.fields["model"]),
            ("Reasoning", self.reasoning), ("Output tokens", self.fields["max_tokens"]),
            ("Context tokens", self.fields["context_tokens"]),
            ("Temperature", self.fields["temperature"]), ("Top p", self.fields["top_p"]),
            ("Timeout (sec)", self.fields["timeout"]),
            ("Endpoint", self.fields["base_url"]),
            ("Save for", self.scope),
        ):
            rows.append(VSplit([Label(label, width=16), widget]))
        rows.extend([Window(height=1), Label(self.connection),
                     Label(lambda: ".env detected" if environment_path().is_file() else "No .env detected"),
                     Label(lambda: self.error, style="class:error")])
        self.dialog = Dialog(
            title="Model settings", body=ScrollablePane(
                HSplit(rows), height=Dimension(min=4, preferred=len(rows)),
            ),
            buttons=[Button("Save", handler=self.save), Button("Cancel", handler=cancel)],
            width=76, modal=False,
        )
        # Keep Esc and Ctrl+S active when focus moves to the buttons as well.
        self.container = HSplit([self.dialog], key_bindings=keys, modal=True)

    def fill(self, config):
        self.config = config
        for name, field in self.fields.items():
            field.text = ("" if name == "base_url" and
                          getattr(config, "sources", {}).get(name) == "local inference port"
                          else str(getattr(config, name)))
        self.refresh_reasoning(reasoning_value(config))

    def refresh_reasoning(self, value):
        config = replace(self.config, model=self.fields["model"].text.strip() or self.config.model)
        options = reasoning_choices(config)
        self.reasoning.options = options
        self.reasoning.value = value if value in dict(options) else options[0][0]

    def model_changed(self, _):
        self.refresh_reasoning(self.reasoning.value)

    def change_profile(self):
        try:
            config = self.original if self.profile.value == "current" else select_profile(
                self.original, self.profile.value,
            )
            self.fill(config)
            self.loaded_profile = self.profile.value
            self.error = ""
        except ValueError as error:
            self.profile.value = self.loaded_profile
            self.error = str(error)

    def connection(self):
        environment = load_environment(api_key_env=self.config.api_key_env)
        available = "set" if environment.get(self.config.api_key_env) else "not set"
        if self.config.provider == "hosted_vllm":
            return "Local server must be running. Empty endpoint uses ECHO_INFERENCE_PORT."
        return f"Provider: {self.config.provider} · {self.config.api_key_env}: {available}"

    def save(self):
        try:
            values = {}
            for name, field in self.fields.items():
                convert = str if name in {"model", "base_url"} else (
                    int if name in {"max_tokens", "context_tokens"} else float
                )
                try:
                    values[name] = convert(field.text.strip())
                except ValueError as error:
                    raise ValueError(f"Invalid {name.replace('_', ' ')}.") from error
            effort = self.reasoning.value
            values.update(reasoning_enabled=effort != "off",
                          reasoning_effort="" if effort == "off" else effort)
            from echo_ai.config.resolver import resolve_values

            sources = dict(getattr(self.config, "sources", {}))
            sources["base_url"] = "model picker"
            # Form edits are explicit for this session; environment overrides apply on startup.
            endpoint = {"base_url": values["base_url"], "provider": self.config.provider}
            endpoint, endpoint_sources = resolve_values(endpoint, {}, {
                "ECHO_INFERENCE_PORT": load_environment().get("ECHO_INFERENCE_PORT", "8001"),
            }, {})
            values["base_url"] = endpoint["base_url"]
            sources.update(endpoint_sources)
            config = replace(self.config, **values)
            object.__setattr__(config, "sources", sources)
            self.on_save(config, make_default=self.scope.value)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error = str(error)

    def __pt_container__(self):
        return self.container
