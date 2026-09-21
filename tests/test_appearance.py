import pytest
from prompt_toolkit.styles import Style

from echo_ai.config.theme import Theme
from echo_ai.ui.appearance import orb_frame


@pytest.mark.parametrize("preset", ["terminal", "dark", "light"])
def test_theme_presets_and_overrides(preset):
    theme = Theme.from_mapping({"preset": preset, "accent": "#123456"})
    styles = Style.from_dict(theme.styles())
    assert styles.get_attrs_for_style_str("class:accent").color == "123456"
    if preset != "terminal":
        assert theme.foreground != theme.background
        assert theme.input_foreground != theme.input_background


@pytest.mark.parametrize("preset", ["unknown", [], None])
def test_invalid_preset_is_a_configuration_error(preset):
    with pytest.raises(ValueError, match="theme.preset"):
        Theme.from_mapping({"preset": preset})


@pytest.mark.parametrize("columns,rows", [(1, 1), (6, 3), (12, 5)])
def test_orb_has_stable_dimensions_and_only_braille(columns, rows):
    for moment in [0, 0.3, 10]:
        frame = orb_frame(moment, columns=columns, rows=rows)
        assert len(frame) == rows
        assert all(len(line) == columns for line in frame)
        assert all(c == " " or 0x2800 <= ord(c) <= 0x28FF for line in frame for c in line)
    assert orb_frame(0.3, columns=columns, rows=rows) == orb_frame(0.3, columns=columns, rows=rows)


def test_orb_changes_with_time_and_handles_empty_sizes():
    assert orb_frame(0) != orb_frame(1)
    assert orb_frame(0, columns=0) == ()
    # The sphere is deliberately sparse, including while rotating.
    for moment in [0, 0.25, 0.5, 1]:
        dots = sum((ord(c) - 0x2800).bit_count() for line in orb_frame(moment) for c in line if c != " ")
        assert 8 <= dots <= 22


def test_markdown_and_syntax_do_not_reintroduce_color():
    from echo_ai.ui.terminal import Entry

    entry = Entry("text", "Echo", "## Heading\n\nA **bold** word and `code`.\n\n```python\ndef f():\n    return 42\n```")
    fragments = [part for line in entry.markdown_lines(80) for part in line]
    assert all("fg:" not in part[0] and "bg:" not in part[0] and "ansi" not in part[0] for part in fragments)
