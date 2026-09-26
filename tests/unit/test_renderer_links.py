from __future__ import annotations

from pathlib import Path

from markdowneditor.core.links import inspect_links, resolve_target
from markdowneditor.core.renderer import render_markdown, sanitize_html


def test_front_matter_tables_headings_and_mermaid() -> None:
    source = """---
title: 문서
---

# 같은 제목
# 같은 제목

| A | B |
|---|---|
| 1 | 2 |

<table><tr><td rowspan="2">원문</td></tr><tr><td>표</td></tr></table>

```mermaid
flowchart TD
  A --> B
```
"""
    result = render_markdown(source)

    assert "문서 정보" in result.html
    assert "source_file" not in result.html
    assert 'id="같은-제목"' in result.html
    assert 'id="같은-제목-1"' in result.html
    assert result.table_count == 2
    assert result.mermaid_count == 1
    assert 'rowspan="2"' in result.html
    assert '<span class="source-anchor" data-line="' in result.html
    assert '<h1 data-line="' in result.html


def test_security_sanitizer_removes_active_content_but_keeps_table() -> None:
    unsafe = """
<script>window.pwned=true</script>
<img src="x.png" onerror="alert(1)">
<a href="javascript:alert(1)">위험</a>
<iframe src="x"></iframe>
<table><tr><td colspan="2">안전</td></tr></table>
"""
    safe = sanitize_html(unsafe)
    assert "script" not in safe
    assert "onerror" not in safe
    assert "javascript:" not in safe
    assert "iframe" not in safe
    assert '<td colspan="2">안전</td>' in safe


def test_external_image_is_blocked_by_default() -> None:
    safe = sanitize_html('<img src="https://example.com/a.png" alt="외부">')
    assert "https://" not in safe
    assert 'data-external-blocked="true"' in safe


def test_link_inspection_decodes_local_paths_and_blocks_dangerous(tmp_path: Path) -> None:
    document = tmp_path / "문서.md"
    target = tmp_path / "한글 파일.csv"
    target.write_text("a,b", encoding="utf-8")
    source = """<a id="안쪽"></a>
[파일](한글%20파일.csv)
[안쪽](#안쪽)
[없음](missing.json)
[외부](https://example.com)
[위험](javascript:alert(1))
"""
    document.write_text(source, encoding="utf-8")

    links = inspect_links(source, document)
    statuses = {item.target: item.status for item in links}

    assert statuses["한글%20파일.csv"] == "정상"
    assert statuses["#안쪽"] == "정상"
    assert statuses["missing.json"] == "없음"
    assert statuses["https://example.com"] == "외부-확인안함"
    assert statuses["javascript:alert(1"] == "차단"


def test_link_resolution_file_parent_fragment_and_unknown_scheme(tmp_path: Path) -> None:
    nested = tmp_path / "하위"
    nested.mkdir()
    target = tmp_path / "공백 파일.md"
    target.write_text("# 대상", encoding="utf-8")

    status, resolved = resolve_target("../공백%20파일.md#대상", nested, set())
    assert status == "정상-앵커미확인"
    assert resolved == str(target.resolve())
    assert resolve_target(target.as_uri(), nested, set()) == ("정상", str(target.resolve()))
    assert resolve_target("custom://value", nested, set())[0] == "차단"


def test_self_created_syntax_and_broken_fixtures_do_not_crash() -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    syntax = render_markdown((fixtures / "syntax_all.md").read_text(encoding="utf-8"))
    broken_source = (fixtures / "broken.md").read_text(encoding="utf-8") + "\n" + ("가" * 10_000)
    broken = render_markdown(broken_source)
    assert syntax.table_count >= 2
    assert "문서 정보" in syntax.html
    assert broken.html
    assert "가" * 100 in broken.html


def test_nested_local_links_support_markdown_and_windows_separators(tmp_path: Path) -> None:
    folder = tmp_path / "한글 폴더"
    folder.mkdir()
    target = folder / "그림.png"
    target.write_bytes(b"image")
    for link in ("한글%20폴더/그림.png", r"한글%20폴더\그림.png"):
        assert resolve_target(link, tmp_path, set()) == ("정상", str(target.resolve()))
