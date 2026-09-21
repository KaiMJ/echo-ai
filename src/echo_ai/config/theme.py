"""Validated interface palette; conversation rows deliberately have no background."""

import re
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Theme:
    foreground: str = "default"
    background: str = "default"
    input_foreground: str = "#eeeeee"
    accent: str = "default"
    muted: str = "#767676"
    error: str = "#d24949"
    warning: str = "#b08900"
    success: str = "#2e8b57"
    spinner: str = "default"
    input_background: str = "#262626"
    input_border: str = "#555555"
    selection_background: str = "#767676"
    selection_foreground: str = "#ffffff"

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if value == "default":
                continue
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"theme.{field.name} must be a quoted '#RRGGBB' color")

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict):
            raise ValueError("theme must be a YAML mapping")  # noqa: TRY004
        values = dict(values)
        preset = values.pop("preset", "terminal")
        presets = {
            "terminal": {},
            "dark": {
                "foreground": "#eeeeee", "background": "#000000", "accent": "#ffffff",
                "muted": "#a3a3a3", "input_background": "#111111", "input_border": "#404040",
                "success": "#3fb950", "error": "#f85149", "warning": "#d29922",
                "spinner": "#ffffff", "selection_background": "#eeeeee",
                "selection_foreground": "#000000",
            },
            "light": {
                "foreground": "#171717", "background": "#ffffff", "accent": "#000000",
                "muted": "#626262", "input_foreground": "#171717", "input_background": "#f5f5f5",
                "input_border": "#b5b5b5", "success": "#1a7f37", "error": "#cf222e",
                "warning": "#9a6700", "spinner": "#000000", "selection_background": "#171717",
                "selection_foreground": "#ffffff",
            },
        }
        if not isinstance(preset, str) or preset not in presets:
            raise ValueError("theme.preset must be terminal, dark, or light")
        unknown = values.keys() - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown settings in theme: {', '.join(map(str, unknown))}")
        return cls(**(presets[preset] | values))

    def styles(self):
        composer = f"bg:{self.input_background} {self.input_foreground}"
        return {
            "": self.foreground + (f" bg:{self.background}" if self.background != "default" else ""),
            "heading": "bold",
            "accent": f"{self.accent} bold",
            "muted": self.muted,
            "error": f"{self.error} bold",
            "warning": self.warning,
            "spinner": f"{self.spinner} bold",
            "success": self.success,
            "key": self.accent,
            "selection": f"bg:{self.selection_background} {self.selection_foreground}",
            "block-selection": f"bg:{self.selection_background}",
            "user-border": self.input_border,
            "composer": composer,
            "composer-box": composer,
            "composer-box frame.border": f"{self.input_border} bg:{self.input_background}",
            "permission": composer,
            "permission frame.border": f"{self.warning} bg:{self.input_background}",
            "permission frame.label": f"{self.warning} bold",
            "permission-target": f"{self.input_foreground} bold",
            "frame.border": self.muted,
            "frame.label": "bold",
            "dialog.body": f"{self.foreground} bg:{self.background}"
            if self.background != "default" else composer,
            "button": composer,
            "button.focused": f"bg:{self.selection_background} {self.selection_foreground} bold",
        }
