from __future__ import annotations

DEFAULT_LETTER_SPACING = 100
LETTER_SPACING_STEP = 5
MIN_LETTER_SPACING = 80
MAX_LETTER_SPACING = 150


def clamp_letter_spacing(value: int) -> int:
    return max(MIN_LETTER_SPACING, min(MAX_LETTER_SPACING, int(value)))


def step_letter_spacing(current: int, steps: int) -> int:
    return clamp_letter_spacing(int(current) + int(steps) * LETTER_SPACING_STEP)


def parse_letter_spacing(raw: object) -> int:
    """Read a stored percentage. Missing or non-numeric values fall back to 100%."""
    if raw is None or isinstance(raw, bool):
        return DEFAULT_LETTER_SPACING
    try:
        value = round(float(str(raw).strip()))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_LETTER_SPACING
    return clamp_letter_spacing(value)
