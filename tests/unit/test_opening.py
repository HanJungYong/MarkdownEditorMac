from __future__ import annotations

import os
from pathlib import Path

from markdowneditor.core.opening import (
    DropEntry,
    OpenSummary,
    classify_drop,
    document_key,
    same_document,
)


def _local(path: Path) -> DropEntry:
    return DropEntry(display=str(path), local_path=str(path))


def test_document_key_ignores_case_separators_and_relative_parts(tmp_path: Path) -> None:
    target = tmp_path / "한글 폴더" / "문서 (1).md"
    target.parent.mkdir()
    target.write_text("# a\n", encoding="utf-8")
    variants = [
        target,
        Path(str(target).upper()),
        Path(str(target).replace("\\", "/")),
        tmp_path / "한글 폴더" / ".." / "한글 폴더" / "문서 (1).md",
    ]
    keys = {document_key(item) for item in variants}
    assert len(keys) == 1
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        assert document_key(Path("한글 폴더") / "문서 (1).md") == document_key(target)
    finally:
        os.chdir(cwd)


def test_same_document_detects_hard_links(tmp_path: Path) -> None:
    original = tmp_path / "a.md"
    original.write_text("x", encoding="utf-8")
    link = tmp_path / "b.md"
    try:
        os.link(original, link)
    except OSError:
        return  # file system without hard links: nothing to check
    assert document_key(original) != document_key(link)
    assert same_document(original, link)
    assert not same_document(original, tmp_path / "없는.md")


def test_classify_drop_keeps_markdown_in_order_and_explains_skips(tmp_path: Path) -> None:
    first = tmp_path / "둘째 문서.MD"
    second = tmp_path / "첫째 (초안).markdown"
    image = tmp_path / "그림.png"
    shortcut = tmp_path / "바로 가기.lnk"
    folder = tmp_path / "폴더.md"
    for item in (first, second, image, shortcut):
        item.write_text("x", encoding="utf-8")
    folder.mkdir()
    entries = [
        _local(first),
        _local(image),
        DropEntry(display="https://example.com/a.md"),
        _local(second),
        _local(first),
        _local(shortcut),
        _local(folder),
        _local(tmp_path / "없음.md"),
    ]
    plan = classify_drop(entries)
    assert plan.paths == [first, second]
    assert plan.has_local_files
    reasons = dict(plan.skipped)
    assert reasons["그림.png"] == "마크다운 파일이 아님"
    assert reasons["https://example.com/a.md"] == "로컬 파일이 아님"
    assert reasons["바로 가기.lnk"] == "바로 가기 파일"
    assert reasons["폴더.md"] == "폴더"
    assert reasons["없음.md"] == "파일이 없음"


def test_remote_only_drop_has_no_local_files() -> None:
    plan = classify_drop([DropEntry(display="https://example.com/readme.md")])
    assert not plan.can_open
    assert not plan.has_local_files


def test_open_summary_text() -> None:
    summary = OpenSummary()
    assert summary.status_text() == ""
    summary.opened.append(Path("a.md"))
    summary.already_open.append(Path("b.md"))
    summary.failed.append(("c.md", "인코딩"))
    summary.skipped.append(("d.png", "마크다운 파일이 아님"))
    assert summary.status_text() == "열림 1 · 이미 열림 1 · 건너뜀 1 · 실패 1"
    assert summary.problem_lines() == ["c.md: 인코딩", "d.png: 마크다운 파일이 아님"]
