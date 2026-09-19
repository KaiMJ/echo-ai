"""Validated interface palette; conversation rows deliberately have no background."""

import re
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Theme:
    foreground: str = "default"
    input_foreground: str = "#eeeeee"
    accent: str = "#5fd7df"
    muted: str = "#767676"
    error: str = "#ff5f5f"
    warning: str = "#e5c07b"
    success: str = "#98c379"
    spinner: str = "#c678dd"
    input_background: str = "#262626"
    input_border: str = "#555555"
    selection_background: str = "#767676"
    selection_foreground: str = "#ffffff"

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "foreground" and value == "default":
                continue
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"theme.{field.name} must be a quoted '#RRGGBB' color")

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict):
            raise ValueError("theme must be a YAML mapping")  # noqa: TRY004
        unknown = values.keys() - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown settings in theme: {', '.join(map(str, unknown))}")
        return cls(**values)

    def styles(self):
        composer = f"bg:{self.input_background} {self.input_foreground}"
        return {
            "": self.foreground,
            "heading": "bold",
            "accent": f"{self.accent} bold",
            "muted": self.muted,
            "error": f"{self.error} bold",
            "warning": self.warning,
            "spinner": f"{self.spinner} bold",
            "success": self.success,
            "key": f"{self.accent} bold",
            "selection": f"bg:{self.selection_background} {self.selection_foreground}",
            "block-selection": f"bg:{self.selection_background}",
            "user-border": self.input_border,
            "composer": composer,
            "composer-box": composer,
            "composer-box frame.border": f"{self.input_border} bg:{self.input_background}",
            "frame.border": self.muted,
            "frame.label": "bold",
        }
