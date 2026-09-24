from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class DocumentError(ValueError):
    """사용자에게 설명할 수 있는 문서 입출력 오류."""


@dataclass(frozen=True, slots=True)
class DocumentFormat:
    encoding: str
    bom: bytes
    newline: str
    crlf_count: int
    lf_count: int
    cr_count: int
    trailing_newline: bool

    @property
    def mixed_newlines(self) -> bool:
        return sum(count > 0 for count in (self.crlf_count, self.lf_count, self.cr_count)) > 1

    @property
    def newline_label(self) -> str:
        return {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[self.newline]


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    path: Path
    text: str
    original_bytes: bytes
    format: DocumentFormat
    sha256: str
    warnings: tuple[str, ...] = ()

    @property
    def line_count(self) -> int:
        if not self.text:
            return 0
        return self.text.count("\n") + (0 if self.text.endswith("\n") else 1)


def _decode(raw: bytes) -> tuple[str, str, bytes]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict"), "utf-8", b"\xef\xbb\xbf"
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="strict"), "utf-16-le", b"\xff\xfe"
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="strict"), "utf-16-be", b"\xfe\xff"
    try:
        return raw.decode("utf-8", errors="strict"), "utf-8", b""
    except UnicodeDecodeError:
        try:
            return raw.decode("cp949", errors="strict"), "cp949", b""
        except UnicodeDecodeError as exc:
            raise DocumentError(
                "인코딩을 판별할 수 없습니다. UTF-8, UTF-16 또는 CP949 파일인지 확인하세요."
            ) from exc


def _newline_format(text: str) -> DocumentFormat:
    crlf_count = text.count("\r\n")
    without_crlf = text.replace("\r\n", "")
    lf_count = without_crlf.count("\n")
    cr_count = without_crlf.count("\r")
    counts = {"\r\n": crlf_count, "\n": lf_count, "\r": cr_count}
    newline = max(counts, key=counts.get) if any(counts.values()) else "\n"
    trailing = text.endswith(("\r\n", "\n", "\r"))
    return DocumentFormat(
        encoding="",
        bom=b"",
        newline=newline,
        crlf_count=crlf_count,
        lf_count=lf_count,
        cr_count=cr_count,
        trailing_newline=trailing,
    )


def load_document(
    path: str | Path,
    *,
    allow_unusual_extension: bool = False,
    allow_large: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> LoadedDocument:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise DocumentError(f"파일을 찾을 수 없습니다: {resolved}")
    if not resolved.is_file():
        raise DocumentError(f"폴더가 아닌 파일을 선택하세요: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS and not allow_unusual_extension:
        raise DocumentError(f"지원하는 마크다운 확장자가 아닙니다: {resolved.suffix or '(없음)'}")
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise DocumentError(f"파일을 읽을 수 없습니다: {exc}") from exc
    if len(raw) > max_bytes and not allow_large:
        raise DocumentError(f"파일이 너무 큽니다: {len(raw):,} bytes (기준 {max_bytes:,} bytes)")
    if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise DocumentError("텍스트 파일이 아닐 수 있습니다(NUL 바이트 발견).")

    decoded, encoding, bom = _decode(raw)
    base_format = _newline_format(decoded)
    fmt = DocumentFormat(
        encoding=encoding,
        bom=bom,
        newline=base_format.newline,
        crlf_count=base_format.crlf_count,
        lf_count=base_format.lf_count,
        cr_count=base_format.cr_count,
        trailing_newline=base_format.trailing_newline,
    )
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    warnings: list[str] = []
    if fmt.mixed_newlines:
        warnings.append(
            f"줄바꿈이 섞여 있습니다. 편집 저장 시 대표 형식 {fmt.newline_label}으로 통일됩니다."
        )
    if encoding == "cp949":
        warnings.append("CP949로 열었습니다. 표현할 수 없는 문자는 UTF-8 저장이 필요합니다.")
    return LoadedDocument(
        path=resolved,
        text=normalized,
        original_bytes=raw,
        format=fmt,
        sha256=hashlib.sha256(raw).hexdigest(),
        warnings=tuple(warnings),
    )


def encode_document(document: LoadedDocument, text: str, *, edited: bool) -> bytes:
    if not edited and text == document.text:
        return document.original_bytes

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if document.format.trailing_newline and normalized and not normalized.endswith("\n"):
        normalized += "\n"
    elif not document.format.trailing_newline:
        normalized = normalized.rstrip("\n")
    external = normalized.replace("\n", document.format.newline)
    try:
        payload = external.encode(document.format.encoding, errors="strict")
    except UnicodeEncodeError as exc:
        raise DocumentError(
            f"{document.format.encoding.upper()}로 표현할 수 없는 문자가 있습니다: 위치 {exc.start}"
        ) from exc
    return document.format.bom + payload


def atomic_write(path: str | Path, data: bytes) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        return target
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise DocumentError(f"파일을 안전하게 저장하지 못했습니다: {exc}") from exc
