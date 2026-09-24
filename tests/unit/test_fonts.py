from markdowneditor.gui.fonts import FONT_FAMILY, FONT_FILES, font_face_css, font_paths


def test_pretendard_font_assets_and_css_are_available() -> None:
    paths = font_paths()
    assert tuple(path.name for path in paths) == FONT_FILES
    assert all(path.is_file() and path.stat().st_size > 1_000_000 for path in paths)

    css = font_face_css()
    assert css.count("@font-face") == 3
    assert FONT_FAMILY in css
    assert all(path.as_uri() in css for path in paths)
