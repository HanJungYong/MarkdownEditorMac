from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QToolBar


class MarkdownToolbar(QToolBar):
    command_requested = Signal(str)

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__("마크다운 도구", parent)
        self.setMovable(False)
        self.actions_by_command: dict[str, QAction] = {}
        self._add("굵게", "bold", QKeySequence.StandardKey.Bold, "선택 영역을 굵게 표시")
        self._add("기울임", "italic", QKeySequence.StandardKey.Italic, "선택 영역을 기울임")
        self._add("취소선", "strike", None, "취소선 적용")
        self._add("코드", "inline_code", None, "인라인 코드 적용")
        self.addSeparator()
        heading = QComboBox(self)
        heading.addItems(["본문", "H1", "H2", "H3", "H4", "H5", "H6"])
        heading.setToolTip("현재 줄의 제목 수준")
        heading.activated.connect(lambda index: self.command_requested.emit(f"heading:{index}"))
        self.addWidget(heading)
        self._add("인용", "quote", None, "인용문")
        self._add("목록", "bullet", None, "글머리 목록")
        self._add("번호", "number", None, "번호 목록")
        self._add("할 일", "task", None, "작업 목록")
        self.addSeparator()
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
        self.addAction(action)
        self.actions_by_command[command] = action
        return action
