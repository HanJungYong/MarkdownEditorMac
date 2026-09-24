import pytest

from markdowneditor.core.md_actions import (
    apply_result,
    insert_block,
    prefix_lines,
    set_heading,
    wrap_inline,
)


def test_wrap_and_unwrap_inline() -> None:
    text = "한글 텍스트"
    wrapped = wrap_inline(text, 3, len(text), "**", placeholder="굵은 글씨")
    changed = apply_result(text, wrapped)
    assert changed == "한글 **텍스트**"
    unwrapped = wrap_inline(changed, 5, 8, "**")
    assert apply_result(changed, unwrapped) == text


def test_empty_inline_inserts_placeholder_and_selects_inside() -> None:
    result = wrap_inline("", 0, 0, "`", placeholder="코드")
    assert result.replacement == "`코드`"
    assert (result.selection_start, result.selection_end) == (1, 3)


def test_prefix_multiple_lines_toggles() -> None:
    text = "첫째\n둘째\n셋째"
    result = prefix_lines(text, 0, 5, "> ")
    changed = apply_result(text, result)
    assert changed == "> 첫째\n> 둘째\n셋째"
    assert apply_result(changed, prefix_lines(changed, 0, 9, "> ")) == text


def test_heading_replaces_existing_level() -> None:
    text = "### 제목\n본문"
    assert apply_result(text, set_heading(text, 0, 0, 2)) == "## 제목\n본문"
    assert apply_result(text, set_heading(text, 0, 0, 0)) == "제목\n본문"


def test_insert_block_adds_one_trailing_newline() -> None:
    result = insert_block(0, 0, "---")
    assert result.replacement == "---\n"


def test_unicode_multiline_list_round_trip_and_invalid_heading() -> None:
    text = "한글 😀\n둘째 줄"
    changed = apply_result(text, prefix_lines(text, 0, len(text), "- [ ] "))
    assert changed == "- [ ] 한글 😀\n- [ ] 둘째 줄"
    assert apply_result(changed, prefix_lines(changed, 0, len(changed), "- [ ] ")) == text

    with pytest.raises(ValueError, match="0~6"):
        set_heading(text, 0, 0, 7)
