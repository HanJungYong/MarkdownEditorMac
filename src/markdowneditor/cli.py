from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from markdowneditor import __version__
from markdowneditor.core.file_io import DocumentError, load_document
from markdowneditor.core.links import inspect_links
from markdowneditor.core.renderer import render_markdown


def _check(path: str, as_json: bool) -> int:
    try:
        document = load_document(path, allow_large=True)
    except DocumentError as exc:
        payload = {"status": "FAIL", "error": str(exc), "path": str(Path(path).resolve())}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if as_json else f"오류: {exc}")
        return 2
    result = render_markdown(document.text)
    links = inspect_links(document.text, document.path)
    problems = [item for item in links if item.status in {"없음", "대상없음", "차단"}]
    payload = {
        "status": "PASS" if not problems else "WARN",
        "path": str(document.path),
        "bytes": len(document.original_bytes),
        "sha256": document.sha256,
        "encoding": document.format.encoding,
        "bom": bool(document.format.bom),
        "newline": document.format.newline_label,
        "lines": document.line_count,
        "render_ms": round(result.elapsed_ms, 3),
        "headings": result.heading_count,
        "tables": result.table_count,
        "images": result.image_count,
        "mermaid": result.mermaid_count,
        "links": len(links),
        "problems": [
            {
                "line": item.line,
                "kind": item.kind,
                "target": item.target,
                "status": item.status,
                "resolved": item.resolved,
            }
            for item in problems
        ],
        "warnings": list(document.warnings),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"상태: {payload['status']}")
        print(f"파일: {payload['path']}")
        print(
            f"형식: {payload['encoding'].upper()} · {payload['newline']} · "
            f"{payload['bytes']:,} bytes · {payload['lines']:,}줄"
        )
        print(
            f"렌더: {payload['render_ms']:.1f}ms · 제목 {payload['headings']} · "
            f"표 {payload['tables']} · 이미지 {payload['images']} · Mermaid {payload['mermaid']}"
        )
        print(f"연결: {payload['links']}개 · 문제 {len(problems)}개")
        for problem in problems[:20]:
            print(f"  {problem['line']}줄 [{problem['status']}] {problem['target']}")
    return 0 if not problems else 1


def _render(path: str, output: str) -> int:
    try:
        document = load_document(path, allow_large=True)
    except DocumentError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    result = render_markdown(document.text)
    style = """
body { max-width: 1100px; margin: 2rem auto;
       font: 15px/1.65 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; }
table { border-collapse: collapse; display: block; overflow: auto; }
th, td { border: 1px solid #bbb; padding: 6px; }
img { max-width: 100%; height: auto; }
pre { overflow: auto; }
"""
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{document.path.name}</title>
<style>{style}</style>
</head><body>{result.html}</body></html>"""
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    print(f"HTML을 저장했습니다: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MarkdownEditor 진단 CLI")
    parser.add_argument("--version", action="version", version=f"MarkdownEditor {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="문서와 연결 요소 점검")
    check.add_argument("file")
    check.add_argument("--json", action="store_true")
    render = subparsers.add_parser("render", help="미리보기 HTML 내보내기")
    render.add_argument("file")
    render.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _check(args.file, args.json)
    if args.command == "render":
        return _render(args.file, args.out)
    return 2
