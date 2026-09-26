from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from markdowneditor.core.file_io import SUPPORTED_EXTENSIONS

SHORTCUT_EXTENSIONS = {".lnk", ".url"}


def document_key(path: str | Path) -> str:
    """Absolute, symlink-resolved key using the host OS's path normalization.

    On macOS, same_document() also checks file identity for case-insensitive volumes.
    Do not case-fold POSIX paths: APFS can also be formatted case-sensitive.
    """
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def same_document(first: str | Path, second: str | Path) -> bool:
    if document_key(first) == document_key(second):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def is_markdown_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class DropEntry:
    """One dragged item. ``local_path`` is None for remote URLs and virtual files."""

    display: str
    local_path: str | None = None


@dataclass
class DropPlan:
    paths: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    has_local_files: bool = False

    @property
    def can_open(self) -> bool:
        return bool(self.paths)


def classify_drop(entries: Iterable[DropEntry]) -> DropPlan:
    """Keep openable local Markdown files in drop order and explain every skipped item."""
    plan = DropPlan()
    seen: set[str] = set()
    for entry in entries:
        if not entry.local_path:
            plan.skipped.append((entry.display, "로컬 파일이 아님"))
            continue
        plan.has_local_files = True
        path = Path(entry.local_path)
        name = path.name or entry.display
        if not path.exists():
            plan.skipped.append((name, "파일이 없음"))
        elif path.is_dir():
            plan.skipped.append((name, "폴더"))
        elif path.suffix.lower() in SHORTCUT_EXTENSIONS:
            plan.skipped.append((name, "바로 가기 파일"))
        elif not is_markdown_path(path):
            plan.skipped.append((name, "마크다운 파일이 아님"))
        else:
            key = document_key(path)
            if key not in seen:
                seen.add(key)
                plan.paths.append(path)
    return plan


@dataclass
class OpenSummary:
    opened: list[Path] = field(default_factory=list)
    already_open: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def any_document(self) -> bool:
        return bool(self.opened or self.already_open)

    def status_text(self) -> str:
        parts = []
        for label, count in (
            ("열림", len(self.opened)),
            ("이미 열림", len(self.already_open)),
            ("건너뜀", len(self.skipped)),
            ("실패", len(self.failed)),
        ):
            if count:
                parts.append(f"{label} {count}")
        return " · ".join(parts)

    def problem_lines(self) -> list[str]:
        return [f"{name}: {reason}" for name, reason in (*self.failed, *self.skipped)]
