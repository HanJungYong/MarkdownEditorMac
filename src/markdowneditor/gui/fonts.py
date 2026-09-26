from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

from markdowneditor.core.view_settings import DEFAULT_LETTER_SPACING

FONT_FAMILY = "Pretendard"
FONT_FILES = (
    "Pretendard-Regular.otf",
    "Pretendard-Medium.otf",
    "Pretendard-Bold.otf",
)
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 24

_registered = False


def font_paths() -> tuple[Path, ...]:
    packaged = files("markdowneditor").joinpath("assets", "fonts")
    source = Path(__file__).resolve().parents[3] / "Font"
    paths: list[Path] = []
    for name in FONT_FILES:
        packaged_font = packaged.joinpath(name)
        if packaged_font.is_file():
            paths.append(Path(str(packaged_font)))
        else:
            paths.append(source / name)
    return tuple(paths)


def register_pretendard_fonts() -> bool:
    global _registered
    if _registered:
        return True
    paths = font_paths()
    if not all(path.is_file() for path in paths):
        return False
    loaded = [QFontDatabase.addApplicationFont(str(path)) >= 0 for path in paths]
    _registered = all(loaded)
    return _registered


def editor_font(size: int, letter_spacing: int = DEFAULT_LETTER_SPACING) -> QFont:
    """The only place that builds the Markdown editor font (size + percentage spacing)."""
    font = QFont(FONT_FAMILY, int(size))
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, float(letter_spacing))
    return font


def font_face_css() -> str:
    regular, medium, bold = font_paths()
    return "\n".join(
        (
            "@font-face { font-family: 'Pretendard'; "
            f"src: url('{regular.as_uri()}') format('opentype'); font-weight: 400; }}",
            "@font-face { font-family: 'Pretendard'; "
            f"src: url('{medium.as_uri()}') format('opentype'); font-weight: 500; }}",
            "@font-face { font-family: 'Pretendard'; "
            f"src: url('{bold.as_uri()}') format('opentype'); font-weight: 700; }}",
        )
    )
