from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from markdowneditor.core.editing import INDENT_TEXT, newline_prefix
from markdowneditor.core.view_settings import DEFAULT_LETTER_SPACING, clamp_letter_spacing
from markdowneditor.gui.fonts import DEFAULT_FONT_SIZE, editor_font


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:  # noqa: ANN001
        super().__init__(document)
        self.rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        self.set_dark_mode(False)

    def set_dark_mode(self, enabled: bool) -> None:
        palettes = {
            False: (
                "#005fcc",
                "#7047b8",
                "#596579",
                "#b42318",
                "#0076a8",
                "#087443",
                "#7646a8",
                "#667085",
                "#c4320a",
            ),
            True: (
                "#65a8ff",
                "#a78bfa",
                "#aab4c3",
                "#ff8a70",
                "#39bdf8",
                "#55d187",
                "#c4a7ff",
                "#8994a5",
                "#ff7657",
            ),
        }
        heading, emphasis, strike, code, link, listing, quote, comment, html = palettes[enabled]
        self.rules.clear()
        self._add(r"^#{1,6}\s+.*$", heading, bold=True)
        self._add(r"\*\*[^*]+\*\*|__[^_]+__", emphasis, bold=True)
        self._add(r"~~[^~]+~~", strike)
        self._add(r"`[^`]+`", code)
        self._add(r"!?\[[^\]]*\]\([^)]+\)", link)
        self._add(r"^\s*(?:[-+*]|\d+\.)\s+", listing, bold=True)
        self._add(r"^\s*>\s+", quote, bold=True)
        self._add(r"<!--.*?-->", comment)
        self._add(r"</?[A-Za-z][^>]*>", html)
        self.rehighlight()

    def _add(self, pattern: str, color: str, *, bold: bool = False) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        self.rules.append((re.compile(pattern), fmt))

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor: MarkdownEditorWidget) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        self.editor.paint_line_numbers(event)


class MarkdownEditorWidget(QPlainTextEdit):
    font_zoom_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.highlighter = MarkdownHighlighter(self.document())
        self.dark_mode = False
        self.auto_indent_enabled = True
        self.markdown_font_size = DEFAULT_FONT_SIZE
        self.letter_spacing = DEFAULT_LETTER_SPACING
        self._apply_editor_font()
        self.set_dark_mode(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.blockCountChanged.connect(self.update_line_number_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.update_line_number_width()

    def raw_text(self) -> str:
        return self.document().toRawText().replace("\u2029", "\n")

    def first_visible_source_line(self) -> int:
        block = self.firstVisibleBlock()
        return block.blockNumber() + 1 if block.isValid() else 1

    def scroll_source_line_to_top(self, line: float) -> int:
        block_count = max(1, self.blockCount())
        target = max(1, min(block_count, round(line)))
        block = self.document().findBlockByNumber(target - 1)
        if not block.isValid():
            return self.first_visible_source_line()

        scrollbar = self.verticalScrollBar()
        previous_cursor = self.textCursor()
        target_cursor = self.textCursor()
        target_cursor.setPosition(block.position())
        editor_blocker = QSignalBlocker(self)
        self.setTextCursor(target_cursor)
        self.centerCursor()
        lines_above = max(0, self.cursorRect(target_cursor).top()) / max(
            1, self.fontMetrics().lineSpacing()
        )
        target_value = scrollbar.value() + round(lines_above)
        self.setTextCursor(previous_cursor)
        scrollbar.setValue(target_value)
        del editor_blocker
        return self.first_visible_source_line()

    def setPlainText(self, text: str) -> None:  # noqa: N802
        super().setPlainText(text)
        # QPlainTextEdit reapplies its original viewport margins at the end of a
        # bulk document replacement on Windows. Recalculate after replacement so
        # 3-4 digit line numbers never overlap the first Markdown characters.
        self.update_line_number_width()

    def line_number_area_width(self, block_count: int | None = None) -> int:
        count = self.blockCount() if block_count is None else block_count
        digits = len(str(max(1, count)))
        # Line numbers use their own 100%-spacing font, so measure with that font.
        return 12 + self.line_number_area.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_width(self, block_count: int = 0) -> None:
        count = block_count if block_count > 0 else self.blockCount()
        self.setViewportMargins(self.line_number_area_width(count), 0, 0, 0)
        self._layout_line_number_area()

    def _layout_line_number_area(self) -> None:
        contents = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_width()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._layout_line_number_area()

    def paint_line_numbers(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self.line_number_area)
        background = "#111419" if self.dark_mode else "#f2f4f7"
        foreground = "#9aa4b2" if self.dark_mode else "#596579"
        painter.fillRect(event.rect(), QColor(background))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setPen(QColor(foreground))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def set_markdown_font_size(self, size: int) -> None:
        self.markdown_font_size = int(size)
        self._apply_editor_font()

    def set_letter_spacing(self, percent: int) -> None:
        self.letter_spacing = clamp_letter_spacing(percent)
        self._apply_editor_font()

    def _apply_editor_font(self) -> None:
        # Size and letter spacing are stored separately so changing one never drops the other.
        self.setFont(editor_font(self.markdown_font_size, self.letter_spacing))
        self.line_number_area.setFont(editor_font(self.markdown_font_size, DEFAULT_LETTER_SPACING))
        self.update_line_number_width()
        self.viewport().update()
        self.line_number_area.update()

    def set_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        if enabled:
            editor_style = (
                "background: #050607; color: #f4f6f8; "
                "selection-background-color: #264f78; selection-color: #ffffff; "
                "border: 1px solid #343a43;"
            )
        else:
            editor_style = (
                "background: #ffffff; color: #202124; "
                "selection-background-color: #cfe4ff; selection-color: #111827; "
                "border: 1px solid #d0d5dd;"
            )
        scrollbar_style = """
QScrollBar:vertical, QScrollBar:horizontal {
  background: #f2f4f7;
  border: 1px solid #d0d5dd;
}
QScrollBar:vertical { width: 14px; }
QScrollBar:horizontal { height: 14px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
  background: #98a2b3;
  border-radius: 5px;
  min-height: 28px;
  min-width: 28px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
  background: #667085;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""
        self.setStyleSheet(f"QPlainTextEdit {{ {editor_style} }}\n{scrollbar_style}")
        self.highlighter.set_dark_mode(enabled)
        self.line_number_area.update()

    def set_auto_indent(self, enabled: bool) -> None:
        self.auto_indent_enabled = enabled

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        modifiers = event.modifiers()
        blocked_modifiers = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if event.key() == Qt.Key.Key_Tab and not modifiers & blocked_modifiers:
            self._insert_space_indentation()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            modifiers & blocked_modifiers
        ):
            self._insert_smart_newline()
            event.accept()
            return
        super().keyPressEvent(event)

    def _insert_space_indentation(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText(INDENT_TEXT)
            return

        document = self.document()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        first = document.findBlock(start)
        last = document.findBlock(end)
        if end == last.position() and end > start:
            last = last.previous()
        positions: list[int] = []
        block = first
        while block.isValid():
            positions.append(block.position())
            if block == last:
                break
            block = block.next()
        cursor.beginEditBlock()
        for position in reversed(positions):
            line_cursor = self.textCursor()
            line_cursor.setPosition(position)
            line_cursor.insertText(INDENT_TEXT)
        cursor.endEditBlock()

    def _insert_smart_newline(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        before_cursor = cursor.block().text()[: cursor.positionInBlock()]
        prefix = newline_prefix(before_cursor, auto_indent=self.auto_indent_enabled)
        cursor.insertText(f"\n{prefix}")
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def wheelEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.font_zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def set_word_wrap(self, enabled: bool) -> None:
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.setLineWrapMode(mode)
