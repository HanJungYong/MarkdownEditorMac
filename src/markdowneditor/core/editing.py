from __future__ import annotations

import re

INDENT_WIDTH = 2
INDENT_TEXT = " " * INDENT_WIDTH

_LEADING_WHITESPACE = re.compile(r"^[ \t]*")
_QUOTE_PREFIX = re.compile(r"^(?:>[ \t]*)+")
_BULLET_PREFIX = re.compile(r"^(?P<bullet>[-+*])[ \t]+(?P<task>\[[ xX]\][ \t]+)?")
_NUMBER_PREFIX = re.compile(r"^(?P<number>\d+)(?P<delimiter>[.)])[ \t]+")


def newline_prefix(line_before_cursor: str, *, auto_indent: bool) -> str:
    """Return indentation and Markdown block marker for the next line."""

    whitespace_match = _LEADING_WHITESPACE.match(line_before_cursor)
    whitespace = whitespace_match.group(0) if whitespace_match else ""
    remainder = line_before_cursor[len(whitespace) :]
    indentation = whitespace.replace("\t", INDENT_TEXT) if auto_indent else ""

    quote_match = _QUOTE_PREFIX.match(remainder)
    quote = quote_match.group(0) if quote_match else ""
    after_quote = remainder[len(quote) :]

    bullet_match = _BULLET_PREFIX.match(after_quote)
    if bullet_match:
        task = "[ ] " if bullet_match.group("task") else ""
        return f"{indentation}{quote}{bullet_match.group('bullet')} {task}"

    number_match = _NUMBER_PREFIX.match(after_quote)
    if number_match:
        number = int(number_match.group("number")) + 1
        return f"{indentation}{quote}{number}{number_match.group('delimiter')} "

    if quote:
        return f"{indentation}{quote}"
    return indentation
