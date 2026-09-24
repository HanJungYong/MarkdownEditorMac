from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from markdowneditor.core.file_io import (
    DocumentError,
    LoadedDocument,
    atomic_write,
    encode_document,
    load_document,
)
from markdowneditor.core.links import LinkReference, inspect_links
from markdowneditor.core.md_actions import (
    EditResult,
    insert_block,
    prefix_lines,
    set_heading,
    wrap_inline,
)
from markdowneditor.core.naming import dated_path, first_available_path
from markdowneditor.core.renderer import RenderResult, render_markdown
from markdowneditor.gui.dialogs import FindReplaceDialog
from markdowneditor.gui.editor import MarkdownEditorWidget
from markdowneditor.gui.fonts import (
    DEFAULT_FONT_SIZE,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    register_pretendard_fonts,
)
from markdowneditor.gui.panels import ProblemsDock
from markdowneditor.gui.preview import PreviewPane
from markdowneditor.gui.toolbar import MarkdownToolbar
from markdowneditor.ui_text import APP_NAME, OPEN_FILTER

DARK_STYLE = """
QMainWindow, QMenuBar, QMenu, QToolBar, QStatusBar, QDockWidget, QDialog {
  background: #17191d;
  color: #edf0f4;
}
QMenuBar::item:selected, QMenu::item:selected { background: #334155; }
QToolBar, QStatusBar { border-color: #343a43; }
QLabel, QCheckBox { color: #edf0f4; }
QToolButton, QPushButton, QComboBox, QLineEdit {
  background: #252a31;
  color: #edf0f4;
  border: 1px solid #4b5563;
  border-radius: 4px;
  padding: 3px 6px;
}
QToolButton:hover, QPushButton:hover { background: #334155; }
QScrollBar { background: #17191d; }
QScrollBar::handle { background: #4b5563; border-radius: 4px; }
"""


class RenderSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class RenderTask(QRunnable):
    def __init__(self, revision: int, source: str, allow_external_images: bool) -> None:
        super().__init__()
        self.revision = revision
        self.source = source
        self.allow_external_images = allow_external_images
        self.signals = RenderSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = render_markdown(self.source, allow_external_images=self.allow_external_images)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(self.revision, str(exc))
        else:
            self.signals.finished.emit(self.revision, result)


class MainWindow(QMainWindow):
    document_opened = Signal(str)
    render_completed = Signal(object)
    sync_scroll_fixed = Signal(object)

    def __init__(
        self,
        initial_path: str | Path | None = None,
        *,
        external_opener: Callable[[QUrl], bool] | None = None,
        date_provider: Callable[[], date] | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.settings = settings or QSettings("OpenAI-Cowork", APP_NAME)
        self.document_data: LoadedDocument | None = None
        self.links: list[LinkReference] = []
        self.session_saved_paths: set[Path] = set()
        self.allow_external_images = False
        self.dark_mode = False
        self.sync_scroll_enabled = False
        self.preview_render_ready = False
        self._pending_preview_source_line = 1.0
        self._syncing_from_preview = False
        self.font_size = DEFAULT_FONT_SIZE
        self.external_opener = external_opener or QDesktopServices.openUrl
        self.date_provider = date_provider or date.today
        self._revision = 0
        self._last_render_result: RenderResult | None = None
        self._find_dialog: FindReplaceDialog | None = None
        self.thread_pool = QThreadPool.globalInstance()

        register_pretendard_fonts()
        self.editor = MarkdownEditorWidget(self)
        self.editor.setEnabled(False)
        self.toolbar = MarkdownToolbar(self)
        self.preview = PreviewPane(self)
        self.preview.set_control_height(self.toolbar.sizeHint().height())
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.toolbar)
        left_layout.addWidget(self.editor)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([700, 700])
        self.setCentralWidget(self.splitter)

        self.problems = ProblemsDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.problems)
        self.problems.hide()
        self.problems.line_requested.connect(self.go_to_line)

        self.path_label = QLabel("파일을 열어 주세요.", self)
        self.format_label = QLabel("", self)
        self.position_label = QLabel("", self)
        self.link_label = QLabel("", self)
        self.render_label = QLabel("", self)
        self.font_decrease_button = QToolButton(self)
        self.font_decrease_button.setObjectName("fontDecreaseButton")
        self.font_decrease_button.setText("−")
        self.font_decrease_button.setToolTip("마크다운 글자 크기 줄이기")
        self.font_size_label = QLabel("", self)
        self.font_size_label.setObjectName("fontSizeLabel")
        self.font_increase_button = QToolButton(self)
        self.font_increase_button.setObjectName("fontIncreaseButton")
        self.font_increase_button.setText("+")
        self.font_increase_button.setToolTip("마크다운 글자 크기 키우기")
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.addWidget(self.path_label, 1)
        for label in (self.format_label, self.position_label, self.link_label, self.render_label):
            status.addPermanentWidget(label)
        status.addPermanentWidget(self.font_decrease_button)
        status.addPermanentWidget(self.font_size_label)
        status.addPermanentWidget(self.font_increase_button)

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(300)
        self.render_timer.timeout.connect(self.start_render)
        self.editor_sync_timer = QTimer(self)
        self.editor_sync_timer.setSingleShot(True)
        self.editor_sync_timer.setInterval(30)
        self.editor_sync_timer.timeout.connect(self._apply_sync_from_editor)
        self.preview_sync_timer = QTimer(self)
        self.preview_sync_timer.setSingleShot(True)
        self.preview_sync_timer.setInterval(30)
        self.preview_sync_timer.timeout.connect(self._apply_sync_from_preview)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._update_position)
        self.editor.document().modificationChanged.connect(self._update_title)
        self.toolbar.command_requested.connect(self.apply_command)
        self.preview.render_completed.connect(self._preview_completed)
        self.preview.link_requested.connect(self.open_link)
        self.preview.message_reported.connect(self.statusBar().showMessage)
        self.editor.font_zoom_requested.connect(self.adjust_font_size)
        self.preview.font_zoom_requested.connect(self.adjust_font_size)
        self.font_decrease_button.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_increase_button.clicked.connect(lambda: self.adjust_font_size(1))
        self.editor.verticalScrollBar().valueChanged.connect(self._sync_from_editor)
        self.preview.scroll_source_line_changed.connect(self._sync_from_preview)
        self.preview.sync_scroll_toggled.connect(self.toggle_sync_scroll)
        self.preview.sync_scroll_fix_requested.connect(self.fix_sync_scroll)

        self._create_actions_and_menus()
        self._restore_settings()
        if initial_path:
            QTimer.singleShot(0, lambda: self.open_document(Path(initial_path)))

    def _create_actions_and_menus(self) -> None:
        file_menu = self.menuBar().addMenu("파일(&F)")
        open_action = QAction("열기(&O)…", self, shortcut=QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_document)
        file_menu.addAction(open_action)
        self.recent_menu = file_menu.addMenu("최근 파일")
        self._rebuild_recent_menu()
        save_action = QAction(
            "저장—날짜 붙여 새 파일(&S)", self, shortcut=QKeySequence.StandardKey.Save
        )
        save_action.triggered.connect(self.save_document)
        file_menu.addAction(save_action)
        save_as_action = QAction(
            "다른 이름으로 저장…", self, shortcut=QKeySequence.StandardKey.SaveAs
        )
        save_as_action.triggered.connect(self.save_as)
        file_menu.addAction(save_as_action)
        location_action = QAction("파일 위치 열기", self)
        location_action.triggered.connect(self.open_file_location)
        file_menu.addAction(location_action)
        file_menu.addSeparator()
        file_menu.addAction("끝내기", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("편집(&E)")
        undo_action = QAction("실행 취소", self, shortcut=QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.editor.undo)
        redo_action = QAction("다시 실행", self, shortcut=QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self.editor.redo)
        edit_menu.addActions([undo_action, redo_action])
        edit_menu.addSeparator()
        for text, slot, shortcut in (
            ("잘라내기", self.editor.cut, QKeySequence.StandardKey.Cut),
            ("복사", self.editor.copy, QKeySequence.StandardKey.Copy),
            ("붙여넣기", self.editor.paste, QKeySequence.StandardKey.Paste),
            ("모두 선택", self.editor.selectAll, QKeySequence.StandardKey.SelectAll),
        ):
            action = QAction(text, self, shortcut=shortcut)
            action.triggered.connect(slot)
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        find_action = QAction("찾기", self, shortcut=QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self.show_find)
        replace_action = QAction("바꾸기", self, shortcut=QKeySequence("Ctrl+H"))
        replace_action.triggered.connect(self.show_replace)
        next_action = QAction("다음 찾기", self, shortcut=QKeySequence("F3"))
        next_action.triggered.connect(lambda: self._find_dialog and self._find_dialog.find_next())
        goto_action = QAction("줄로 이동", self, shortcut=QKeySequence("Ctrl+G"))
        goto_action.triggered.connect(self.ask_go_to_line)
        edit_menu.addActions([find_action, replace_action, next_action, goto_action])
        edit_menu.addSeparator()
        self.indent_action = QAction("들여쓰기", self, checkable=True, checked=True)
        self.indent_action.setToolTip("줄바꿈할 때 현재 줄의 공백 들여쓰기 유지")
        self.indent_action.toggled.connect(self.toggle_auto_indent)
        edit_menu.addAction(self.indent_action)

        format_menu = self.menuBar().addMenu("서식(&O)")
        for action in self.toolbar.actions_by_command.values():
            format_menu.addAction(action)

        view_menu = self.menuBar().addMenu("보기(&V)")
        both_action = QAction("편집+미리보기", self)
        both_action.triggered.connect(lambda: self.set_view_mode("both"))
        editor_action = QAction("편집만", self)
        editor_action.triggered.connect(lambda: self.set_view_mode("editor"))
        preview_action = QAction("미리보기만", self)
        preview_action.triggered.connect(lambda: self.set_view_mode("preview"))
        view_menu.addActions([both_action, editor_action, preview_action])
        wrap_action = QAction("자동 줄바꿈", self, checkable=True, checked=True)
        wrap_action.toggled.connect(self.editor.set_word_wrap)
        view_menu.addAction(wrap_action)
        refresh_action = QAction("미리보기 새로 고침", self, shortcut=QKeySequence("F5"))
        refresh_action.triggered.connect(self.start_render)
        view_menu.addAction(refresh_action)
        external_action = QAction("외부 이미지 표시", self, checkable=True, checked=False)
        external_action.toggled.connect(self.toggle_external_images)
        view_menu.addAction(external_action)
        problem_action = self.problems.toggleViewAction()
        problem_action.setText("연결 문제 패널")
        view_menu.addAction(problem_action)
        view_menu.addSeparator()
        self.dark_mode_action = QAction("다크 모드", self, checkable=True)
        self.dark_mode_action.toggled.connect(self.toggle_dark_mode)
        view_menu.addAction(self.dark_mode_action)
        larger_action = QAction("글자 크게", self, shortcut=QKeySequence("Ctrl++"))
        larger_action.triggered.connect(lambda: self.adjust_font_size(1))
        smaller_action = QAction("글자 작게", self, shortcut=QKeySequence("Ctrl+-"))
        smaller_action.triggered.connect(lambda: self.adjust_font_size(-1))
        view_menu.addActions([larger_action, smaller_action])

        help_menu = self.menuBar().addMenu("도움말(&H)")
        help_action = QAction("사용 설명서", self)
        help_action.triggered.connect(self.open_help)
        about_action = QAction("정보", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addActions([help_action, about_action])

    def _restore_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self.settings.value("window/splitter")
        if splitter:
            self.splitter.restoreState(splitter)
        try:
            size = int(self.settings.value("view/font_size", DEFAULT_FONT_SIZE))
        except (TypeError, ValueError):
            size = DEFAULT_FONT_SIZE
        self.set_font_size(size)
        dark = _setting_bool(self.settings.value("view/dark_mode", False))
        self.dark_mode_action.setChecked(dark)
        self.toggle_dark_mode(dark)
        sync = _setting_bool(self.settings.value("view/sync_scroll", False))
        self.preview.sync_checkbox.setChecked(sync)
        self.toggle_sync_scroll(sync)
        auto_indent = _setting_bool(self.settings.value("edit/auto_indent", True))
        self.indent_action.setChecked(auto_indent)
        self.toggle_auto_indent(auto_indent)

    def _save_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.splitter.saveState())
        self.settings.setValue("view/font_size", self.font_size)
        self.settings.setValue("view/dark_mode", self.dark_mode)
        self.settings.setValue("view/sync_scroll", self.sync_scroll_enabled)
        self.settings.setValue("edit/auto_indent", self.editor.auto_indent_enabled)

    def recent_files(self) -> list[str]:
        value = self.settings.value("recent/files", [])
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    def _remember_recent(self, path: Path) -> None:
        files = [str(path)] + [item for item in self.recent_files() if item != str(path)]
        self.settings.setValue("recent/files", files[:10])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        valid = [item for item in self.recent_files() if Path(item).exists()]
        if not valid:
            empty = self.recent_menu.addAction("최근 파일 없음")
            empty.setEnabled(False)
            return
        for item in valid:
            action = self.recent_menu.addAction(item)
            action.triggered.connect(lambda _checked=False, path=item: self.open_document(path))

    @Slot()
    def choose_document(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "마크다운 파일 열기", "", OPEN_FILTER)
        if path:
            self.open_document(path)

    def open_document(self, path: str | Path) -> bool:
        if not self._confirm_discard_or_save():
            return False
        try:
            document = load_document(path)
        except DocumentError as exc:
            message = str(exc)
            if "확장자" in message:
                answer = QMessageBox.question(self, "확장자 확인", f"{message}\n그래도 열까요?")
                if answer == QMessageBox.StandardButton.Yes:
                    return self._open_with_options(path, allow_unusual_extension=True)
            elif "너무 큽니다" in message:
                answer = QMessageBox.question(self, "큰 파일", f"{message}\n그래도 열까요?")
                if answer == QMessageBox.StandardButton.Yes:
                    return self._open_with_options(path, allow_large=True)
            QMessageBox.critical(self, "파일 열기 실패", message)
            return False
        return self._set_document(document)

    def _open_with_options(self, path: str | Path, **options: bool) -> bool:
        try:
            return self._set_document(load_document(path, **options))
        except DocumentError as exc:
            QMessageBox.critical(self, "파일 열기 실패", str(exc))
            return False

    def _set_document(self, document: LoadedDocument) -> bool:
        self.document_data = document
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self.editor.blockSignals(True)
        self.editor.setPlainText(document.text)
        self.editor.document().setModified(False)
        self.editor.blockSignals(False)
        self.editor.setEnabled(True)
        self.preview.set_document_directory(document.path.parent)
        self._refresh_links()
        self._remember_recent(document.path)
        self._update_title()
        self._update_status()
        self.start_render()
        self.document_opened.emit(str(document.path))
        if document.warnings:
            self.statusBar().showMessage(" ".join(document.warnings), 12000)
        return True

    def _refresh_links(self) -> None:
        if self.document_data is None:
            return
        self.links = inspect_links(self.editor.raw_text(), self.document_data.path)
        self.problems.set_links(self.links)
        self._update_status()

    def _on_text_changed(self) -> None:
        if self.document_data is None:
            return
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self.render_timer.start()
        self._update_status()

    @Slot()
    def start_render(self) -> None:
        if self.document_data is None:
            return
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self._revision += 1
        revision = self._revision
        task = RenderTask(revision, self.editor.raw_text(), self.allow_external_images)
        task.signals.finished.connect(self._renderer_finished)
        task.signals.failed.connect(self._renderer_failed)
        self.thread_pool.start(task)

    @Slot(int, object)
    def _renderer_finished(self, revision: int, result: RenderResult) -> None:
        if revision != self._revision:
            return
        self._last_render_result = result
        self.render_label.setText(f"Python {result.elapsed_ms:.0f}ms")
        self.preview.update_html(result.html, revision, self.editor.blockCount())
        self._refresh_links()

    @Slot(int, str)
    def _renderer_failed(self, revision: int, message: str) -> None:
        if revision == self._revision:
            self.preview_render_ready = False
            self.preview.set_sync_fix_enabled(False)
            self.statusBar().showMessage(f"미리보기 생성 실패: {message}", 10000)

    @Slot(object)
    def _preview_completed(self, stats: object) -> None:
        self.preview_render_ready = True
        self.preview.set_sync_fix_enabled(self.document_data is not None)
        if isinstance(stats, dict):
            table_count = stats.get("tables", 0)
            loaded_images = stats.get("imagesLoaded", 0)
            self.render_label.setText(
                f"{self._last_render_result.elapsed_ms:.0f}ms · "
                f"표 {table_count} · 이미지 {loaded_images}"
                if self._last_render_result
                else "미리보기 완료"
            )
        self.render_completed.emit(stats)
        if self.sync_scroll_enabled:
            self._sync_from_editor()

    def _update_title(self, _modified: bool | None = None) -> None:
        name = self.document_data.path.name if self.document_data else APP_NAME
        marker = " *" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{APP_NAME} - {name}{marker}" if self.document_data else APP_NAME)

    def _update_position(self) -> None:
        cursor = self.editor.textCursor()
        self.position_label.setText(
            f"줄 {cursor.blockNumber() + 1}, 칸 {cursor.positionInBlock() + 1}"
        )

    def _update_status(self) -> None:
        if self.document_data is None:
            return
        document = self.document_data
        self.path_label.setText(str(document.path))
        bom = " · BOM" if document.format.bom else ""
        self.format_label.setText(
            f"{document.format.encoding.upper()}{bom} · {document.format.newline_label}"
        )
        missing = sum(item.status in {"없음", "대상없음", "차단"} for item in self.links)
        self.link_label.setText(f"연결 {len(self.links)} · 문제 {missing}")
        self._update_position()

    def _apply_edit(self, result: EditResult) -> None:
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(result.start)
        cursor.setPosition(result.end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(result.replacement)
        cursor.setPosition(result.selection_start)
        cursor.setPosition(result.selection_end, QTextCursor.MoveMode.KeepAnchor)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    @Slot(str)
    def apply_command(self, command: str) -> None:
        if self.document_data is None:
            return
        text = self.editor.raw_text()
        cursor = self.editor.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        if command == "bold":
            result = wrap_inline(text, start, end, "**", placeholder="굵은 글씨")
        elif command == "italic":
            result = wrap_inline(text, start, end, "*", placeholder="기울임")
        elif command == "strike":
            result = wrap_inline(text, start, end, "~~", placeholder="취소선")
        elif command == "inline_code":
            result = wrap_inline(text, start, end, "`", placeholder="코드")
        elif command.startswith("heading:"):
            result = set_heading(text, start, end, int(command.split(":", 1)[1]))
        elif command == "quote":
            result = prefix_lines(text, start, end, "> ")
        elif command == "bullet":
            result = prefix_lines(text, start, end, "- ")
        elif command == "number":
            result = prefix_lines(text, start, end, "1. ")
        elif command == "task":
            result = prefix_lines(text, start, end, "- [ ] ")
        elif command == "link":
            selected = text[start:end]
            label, ok = QInputDialog.getText(self, "링크", "표시할 글자", text=selected)
            if not ok:
                return
            target, ok = QInputDialog.getText(self, "링크", "주소 또는 파일 경로")
            if not ok or not target:
                return
            result = insert_block(start, end, f"[{label or target}]({target})")
        elif command == "image":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "이미지 선택",
                str(self.document_data.path.parent),
                "이미지 (*.png *.jpg *.jpeg *.gif *.svg *.webp *.bmp)",
            )
            if not path:
                return
            relative = os.path.relpath(path, self.document_data.path.parent).replace("\\", "/")
            target = quote(relative, safe="/._-")
            result = insert_block(start, end, f"![{Path(path).stem}]({target})")
        elif command == "table":
            result = insert_block(
                start,
                end,
                "\n| 열 1 | 열 2 | 열 3 |\n|---|---|---|\n|  |  |  |\n|  |  |  |\n",
            )
        elif command == "code_block":
            language, ok = QInputDialog.getText(self, "코드 블록", "언어(선택)")
            if not ok:
                return
            selected = text[start:end]
            result = insert_block(start, end, f"\n```{language}\n{selected}\n```\n")
        elif command == "mermaid":
            result = insert_block(
                start,
                end,
                "\n```mermaid\n"
                "flowchart TD\n"
                "    A[시작] --> B{조건}\n"
                "    B -- 예 --> C[처리]\n"
                "    B -- 아니오 --> D[끝]\n"
                "```\n",
            )
        elif command == "hr":
            result = insert_block(start, end, "\n---\n")
        else:
            return
        self._apply_edit(result)

    def show_find(self) -> None:
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(self.editor, self)
        self._find_dialog.replace_edit.setVisible(False)
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.find_edit.setFocus()

    def show_replace(self) -> None:
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(self.editor, self)
        self._find_dialog.replace_edit.setVisible(True)
        self._find_dialog.show()
        self._find_dialog.raise_()

    def ask_go_to_line(self) -> None:
        line, ok = QInputDialog.getInt(
            self,
            "줄로 이동",
            "줄 번호",
            self.editor.textCursor().blockNumber() + 1,
            1,
            max(1, self.editor.blockCount()),
        )
        if ok:
            self.go_to_line(line)

    @Slot(int)
    def go_to_line(self, line: int) -> None:
        block = self.editor.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            cursor = QTextCursor(block)
            self.editor.setTextCursor(cursor)
            self.editor.centerCursor()
            self.editor.setFocus()

    def set_view_mode(self, mode: str) -> None:
        self.splitter.widget(0).setVisible(mode in {"both", "editor"})
        self.preview.setVisible(mode in {"both", "preview"})

    @Slot(bool)
    def toggle_external_images(self, enabled: bool) -> None:
        self.allow_external_images = enabled
        self.preview.set_external_images(enabled)
        self.start_render()

    @Slot(bool)
    def toggle_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        self.setStyleSheet(DARK_STYLE if enabled else "")
        self.editor.set_dark_mode(enabled)
        self.preview.set_dark_mode(enabled)
        self.settings.setValue("view/dark_mode", enabled)
        if self.document_data is not None:
            self.start_render()

    @Slot(int)
    def adjust_font_size(self, steps: int) -> None:
        self.set_font_size(self.font_size + steps)

    def set_font_size(self, size: int) -> None:
        bounded = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))
        self.font_size = bounded
        self.editor.set_markdown_font_size(bounded)
        self.preview.set_markdown_font_size(bounded)
        self.font_size_label.setText(f"글자 {bounded}")
        self.font_decrease_button.setEnabled(bounded > MIN_FONT_SIZE)
        self.font_increase_button.setEnabled(bounded < MAX_FONT_SIZE)
        self.settings.setValue("view/font_size", bounded)

    @Slot(bool)
    def toggle_sync_scroll(self, enabled: bool) -> None:
        self.sync_scroll_enabled = enabled
        self.settings.setValue("view/sync_scroll", enabled)
        if enabled:
            QTimer.singleShot(0, self._sync_from_editor)

    @Slot(bool)
    def toggle_auto_indent(self, enabled: bool) -> None:
        self.editor.set_auto_indent(enabled)
        self.settings.setValue("edit/auto_indent", enabled)

    @Slot(int)
    def _sync_from_editor(self, _value: int = 0) -> None:
        if (
            not self.sync_scroll_enabled
            or not self.preview_render_ready
            or self._syncing_from_preview
        ):
            return
        self.editor_sync_timer.start()

    @Slot()
    def _apply_sync_from_editor(self) -> None:
        if not self.sync_scroll_enabled or not self.preview_render_ready:
            return
        scrollbar = self.editor.verticalScrollBar()
        maximum = scrollbar.maximum()
        ratio = scrollbar.value() / maximum if maximum else 0.0
        self.preview.align_to_source_line(
            self.editor.first_visible_source_line(),
            self.editor.blockCount(),
            ratio,
        )

    @Slot(float)
    def _sync_from_preview(self, line: float) -> None:
        if not self.sync_scroll_enabled or not self.preview_render_ready:
            return
        self._pending_preview_source_line = line
        self.preview_sync_timer.start()

    @Slot()
    def _apply_sync_from_preview(self) -> None:
        if not self.sync_scroll_enabled or not self.preview_render_ready:
            return
        self._syncing_from_preview = True
        try:
            self.editor.scroll_source_line_to_top(self._pending_preview_source_line)
        finally:
            self._syncing_from_preview = False

    @Slot()
    def fix_sync_scroll(self) -> None:
        if self.document_data is None or not self.preview_render_ready:
            self.statusBar().showMessage("미리보기 렌더링이 끝난 후 위치를 맞출 수 있습니다.", 5000)
            return
        scrollbar = self.editor.verticalScrollBar()
        maximum = scrollbar.maximum()
        fallback_ratio = scrollbar.value() / maximum if maximum else 0.0
        self.preview.set_sync_fix_enabled(False)
        self.preview.align_to_source_line(
            self.editor.first_visible_source_line(),
            self.editor.blockCount(),
            fallback_ratio,
            self._sync_fix_completed,
        )

    def _sync_fix_completed(self, result: object) -> None:
        self.preview.set_sync_fix_enabled(
            self.document_data is not None and self.preview_render_ready
        )
        if isinstance(result, dict) and result.get("ok"):
            self.statusBar().showMessage("편집기 기준으로 미리보기 위치를 맞췄습니다.", 5000)
        else:
            self.statusBar().showMessage("미리보기 위치를 맞추지 못했습니다.", 5000)
        self.sync_scroll_fixed.emit(result)

    def _choose_save_target(self) -> Path | None:
        assert self.document_data is not None
        current = self.document_data.path
        candidate = dated_path(current, self.date_provider())
        if current in self.session_saved_paths and current == candidate:
            return current
        if not candidate.exists():
            return candidate
        box = QMessageBox(self)
        box.setWindowTitle("파일이 이미 있습니다")
        box.setText(f"다음 파일이 이미 있습니다.\n{candidate.name}")
        overwrite = box.addButton("덮어쓰기", QMessageBox.ButtonRole.AcceptRole)
        numbered = box.addButton("번호 붙여 저장", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is overwrite:
            return candidate
        if box.clickedButton() is numbered:
            return first_available_path(candidate)
        return None

    @Slot()
    def save_document(self) -> bool:
        if self.document_data is None:
            return False
        target = self._choose_save_target()
        return False if target is None else self.save_to_path(target)

    def save_to_path(self, target: str | Path) -> bool:
        if self.document_data is None:
            return False
        target_path = Path(target).resolve()
        try:
            payload = encode_document(
                self.document_data,
                self.editor.raw_text(),
                edited=self.editor.document().isModified(),
            )
        except DocumentError as exc:
            if "표현할 수 없는" not in str(exc):
                QMessageBox.critical(self, "저장 실패", str(exc))
                return False
            answer = QMessageBox.question(
                self,
                "UTF-8로 저장",
                f"{exc}\nUTF-8로 저장할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            normalized = self.editor.raw_text().replace("\n", self.document_data.format.newline)
            payload = normalized.encode("utf-8")
        try:
            atomic_write(target_path, payload)
            new_document = load_document(
                target_path, allow_unusual_extension=True, allow_large=True
            )
        except DocumentError as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return False
        self.document_data = new_document
        self.session_saved_paths.add(target_path)
        self.editor.document().setModified(False)
        self.preview.set_document_directory(target_path.parent)
        self._remember_recent(target_path)
        self._refresh_links()
        self._update_title()
        self.statusBar().showMessage(f"저장했습니다: {target_path.name}", 8000)
        return True

    @Slot()
    def save_as(self) -> bool:
        if self.document_data is None:
            return False
        suggested = dated_path(self.document_data.path)
        path, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", str(suggested), OPEN_FILTER
        )
        if not path:
            return False
        target = Path(path).resolve()
        if target == self.document_data.path:
            answer = QMessageBox.warning(
                self,
                "원본 덮어쓰기",
                "원본 파일을 덮어씁니다. 계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        elif target.parent != self.document_data.path.parent:
            broken = sum(1 for item in self.links if item.status == "정상" and item.resolved)
            answer = QMessageBox.warning(
                self,
                "상대 링크 확인",
                f"다른 폴더에 저장하면 최대 {broken}개의 상대 링크가 끊길 수 있습니다. 계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return self.save_to_path(target)

    def _confirm_discard_or_save(self) -> bool:
        if self.document_data is None or not self.editor.document().isModified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("저장하지 않은 변경")
        box.setText("변경 내용을 저장할까요?")
        save_button = box.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("저장 안 함", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save_button:
            return self.save_document()
        return box.clickedButton() is discard_button

    @Slot(str)
    def open_link(self, target: str) -> None:
        if self.document_data is None:
            return
        parsed = urlparse(target)
        if parsed.scheme.lower() in {"javascript", "vbscript"}:
            self.statusBar().showMessage("안전을 위해 위험한 링크를 차단했습니다.", 8000)
            return
        if parsed.scheme.lower() in {"http", "https", "mailto"}:
            self.external_opener(QUrl(target))
            return
        clean = unquote(parsed.path).replace("/", os.sep)
        path = Path(clean) if re_drive_path(clean) else (self.document_data.path.parent / clean)
        path = path.resolve()
        if not path.exists():
            QMessageBox.warning(self, "파일 없음", f"파일을 찾을 수 없습니다:\n{path}")
            return
        if path.suffix.lower() in {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}:
            self.open_document(path)
        else:
            self.external_opener(QUrl.fromLocalFile(str(path)))

    def open_file_location(self) -> None:
        if self.document_data:
            self.external_opener(QUrl.fromLocalFile(str(self.document_data.path.parent)))

    def open_help(self) -> None:
        path = Path(__file__).resolve().parents[3] / "docs" / "사용설명서.md"
        if path.exists():
            self.open_document(path)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "MarkdownEditor 정보",
            "MarkdownEditor 0.1.0\n\n"
            "Python · PySide6 · QtWebEngine · markdown-it-py · Mermaid\n"
            "자세한 라이선스는 THIRD_PARTY_NOTICES.md를 참고하세요.",
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_document(url.toLocalFile())
                event.acceptProposedAction()
                return

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._confirm_discard_or_save():
            self._save_settings()
            self.render_timer.stop()
            self.editor_sync_timer.stop()
            self.preview_sync_timer.stop()
            self.thread_pool.waitForDone(5000)
            self.preview.shutdown()
            event.accept()
        else:
            event.ignore()


def re_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in {"\\", "/"}


def _setting_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
