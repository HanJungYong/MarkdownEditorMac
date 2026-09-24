from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

_DANGEROUS_TAGS = {"script", "iframe", "object", "embed", "base", "meta", "form"}
_DANGEROUS_VOID_TAGS = {"base", "meta", "embed"}
_ALLOWED_TAGS = {
    "a",
    "article",
    "blockquote",
    "br",
    "code",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "input",
    "kbd",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
_GLOBAL_ATTRS = {"id", "class", "title", "data-line", "dir", "lang"}
_TAG_ATTRS = {
    "a": {"href", "name"},
    "img": {"src", "alt", "width", "height"},
    "td": {"rowspan", "colspan", "align"},
    "th": {"rowspan", "colspan", "align", "scope"},
    "input": {"type", "checked", "disabled"},
    "ol": {"start"},
}
_VOID_TAGS = {"br", "hr", "img", "input"}


class _Sanitizer(HTMLParser):
    def __init__(self, allow_external_images: bool) -> None:
        super().__init__(convert_charrefs=False)
        self.allow_external_images = allow_external_images
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            if tag not in _DANGEROUS_VOID_TAGS:
                self.skip_depth += 1
            return
        if self.skip_depth or tag not in _ALLOWED_TAGS:
            return
        allowed = _GLOBAL_ATTRS | _TAG_ATTRS.get(tag, set())
        clean_attrs: list[str] = []
        for name, value in attrs:
            lowered = name.lower()
            if lowered.startswith("on") or lowered not in allowed:
                continue
            actual = "" if value is None else value
            if lowered in {"href", "src"}:
                compact = actual.strip().lower()
                if compact.startswith(("javascript:", "vbscript:")):
                    continue
                if (
                    tag == "img"
                    and compact.startswith(("http://", "https://"))
                    and not self.allow_external_images
                ):
                    clean_attrs.append('data-external-blocked="true"')
                    continue
            clean_attrs.append(f'{lowered}="{html.escape(actual, quote=True)}"')
        suffix = " " + " ".join(clean_attrs) if clean_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DANGEROUS_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if not self.skip_depth and tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&#{name};")

    def get_html(self) -> str:
        return "".join(self.parts)


@dataclass(frozen=True, slots=True)
class RenderResult:
    html: str
    elapsed_ms: float
    heading_count: int
    table_count: int
    image_count: int
    mermaid_count: int


def github_slug(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text).strip().lower()
    value = re.sub(r"[^\w\-\s가-힣]", "", value, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", value).strip("-") or "section"


def sanitize_html(value: str, *, allow_external_images: bool = False) -> str:
    parser = _Sanitizer(allow_external_images)
    parser.feed(value)
    parser.close()
    return parser.get_html()


def _front_matter_renderer(tokens: list[Any], index: int, *_: Any) -> str:
    token = tokens[index]
    raw = token.content
    line = token.map[0] + 1 if token.map else 1
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        parsed = None
    if not isinstance(parsed, dict):
        return (
            f'<details class="front-matter" data-line="{line}">'
            "<summary>문서 정보(해석 실패)</summary>"
            f"<pre>{html.escape(raw)}</pre></details>"
        )
    rows = "".join(
        f"<dt>{html.escape(str(key))}</dt><dd>{html.escape(str(value))}</dd>"
        for key, value in parsed.items()
    )
    return (
        f'<details class="front-matter" data-line="{line}">'
        f"<summary>문서 정보</summary><dl>{rows}</dl></details>"
    )


def _html_block_renderer(tokens: list[Any], index: int, *_: Any) -> str:
    token = tokens[index]
    line = token.map[0] + 1 if token.map else 1
    return f'<span class="source-anchor" data-line="{line}"></span>{token.content}'


def _fence_renderer(tokens: list[Any], index: int, *_: Any) -> str:
    token = tokens[index]
    language = token.info.strip().split(maxsplit=1)[0] if token.info.strip() else ""
    line = token.map[0] + 1 if token.map else 1
    if language.lower() == "mermaid":
        return (
            f'<div class="mermaid-wrap" data-line="{line}">'
            f'<pre class="mermaid">{html.escape(token.content)}</pre></div>'
        )
    class_name = f' class="language-{html.escape(language, quote=True)}"' if language else ""
    label = f'<span class="code-language">{html.escape(language)}</span>' if language else ""
    escaped_content = html.escape(token.content)
    return (
        f'<div class="code-wrap" data-line="{line}">{label}'
        f"<pre><code{class_name}>{escaped_content}</code></pre></div>"
    )


def _make_markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "linkify": True})
    md.enable("table")
    md.enable("strikethrough")
    md.use(front_matter_plugin)
    md.use(footnote_plugin)
    md.use(tasklists_plugin, enabled=False)
    md.renderer.rules["front_matter"] = _front_matter_renderer
    md.renderer.rules["fence"] = _fence_renderer
    md.renderer.rules["html_block"] = _html_block_renderer
    return md


def render_markdown(source: str, *, allow_external_images: bool = False) -> RenderResult:
    started = time.perf_counter()
    md = _make_markdown()
    env: dict[str, Any] = {}
    tokens = md.parse(source, env)
    slug_counts: dict[str, int] = {}
    heading_count = 0
    for index, token in enumerate(tokens):
        if token.map and token.nesting == 1:
            token.attrSet("data-line", str(token.map[0] + 1))
        if token.type == "heading_open" and index + 1 < len(tokens):
            heading_count += 1
            base = github_slug(tokens[index + 1].content)
            occurrence = slug_counts.get(base, 0)
            slug_counts[base] = occurrence + 1
            token.attrSet("id", base if occurrence == 0 else f"{base}-{occurrence}")
    rendered = md.renderer.render(tokens, md.options, env)
    safe = sanitize_html(rendered, allow_external_images=allow_external_images)
    elapsed = (time.perf_counter() - started) * 1000
    return RenderResult(
        html=safe,
        elapsed_ms=elapsed,
        heading_count=heading_count,
        table_count=len(re.findall(r"<table(?:\s|>)", safe, flags=re.IGNORECASE)),
        image_count=len(re.findall(r"<img(?:\s|>)", safe, flags=re.IGNORECASE)),
        mermaid_count=len(re.findall(r'class="mermaid"', safe)),
    )
