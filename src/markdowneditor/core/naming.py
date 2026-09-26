from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

_DATED_SUFFIX = re.compile(r"_(\d{8})(?:_(\d+))?$")


def _is_valid_yyyymmdd(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def base_name_without_date(stem: str) -> str:
    match = _DATED_SUFFIX.search(stem)
    if match and _is_valid_yyyymmdd(match.group(1)):
        return stem[: match.start()]
    return stem


def dated_path(current_path: str | Path, today: date | None = None) -> Path:
    path = Path(current_path)
    actual_date = today or date.today()
    base = base_name_without_date(path.stem)
    return path.with_name(f"{base}_{actual_date:%Y%m%d}{path.suffix}")


def numbered_path(path: str | Path, number: int) -> Path:
    target = Path(path)
    if number < 2:
        raise ValueError("순번은 2 이상이어야 합니다.")
    return target.with_name(f"{target.stem}_{number}{target.suffix}")


def first_available_path(path: str | Path, is_taken: Callable[[Path], bool] | None = None) -> Path:
    """Return ``path`` or the first free ``_N`` variant.

    ``is_taken`` lets callers reserve paths that do not exist on disk yet but must not be
    reused, such as a file that is open in another editor tab.
    """

    def unavailable(candidate: Path) -> bool:
        return candidate.exists() or (is_taken is not None and is_taken(candidate))

    target = Path(path)
    if not unavailable(target):
        return target
    number = 2
    while unavailable(numbered_path(target, number)):
        number += 1
    return numbered_path(target, number)
