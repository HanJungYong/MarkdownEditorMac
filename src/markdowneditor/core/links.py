from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

_MARKDOWN_LINK = re.compile(r"(!?)\[[^\]]*\]\((<[^>]+>|[^)]+)\)")
_REFERENCE_DEF = re.compile(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
_HTML_TARGET = re.compile(
    r"<(a|img)\b[^>]*?\s(href|src)\s*=\s*([\"'])(.*?)\3", re.IGNORECASE | re.DOTALL
)
_HTML_ID = re.compile(r"\bid\s*=\s*([\"'])(.*?)\1", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LinkReference:
    kind: str
    target: str
    line: int
    status: str
    resolved: str | None = None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def collect_explicit_ids(text: str) -> set[str]:
    return {match.group(2) for match in _HTML_ID.finditer(text)}


def resolve_target(target: str, document_dir: Path, anchors: set[str]) -> tuple[str, str | None]:
    clean = target.strip().strip("<>")
    if " " in clean and not clean.startswith(("http://", "https://")):
        clean = clean.split(maxsplit=1)[0]
    parsed = urlparse(clean)
    scheme = parsed.scheme.lower()
    if scheme in {"javascript", "vbscript"}:
        return "차단", None
    if scheme in {"http", "https", "mailto"}:
        return "외부-확인안함", clean
    if scheme == "data":
        return "내장", None
    if clean.startswith("#"):
        anchor = unquote(clean[1:])
        return ("정상" if anchor in anchors else "대상없음"), anchor

    fragment = unquote(parsed.fragment)
    path_part = unquote(parsed.path)
    if scheme == "file":
        resolved = Path(url2pathname(parsed.path)).resolve()
    elif re.match(r"^[A-Za-z]:[\\/]", clean):
        raw_path = clean.split("#", 1)[0].split("?", 1)[0]
        resolved = Path(unquote(raw_path)).resolve()
    elif scheme:
        return "차단", clean
    else:
        raw_path = path_part.replace("/", "\\")
        resolved = (document_dir / raw_path).resolve()
    if not resolved.exists():
        return "없음", str(resolved)
    if fragment and resolved.suffix.lower() in {".md", ".markdown"}:
        return "정상-앵커미확인", str(resolved)
    return "정상", str(resolved)


def inspect_links(text: str, document_path: str | Path) -> list[LinkReference]:
    document = Path(document_path).resolve()
    anchors = collect_explicit_ids(text)
    results: list[LinkReference] = []
    seen_spans: set[tuple[int, int]] = set()

    for match in _MARKDOWN_LINK.finditer(text):
        target = match.group(2)
        status, resolved = resolve_target(target, document.parent, anchors)
        results.append(
            LinkReference(
                kind="이미지" if match.group(1) else "링크",
                target=target,
                line=_line_number(text, match.start()),
                status=status,
                resolved=resolved,
            )
        )
        seen_spans.add(match.span())
    for match in _REFERENCE_DEF.finditer(text):
        target = match.group(1)
        status, resolved = resolve_target(target, document.parent, anchors)
        results.append(
            LinkReference(
                kind="참조정의",
                target=target,
                line=_line_number(text, match.start()),
                status=status,
                resolved=resolved,
            )
        )
    for match in _HTML_TARGET.finditer(text):
        target = match.group(4)
        status, resolved = resolve_target(target, document.parent, anchors)
        results.append(
            LinkReference(
                kind="이미지" if match.group(1).lower() == "img" else "링크",
                target=target,
                line=_line_number(text, match.start()),
                status=status,
                resolved=resolved,
            )
        )
    return results
