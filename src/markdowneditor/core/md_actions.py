from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditResult:
    start: int
    end: int
    replacement: str
    selection_start: int
    selection_end: int


def wrap_inline(
    text: str,
    start: int,
    end: int,
    prefix: str,
    suffix: str | None = None,
    placeholder: str = "텍스트",
) -> EditResult:
    suffix = prefix if suffix is None else suffix
    selected = text[start:end]
    if (
        start >= len(prefix)
        and text[start - len(prefix) : start] == prefix
        and text[end : end + len(suffix)] == suffix
    ):
        replacement = selected
        return EditResult(
            start - len(prefix),
            end + len(suffix),
            replacement,
            start - len(prefix),
            end - len(prefix),
        )
    if selected.startswith(prefix) and selected.endswith(suffix):
        inner = selected[len(prefix) : len(selected) - len(suffix)]
        return EditResult(start, end, inner, start, start + len(inner))
    content = selected or placeholder
    replacement = f"{prefix}{content}{suffix}"
    offset = start + len(prefix)
    return EditResult(start, end, replacement, offset, offset + len(content))


def prefix_lines(text: str, start: int, end: int, prefix: str) -> EditResult:
    line_start = text.rfind("\n", 0, start) + 1
    next_break = text.find("\n", end)
    line_end = len(text) if next_break == -1 else next_break
    block = text[line_start:line_end]
    lines = block.split("\n")
    non_empty = [line for line in lines if line]
    remove = bool(non_empty) and all(line.startswith(prefix) for line in non_empty)
    changed = [
        line[len(prefix) :] if remove and line.startswith(prefix) else prefix + line
        for line in lines
    ]
    replacement = "\n".join(changed)
    return EditResult(line_start, line_end, replacement, line_start, line_start + len(replacement))


def set_heading(text: str, start: int, end: int, level: int) -> EditResult:
    if level not in range(0, 7):
        raise ValueError("제목 수준은 0~6이어야 합니다.")
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    lines = text[line_start:line_end].split("\n")
    changed: list[str] = []
    marker = "#" * level
    for line in lines:
        stripped = line.lstrip()
        leading = line[: len(line) - len(stripped)]
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").lstrip()
        changed.append(f"{leading}{marker} {stripped}" if level else f"{leading}{stripped}")
    replacement = "\n".join(changed)
    return EditResult(line_start, line_end, replacement, line_start, line_start + len(replacement))


def insert_block(start: int, end: int, block: str) -> EditResult:
    replacement = block if block.endswith("\n") else block + "\n"
    return EditResult(start, end, replacement, start, start + len(replacement))


def apply_result(text: str, result: EditResult) -> str:
    return text[: result.start] + result.replacement + text[result.end :]
