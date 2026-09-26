from __future__ import annotations

import pytest

from markdowneditor.core.view_settings import (
    DEFAULT_LETTER_SPACING,
    LETTER_SPACING_STEP,
    MAX_LETTER_SPACING,
    MIN_LETTER_SPACING,
    clamp_letter_spacing,
    parse_letter_spacing,
    step_letter_spacing,
)


def test_letter_spacing_defaults_follow_the_prompt() -> None:
    assert DEFAULT_LETTER_SPACING == 100
    assert LETTER_SPACING_STEP == 5
    assert (MIN_LETTER_SPACING, MAX_LETTER_SPACING) == (80, 150)


def test_step_changes_by_five_points_and_stops_at_bounds() -> None:
    assert step_letter_spacing(100, 1) == 105
    assert step_letter_spacing(105, -1) == 100
    assert step_letter_spacing(150, 1) == 150
    assert step_letter_spacing(80, -1) == 80
    assert step_letter_spacing(145, 3) == 150


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 100),
        ("", 100),
        ("abc", 100),
        (True, 100),
        ("115", 115),
        (120, 120),
        ("112.6", 113),
        (" 90 ", 90),
        ("300", 150),
        (-5, 80),
        (float("inf"), 100),
    ],
)
def test_parse_stored_value_recovers_safely(raw: object, expected: int) -> None:
    assert parse_letter_spacing(raw) == expected


def test_clamp() -> None:
    assert clamp_letter_spacing(79) == 80
    assert clamp_letter_spacing(151) == 150
    assert clamp_letter_spacing(100) == 100
