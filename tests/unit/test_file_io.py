from __future__ import annotations

from pathlib import Path

import pytest

from markdowneditor.core.file_io import (
    DocumentError,
    atomic_write,
    encode_document,
    load_document,
)


@pytest.mark.parametrize(
    ("raw", "encoding", "bom"),
    [
        ("한글\n".encode(), "utf-8", b""),
        (b"\xef\xbb\xbf" + "한글\r\n".encode(), "utf-8", b"\xef\xbb\xbf"),
        (b"\xff\xfe" + "한글\r\n".encode("utf-16-le"), "utf-16-le", b"\xff\xfe"),
        (b"\xfe\xff" + "한글\r".encode("utf-16-be"), "utf-16-be", b"\xfe\xff"),
        ("한글\r\n".encode("cp949"), "cp949", b""),
    ],
)
def test_load_and_unedited_round_trip(
    tmp_path: Path, raw: bytes, encoding: str, bom: bytes
) -> None:
    path = tmp_path / "문서.md"
    path.write_bytes(raw)

    document = load_document(path)

    assert document.format.encoding == encoding
    assert document.format.bom == bom
    assert encode_document(document, document.text, edited=False) == raw


def test_newline_metadata_and_unicode_preservation(tmp_path: Path) -> None:
    raw = "탭\tNBSP\u00a0전각\u3000\r\n둘\n셋\r".encode()
    path = tmp_path / "혼합.md"
    path.write_bytes(raw)

    document = load_document(path)

    assert document.format.mixed_newlines
    assert (document.format.crlf_count, document.format.lf_count, document.format.cr_count) == (
        1,
        1,
        1,
    )
    assert "\t" in document.text
    assert "\u00a0" in document.text
    assert "\u3000" in document.text
    assert document.warnings


def test_rejects_missing_directory_binary_and_extension(tmp_path: Path) -> None:
    with pytest.raises(DocumentError, match="찾을 수 없습니다"):
        load_document(tmp_path / "없음.md")
    with pytest.raises(DocumentError, match="폴더가 아닌"):
        load_document(tmp_path)
    wrong = tmp_path / "문서.txt"
    wrong.write_text("text", encoding="utf-8")
    with pytest.raises(DocumentError, match="확장자"):
        load_document(wrong)
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"abc\x00def")
    with pytest.raises(DocumentError, match="NUL"):
        load_document(binary)


def test_cp949_unrepresentable_character_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "cp949.md"
    path.write_bytes("한글".encode("cp949"))
    document = load_document(path)

    with pytest.raises(DocumentError, match="표현할 수 없는"):
        encode_document(document, document.text + " 😀", edited=True)


def test_atomic_write(tmp_path: Path) -> None:
    path = tmp_path / "결과.md"
    atomic_write(path, b"first")
    atomic_write(path, b"second")
    assert path.read_bytes() == b"second"
    assert not list(tmp_path.glob("*.tmp"))


def test_empty_large_and_undecodable_inputs(tmp_path: Path) -> None:
    empty = tmp_path / "빈 문서.md"
    empty.write_bytes(b"")
    document = load_document(empty)
    assert document.text == ""
    assert document.line_count == 0

    large = tmp_path / "큰 문서.md"
    large.write_bytes(b"12345")
    with pytest.raises(DocumentError, match="너무 큽니다"):
        load_document(large, max_bytes=4)
    assert load_document(large, max_bytes=4, allow_large=True).text == "12345"

    undecodable = tmp_path / "인코딩 실패.md"
    undecodable.write_bytes(b"\x81")
    with pytest.raises(DocumentError, match="인코딩을 판별"):
        load_document(undecodable)


@pytest.mark.parametrize(
    ("raw", "edited", "expected"),
    [
        (b"a\r\nb\r\n", "a\nb 변경", b"a\r\nb \xeb\xb3\x80\xea\xb2\xbd\r\n"),
        (b"a\rb", "a\nb 변경\n", b"a\rb \xeb\xb3\x80\xea\xb2\xbd"),
    ],
)
def test_edited_save_preserves_newline_and_trailing_policy(
    tmp_path: Path, raw: bytes, edited: str, expected: bytes
) -> None:
    path = tmp_path / "줄바꿈.md"
    path.write_bytes(raw)
    document = load_document(path)
    assert encode_document(document, edited, edited=True) == expected
