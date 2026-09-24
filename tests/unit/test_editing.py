from __future__ import annotations

import pytest

from markdowneditor.core.editing import newline_prefix


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("일반 문장", ""),
        ("  일반 문장", "  "),
        ("\t일반 문장", "  "),
        ("> 인용", "> "),
        ("  > 인용", "  > "),
        ("- 목록", "- "),
        ("+ 목록", "+ "),
        ("* [x] 완료", "* [ ] "),
        ("> - 인용 목록", "> - "),
        ("9. 번호", "10. "),
        ("3) 번호", "4) "),
    ],
)
def test_newline_prefix_with_auto_indent(line: str, expected: str) -> None:
    assert newline_prefix(line, auto_indent=True) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  일반 문장", ""),
        ("  > 인용", "> "),
        ("    - 목록", "- "),
        ("  7. 번호", "8. "),
    ],
)
def test_newline_prefix_without_auto_indent(line: str, expected: str) -> None:
    assert newline_prefix(line, auto_indent=False) == expected
