from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from markdowneditor.gui.editor import MarkdownEditorWidget


class FindReplaceDialog(QDialog):
    def __init__(self, editor: MarkdownEditorWidget, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle("찾기 및 바꾸기")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.find_edit = QLineEdit(self)
        self.replace_edit = QLineEdit(self)
        self.case_box = QCheckBox("대소문자 구분", self)
        self.word_box = QCheckBox("단어 단위", self)
        self.regex_box = QCheckBox("정규식", self)
        self.result_label = QLabel("", self)

        form = QFormLayout()
        form.addRow("찾을 내용", self.find_edit)
        form.addRow("바꿀 내용", self.replace_edit)
        options = QHBoxLayout()
        options.addWidget(self.case_box)
        options.addWidget(self.word_box)
        options.addWidget(self.regex_box)
        buttons = QHBoxLayout()
        find_button = QPushButton("다음 찾기", self)
        replace_button = QPushButton("바꾸기", self)
        all_button = QPushButton("모두 바꾸기", self)
        close_button = QPushButton("닫기", self)
        buttons.addWidget(find_button)
        buttons.addWidget(replace_button)
        buttons.addWidget(all_button)
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(options)
        layout.addWidget(self.result_label)
        layout.addLayout(buttons)

        find_button.clicked.connect(self.find_next)
        replace_button.clicked.connect(self.replace_one)
        all_button.clicked.connect(self.replace_all)
        close_button.clicked.connect(self.close)
        self.find_edit.returnPressed.connect(self.find_next)

    def _flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self.case_box.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.word_box.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def find_next(self) -> bool:
        pattern = self.find_edit.text()
        if not pattern:
            return False
        if self.regex_box.isChecked():
            source = self.editor.raw_text()
            start = self.editor.textCursor().selectionEnd()
            flags = 0 if self.case_box.isChecked() else re.IGNORECASE
            try:
                match = re.search(pattern, source[start:], flags)
                if match is None:
                    match = re.search(pattern, source, flags)
                    start = 0
            except re.error as exc:
                self.result_label.setText(f"정규식 오류: {exc}")
                return False
            if match is None:
                self.result_label.setText("찾을 내용이 없습니다.")
                return False
            cursor = self.editor.textCursor()
            cursor.setPosition(start + match.start())
            cursor.setPosition(start + match.end(), QTextCursor.MoveMode.KeepAnchor)
            self.editor.setTextCursor(cursor)
            self.result_label.setText("찾았습니다.")
            return True
        found = self.editor.find(pattern, self._flags())
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(pattern, self._flags())
        self.result_label.setText("찾았습니다." if found else "찾을 내용이 없습니다.")
        return found

    def replace_one(self) -> None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection() and not self.find_next():
            return
        cursor = self.editor.textCursor()
        cursor.insertText(self.replace_edit.text())
        self.find_next()

    def replace_all(self) -> None:
        pattern = self.find_edit.text()
        if not pattern:
            return
        source = self.editor.raw_text()
        flags = 0 if self.case_box.isChecked() else re.IGNORECASE
        if not self.regex_box.isChecked():
            pattern = re.escape(pattern)
            if self.word_box.isChecked():
                pattern = rf"\b{pattern}\b"
        try:
            changed, count = re.subn(pattern, self.replace_edit.text(), source, flags=flags)
        except re.error as exc:
            QMessageBox.warning(self, "정규식 오류", str(exc))
            return
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(changed)
        cursor.endEditBlock()
        self.result_label.setText(f"{count}개를 바꿨습니다.")
