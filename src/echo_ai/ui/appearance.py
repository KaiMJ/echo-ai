"""Monochrome presentation shared by the terminal and its documentation captures."""

from math import cos, pi, sin, sqrt

from pygments.token import Comment, Keyword
from rich.default_styles import DEFAULT_STYLES
from rich.style import Style
from rich.syntax import SyntaxTheme
from rich.theme import Theme

MARKDOWN_THEME = Theme({
    **{name: "none" for name in DEFAULT_STYLES if name.startswith("markdown.")},
    "markdown.h1": "bold",
    "markdown.h2": "bold",
    "markdown.h3": "bold",
    "markdown.h4": "bold",
    "markdown.h5": "bold",
    "markdown.h6": "bold",
    "markdown.strong": "bold",
    "markdown.em": "italic",
    "markdown.code": "bold",
    "markdown.link": "underline",
    "markdown.link_url": "dim underline",
    "markdown.block_quote": "dim",
})


class MonochromeSyntax(SyntaxTheme):
    """Use weight and emphasis while inheriting the active terminal foreground."""

    def get_style_for_token(self, token_type):
        return Style(bold=token_type in Keyword, italic=token_type in Comment)

    def get_background_style(self):
        return Style()


CODE_THEME = MonochromeSyntax()


def orb_frame(moment, *, columns=6, rows=3):
    """Rotate a sparse point sphere, not filled rings, on a Braille grid.

    Only the front hemisphere is drawn. At the default size, about 18 isolated
    dots describe the surface instead of saturating all eight dots in each cell.
    """
    if columns < 1 or rows < 1:
        return ()
    width, height = columns * 2, rows * 4
    cells = [[0] * columns for _ in range(rows)]
    bits = ((0, 3), (1, 4), (2, 5), (6, 7))
    radius = max(0.0, min(width, height) / 2 - 1)
    yaw = moment * 1.3
    for index in range(36):
        y = 1 - 2 * (index + 0.5) / 36
        angle = index * pi * (3 - sqrt(5))
        ring = sqrt(1 - y * y)
        x, z = cos(angle) * ring, sin(angle) * ring
        depth = z * cos(yaw) - x * sin(yaw)
        if depth < 0:
            continue
        px = round((width - 1) / 2 + (x * cos(yaw) + z * sin(yaw)) * radius)
        py = round((height - 1) / 2 + y * radius)
        if 0 <= px < width and 0 <= py < height:
            cells[py // 4][px // 2] |= 1 << bits[py % 4][px % 2]
    return tuple("".join(chr(0x2800 + cell) if cell else " " for cell in row) for row in cells)
