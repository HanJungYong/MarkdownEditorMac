from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QToolBar

HEADING_ITEMS = ["본문", "H1", "H2", "H3", "H4", "H5", "H6"]


class MarkdownActions(QObject):
    """Formatting commands created exactly once per window.

    Every tab shows these same ``QAction`` objects in its own toolbar, so shortcuts
    such as Ctrl+B stay unique and always act on the active document.
    """

    command_requested = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.actions_by_command: dict[str, QAction] = {}
        self.toolbar_items: list[str | None] = []
        self._add("굵게", "bold", QKeySequence.StandardKey.Bold, "선택 영역을 굵게 표시")
        self._add("기울임", "italic", QKeySequence.StandardKey.Italic, "선택 영역을 기울임")
        self._add("취소선", "strike", None, "취소선 적용")
        self._add("코드", "inline_code", None, "인라인 코드 적용")
        self.toolbar_items.append(None)
        self.toolbar_items.append("heading")
        self._add("인용", "quote", None, "인용문")
        self._add("목록", "bullet", None, "글머리 목록")
        self._add("번호", "number", None, "번호 목록")
        self._add("할 일", "task", None, "작업 목록")
        self.toolbar_items.append(None)
        self._add("링크", "link", QKeySequence("Ctrl+K"), "링크 삽입")
        self._add("이미지", "image", None, "이미지 삽입")
        self._add("표", "table", None, "3×3 표 삽입")
        self._add("코드 블록", "code_block", None, "코드 블록 삽입")
        self._add("Mermaid", "mermaid", None, "Mermaid flowchart 삽입")
        self._add("구분선", "hr", None, "구분선 삽입")

    def _add(
        self,
        text: str,
        command: str,
        shortcut: QKeySequence.StandardKey | QKeySequence | None,
        tip: str,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.setToolTip(f"{text}: {tip}")
        action.triggered.connect(
            lambda _checked=False, value=command: self.command_requested.emit(value)
        )
        self.actions_by_command[command] = action
        self.toolbar_items.append(command)
        return action

    def set_enabled(self, enabled: bool) -> None:
        for action in self.actions_by_command.values():
            action.setEnabled(enabled)


class MarkdownToolbar(QToolBar):
    """Per-tab toolbar widget that displays the shared ``MarkdownActions``."""

    def __init__(self, actions: MarkdownActions, parent=None) -> None:  # noqa: ANN001
        super().__init__("마크다운 도구", parent)
        self.setMovable(False)
        self.markdown_actions = actions
        self.actions_by_command = actions.actions_by_command
        self.heading_combo: QComboBox | None = None
        for item in actions.toolbar_items:
            if item is None:
                self.addSeparator()
            elif item == "heading":
                self.heading_combo = QComboBox(self)
                self.heading_combo.addItems(HEADING_ITEMS)
                self.heading_combo.setToolTip("현재 줄의 제목 수준")
                self.heading_combo.activated.connect(
                    lambda index: actions.command_requested.emit(f"heading:{index}")
                )
                self.addWidget(self.heading_combo)
            else:
                self.addAction(actions.actions_by_command[item])
