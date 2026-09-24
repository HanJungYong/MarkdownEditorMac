from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from markdowneditor.core.naming import dated_path, first_available_path, numbered_path


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("문서.md", "문서_20260919.md"),
        ("문서_20260918.md", "문서_20260919.md"),
        ("문서_20260918_2.md", "문서_20260919.md"),
        ("문서.v2.MD", "문서.v2_20260919.MD"),
        ("문서_20261345.md", "문서_20261345_20260919.md"),
        ("메모_2026.md", "메모_2026_20260919.md"),
    ],
)
def test_dated_path_examples(source: str, expected: str) -> None:
    assert dated_path(source, date(2026, 9, 19)).name == expected


def test_first_available_path_uses_sequence(tmp_path: Path) -> None:
    target = tmp_path / "문서_20260919.md"
    target.write_text("1", encoding="utf-8")
    numbered_path(target, 2).write_text("2", encoding="utf-8")
    assert first_available_path(target).name == "문서_20260919_3.md"


def test_number_must_start_at_two() -> None:
    with pytest.raises(ValueError):
        numbered_path("x.md", 1)
