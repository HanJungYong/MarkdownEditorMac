from __future__ import annotations

import os
import weakref
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
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
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
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
from markdowneditor.core.links import LinkReference
from markdowneditor.core.md_actions import (
    EditResult,
    insert_block,
    prefix_lines,
    set_heading,
    wrap_inline,
)
from markdowneditor.core.naming import dated_path, first_available_path
from markdowneditor.core.opening import (
    DropPlan,
    OpenSummary,
    document_key,
    is_markdown_path,
    same_document,
)
from markdowneditor.core.view_settings import (
    DEFAULT_LETTER_SPACING,
    MAX_LETTER_SPACING,
    MIN_LETTER_SPACING,
    clamp_letter_spacing,
    parse_letter_spacing,
    step_letter_spacing,
)
from markdowneditor.gui.dialogs import FindReplaceDialog
from markdowneditor.gui.document_session import DocumentSession, ViewState
from markdowneditor.gui.editor import MarkdownEditorWidget
from markdowneditor.gui.file_drop import FileDropController
from markdowneditor.gui.fonts import (
    DEFAULT_FONT_SIZE,
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
    register_pretendard_fonts,
)
from markdowneditor.gui.panels import ProblemsDock
from markdowneditor.gui.preview import (
    PreviewPane,
    release_shared_network_guard,
    shared_network_guard,
)
from markdowneditor.gui.toolbar import MarkdownActions, MarkdownToolbar
from markdowneditor.ui_text import (
    APP_NAME,
    CLOSE_TAB,
    LETTER_SPACING_LARGER,
    LETTER_SPACING_SMALLER,
    NO_DOCUMENT,
    OPEN_FILTER,
)

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
QTabWidget::pane { border: 0; border-top: 1px solid #343a43; }
QListWidget { background: #1f2329; color: #edf0f4; border: 1px solid #343a43; }
QListWidget::item:selected { background: #334155; }
"""

VIEW_MODES = {"both": "편집+미리보기", "editor": "편집만", "preview": "미리보기만"}

# The active tab is marked by a thick accent bar and bold text, not by colour alone.
TAB_STYLE_LIGHT = """
QTabBar::tab {
  background: palette(button);
  color: palette(button-text);
  border: 1px solid palette(mid);
  border-bottom: 0;
  border-top: 3px solid transparent;
  padding: 5px 12px;
}
QTabBar::tab:selected {
  background: palette(base);
  border-top: 3px solid #2563eb;
  font-weight: bold;
}
QTabBar::tab:!selected:hover { background: palette(midlight); }
"""
TAB_STYLE_DARK = """
QTabBar::tab {
  background: #252a31;
  color: #c9d1dc;
  border: 1px solid #343a43;
  border-bottom: 0;
  border-top: 3px solid transparent;
  padding: 5px 12px;
}
QTabBar::tab:selected {
  background: #3b4656;
  color: #ffffff;
  border-top: 3px solid #60a5fa;
  font-weight: bold;
}
QTabBar::tab:!selected:hover { background: #334155; }
"""

_live_windows: weakref.WeakSet[MainWindow] = weakref.WeakSet()


class MainWindow(QMainWindow):
    document_opened = Signal(str)
    render_completed = Signal(object)
    sync_scroll_fixed = Signal(object)
    active_session_changed = Signal(object)

    def __init__(
        self,
        initial_path: str | Path | Sequence[str | Path] | None = None,
        *,
        external_opener: Callable[[QUrl], bool] | None = None,
        date_provider: Callable[[], date] | None = None,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        _live_windows.add(self)
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.settings = settings or QSettings("OpenAI-Cowork", APP_NAME)
        self.session_saved_paths: set[Path] = set()
        self.allow_external_images = False
        self.dark_mode = False
        self.sync_scroll_enabled = False
        self.auto_indent_enabled = True
        self.word_wrap_enabled = True
        self.view_mode = "both"
        self.font_size = DEFAULT_FONT_SIZE
        self.letter_spacing = DEFAULT_LETTER_SPACING
        self.external_opener = external_opener or QDesktopServices.openUrl
        self.date_provider = date_provider or date.today
        self.thread_pool = QThreadPool.globalInstance()
        self._sessions: list[DocumentSession] = []
        self._find_dialog: FindReplaceDialog | None = None
        self._saved_splitter_state = None
        self._shut_down = False

        register_pretendard_fonts()
        shared_network_guard().allow_external_images = self.allow_external_images
        self.markdown_actions = MarkdownActions(self)
        self.markdown_actions.command_requested.connect(self.apply_command)
        self.drop_controller = FileDropController(
            self.handle_drop, self, on_reject=self._explain_rejected_drop
        )

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        tab_bar = self.tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._show_tab_context_menu)
        tab_bar.installEventFilter(self)  # middle-click closes a tab
        self.welcome = self._create_welcome_page()
        self.central_stack = QStackedWidget(self)
        self.central_stack.addWidget(self.welcome)
        self.central_stack.addWidget(self.tabs)
        self.setCentralWidget(self.central_stack)

        self.problems = ProblemsDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.problems)
        self.problems.hide()
        self.problems.line_requested.connect(self.go_to_line)

        self._create_status_bar()
        self._create_actions_and_menus()
        self._restore_settings()
        self._update_document_actions()
        initial_paths = _as_path_list(initial_path)
        if initial_paths:
            QTimer.singleShot(0, self, lambda: self.open_paths(initial_paths, origin="cli"))

    # ----- construction -------------------------------------------------------------------

    def _create_welcome_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(12)
        title = QLabel(NO_DOCUMENT, page)
        title.setObjectName("welcomeTitle")
        title.setWordWrap(True)
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        title.setFont(font)
        layout.addWidget(title)
        open_button = QPushButton("열기…", page)
        open_button.setObjectName("welcomeOpenButton")
        open_button.clicked.connect(self.choose_document)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel("최근 파일", page))
        self.welcome_recent = QListWidget(page)
        self.welcome_recent.setObjectName("welcomeRecentList")
        self.welcome_recent.itemActivated.connect(self._open_recent_item)
        self.welcome_recent.itemClicked.connect(self._open_recent_item)
        layout.addWidget(self.welcome_recent, 1)
        return page

    @Slot(str)
    def _on_status_message_changed(self, text: str) -> None:
        # QStatusBar hides the path label only implicitly while a temporary message is shown,
        # and any re-layout (e.g. a theme change) re-shows it under the message. Hiding it
        # explicitly keeps the two texts from overlapping.
        self.path_label.setVisible(not text)

    def _apply_tab_style(self) -> None:
        self.tabs.tabBar().setStyleSheet(TAB_STYLE_DARK if self.dark_mode else TAB_STYLE_LIGHT)

    def _create_status_bar(self) -> None:
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
        self.letter_spacing_label = QLabel("", self)
        self.letter_spacing_label.setObjectName("letterSpacingLabel")
        self.letter_spacing_label.setToolTip("편집기 글간격 (보기 > 글간격 크게/작게)")
        status = QStatusBar(self)
        self.setStatusBar(status)
        status.addWidget(self.path_label, 1)
        for label in (self.format_label, self.position_label, self.link_label, self.render_label):
            status.addPermanentWidget(label)
        status.addPermanentWidget(self.font_decrease_button)
        status.addPermanentWidget(self.font_size_label)
        status.addPermanentWidget(self.font_increase_button)
        status.addPermanentWidget(self.letter_spacing_label)
        status.messageChanged.connect(self._on_status_message_changed)
        self.font_decrease_button.clicked.connect(lambda: self.adjust_font_size(-1))
        self.font_increase_button.clicked.connect(lambda: self.adjust_font_size(1))

    def _create_actions_and_menus(self) -> None:
        self._document_actions: list[QAction] = []

        def document_action(action: QAction) -> QAction:
            self._document_actions.append(action)
            return action

        file_menu = self.menuBar().addMenu("파일(&F)")
        open_action = QAction("열기(&O)…", self, shortcut=QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_document)
        file_menu.addAction(open_action)
        self.recent_menu = file_menu.addMenu("최근 파일")
        self._rebuild_recent_menu()
        save_action = document_action(
            QAction("저장—날짜 붙여 새 파일(&S)", self, shortcut=QKeySequence.StandardKey.Save)
        )
        save_action.triggered.connect(self.save_document)
        file_menu.addAction(save_action)
        save_as_action = document_action(
            QAction("다른 이름으로 저장…", self, shortcut=QKeySequence.StandardKey.SaveAs)
        )
        save_as_action.triggered.connect(self.save_as)
        file_menu.addAction(save_as_action)
        location_action = document_action(QAction("파일 위치 열기", self))
        location_action.triggered.connect(self.open_file_location)
        file_menu.addAction(location_action)
        file_menu.addSeparator()
        self.close_tab_action = document_action(QAction(CLOSE_TAB, self))
        # setShortcuts(StandardKey) binds every platform key (Windows: Ctrl+W and Ctrl+F4);
        # the constructor's shortcut= argument would bind only the first one.
        self.close_tab_action.setShortcuts(QKeySequence.StandardKey.Close)
        self.close_tab_action.triggered.connect(self.close_active_tab)
        file_menu.addAction(self.close_tab_action)
        self.close_others_action = document_action(QAction("다른 탭 닫기", self))
        self.close_others_action.triggered.connect(
            lambda _checked=False: self.close_other_sessions(self.active_session)
        )
        self.close_all_action = document_action(QAction("모든 탭 닫기", self))
        self.close_all_action.triggered.connect(lambda _checked=False: self.close_all_sessions())
        file_menu.addActions([self.close_others_action, self.close_all_action])
        file_menu.addSeparator()
        file_menu.addAction("끝내기", self.close, QKeySequence.StandardKey.Quit)

        edit_menu = self.menuBar().addMenu("편집(&E)")
        for text, method, shortcut in (
            ("실행 취소", "undo", QKeySequence.StandardKey.Undo),
            ("다시 실행", "redo", QKeySequence.StandardKey.Redo),
            (None, None, None),
            ("잘라내기", "cut", QKeySequence.StandardKey.Cut),
            ("복사", "copy", QKeySequence.StandardKey.Copy),
            ("붙여넣기", "paste", QKeySequence.StandardKey.Paste),
            ("모두 선택", "selectAll", QKeySequence.StandardKey.SelectAll),
        ):
            if text is None:
                edit_menu.addSeparator()
                continue
            action = document_action(QAction(text, self, shortcut=shortcut))
            # Resolve the editor when the action runs, never when the menu is built.
            action.triggered.connect(lambda _checked=False, name=method: self._editor_call(name))
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        find_action = document_action(QAction("찾기", self, shortcut=QKeySequence.StandardKey.Find))
        find_action.triggered.connect(self.show_find)
        replace_action = document_action(QAction("바꾸기", self, shortcut=QKeySequence("Ctrl+H")))
        replace_action.triggered.connect(self.show_replace)
        next_action = document_action(QAction("다음 찾기", self, shortcut=QKeySequence("F3")))
        next_action.triggered.connect(self.find_next)
        goto_action = document_action(QAction("줄로 이동", self, shortcut=QKeySequence("Ctrl+G")))
        goto_action.triggered.connect(self.ask_go_to_line)
        edit_menu.addActions([find_action, replace_action, next_action, goto_action])
        edit_menu.addSeparator()
        self.indent_action = QAction("들여쓰기", self, checkable=True, checked=True)
        self.indent_action.setToolTip("줄바꿈할 때 현재 줄의 공백 들여쓰기 유지")
        self.indent_action.toggled.connect(self.toggle_auto_indent)
        edit_menu.addAction(self.indent_action)

        format_menu = self.menuBar().addMenu("서식(&O)")
        for action in self.markdown_actions.actions_by_command.values():
            format_menu.addAction(action)

        view_menu = self.menuBar().addMenu("보기(&V)")
        self.view_mode_group = QActionGroup(self)
        self.view_mode_group.setExclusive(True)
        self.view_mode_actions: dict[str, QAction] = {}
        for mode, text in VIEW_MODES.items():
            action = QAction(text, self, checkable=True)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_view_mode(value))
            self.view_mode_group.addAction(action)
            self.view_mode_actions[mode] = action
            view_menu.addAction(action)
        self.view_mode_actions["both"].setChecked(True)
        self.wrap_action = QAction("자동 줄바꿈", self, checkable=True, checked=True)
        self.wrap_action.toggled.connect(self.toggle_word_wrap)
        view_menu.addAction(self.wrap_action)
        refresh_action = document_action(
            QAction("미리보기 새로 고침", self, shortcut=QKeySequence("F5"))
        )
        refresh_action.triggered.connect(self.start_render)
        view_menu.addAction(refresh_action)
        self.external_action = QAction("외부 이미지 표시", self, checkable=True, checked=False)
        self.external_action.toggled.connect(self.toggle_external_images)
        view_menu.addAction(self.external_action)
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
        self.letter_spacing_larger_action = QAction(LETTER_SPACING_LARGER, self)
        self.letter_spacing_larger_action.setToolTip("편집기 글자 사이 간격을 5%씩 넓힙니다.")
        self.letter_spacing_larger_action.triggered.connect(lambda: self.adjust_letter_spacing(1))
        self.letter_spacing_smaller_action = QAction(LETTER_SPACING_SMALLER, self)
        self.letter_spacing_smaller_action.setToolTip("편집기 글자 사이 간격을 5%씩 좁힙니다.")
        self.letter_spacing_smaller_action.triggered.connect(lambda: self.adjust_letter_spacing(-1))
        self.letter_spacing_reset_action = QAction("글간격 기본값", self)
        self.letter_spacing_reset_action.setToolTip("편집기 글간격을 기본값 100%로 되돌립니다.")
        self.letter_spacing_reset_action.triggered.connect(
            lambda _checked=False: self.set_letter_spacing(DEFAULT_LETTER_SPACING)
        )
        view_menu.addActions(
            [
                self.letter_spacing_larger_action,
                self.letter_spacing_smaller_action,
                self.letter_spacing_reset_action,
            ]
        )

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
        self._saved_splitter_state = self.settings.value("window/splitter")
        try:
            size = int(self.settings.value("view/font_size", DEFAULT_FONT_SIZE))
        except (TypeError, ValueError):
            size = DEFAULT_FONT_SIZE
        self.set_font_size(size)
        self.set_letter_spacing(
            parse_letter_spacing(self.settings.value("view/letter_spacing")), announce=False
        )
        dark = _setting_bool(self.settings.value("view/dark_mode", False))
        self.dark_mode_action.setChecked(dark)
        self.toggle_dark_mode(dark)
        sync = _setting_bool(self.settings.value("view/sync_scroll", False))
        self.toggle_sync_scroll(sync)
        auto_indent = _setting_bool(self.settings.value("edit/auto_indent", True))
        self.indent_action.setChecked(auto_indent)
        self.toggle_auto_indent(auto_indent)
        word_wrap = _setting_bool(self.settings.value("view/word_wrap", True))
        self.wrap_action.setChecked(word_wrap)
        self.toggle_word_wrap(word_wrap)
        mode = str(self.settings.value("view/mode", "both"))
        self.set_view_mode(mode if mode in VIEW_MODES else "both")

    def _save_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        session = self.active_session
        if session is not None:
            self.settings.setValue("window/splitter", session.splitter.saveState())
        self.settings.setValue("view/font_size", self.font_size)
        self.settings.setValue("view/letter_spacing", self.letter_spacing)
        self.settings.setValue("view/dark_mode", self.dark_mode)
        self.settings.setValue("view/sync_scroll", self.sync_scroll_enabled)
        self.settings.setValue("edit/auto_indent", self.auto_indent_enabled)
        self.settings.setValue("view/word_wrap", self.word_wrap_enabled)
        self.settings.setValue("view/mode", self.view_mode)

    # ----- active document (read-only compatibility properties) ----------------------------

    @property
    def sessions(self) -> tuple[DocumentSession, ...]:
        return tuple(self._sessions)

    @property
    def active_session(self) -> DocumentSession | None:
        return self._session_for_page(self.tabs.currentWidget())

    @property
    def editor(self) -> MarkdownEditorWidget | None:
        session = self.active_session
        return session.editor if session else None

    @property
    def preview(self) -> PreviewPane | None:
        session = self.active_session
        return session.preview if session else None

    @property
    def toolbar(self) -> MarkdownToolbar | None:
        session = self.active_session
        return session.toolbar if session else None

    @property
    def document_data(self) -> LoadedDocument | None:
        session = self.active_session
        return session.document if session else None

    @property
    def links(self) -> list[LinkReference]:
        session = self.active_session
        return session.links if session else []

    @property
    def preview_render_ready(self) -> bool:
        session = self.active_session
        return bool(session and session.preview_render_ready)

    def _session_for_page(self, page: QWidget | None) -> DocumentSession | None:
        if page is None:
            return None
        for session in self._sessions:
            if session.page is page:
                return session
        return None

    def find_session(self, path: str | Path) -> DocumentSession | None:
        key = document_key(path)
        for session in self._sessions:
            if session.key == key:
                return session
        for session in self._sessions:
            if same_document(session.path, path):
                return session
        return None

    def _is_open_elsewhere(self, path: str | Path, current: DocumentSession | None) -> bool:
        owner = self.find_session(path)
        return owner is not None and owner is not current

    # ----- sessions and tabs ----------------------------------------------------------------

    def _view_state(self) -> ViewState:
        return ViewState(
            dark_mode=self.dark_mode,
            font_size=self.font_size,
            letter_spacing=self.letter_spacing,
            auto_indent=self.auto_indent_enabled,
            word_wrap=self.word_wrap_enabled,
            allow_external_images=self.allow_external_images,
            sync_scroll=self.sync_scroll_enabled,
            view_mode=self.view_mode,
        )

    def _create_session(self, document: LoadedDocument) -> DocumentSession:
        session = DocumentSession(
            document,
            actions=self.markdown_actions,
            thread_pool=self.thread_pool,
            state=self._view_state(),
            parent=self,
        )
        current = self.active_session
        if current is not None:
            session.splitter.setSizes(current.splitter.sizes())
        elif self._saved_splitter_state:
            session.splitter.restoreState(self._saved_splitter_state)
        session.modification_changed.connect(
            lambda _modified, s=session: self._on_session_modified(s)
        )
        session.render_completed.connect(
            lambda stats, s=session: self._on_session_rendered(s, stats)
        )
        session.render_status_changed.connect(
            lambda text, s=session: self._if_active(s, lambda: self.render_label.setText(text))
        )
        session.links_changed.connect(lambda s=session: self._if_active(s, self._update_links_view))
        session.status_changed.connect(lambda s=session: self._if_active(s, self._update_status))
        session.status_message.connect(
            lambda message, timeout, s=session: self._if_active(
                s, lambda: self.statusBar().showMessage(message, timeout)
            )
        )
        session.link_requested.connect(lambda target, s=session: self._open_link_from(s, target))
        session.sync_scroll_toggled.connect(self.toggle_sync_scroll)
        session.sync_scroll_fixed.connect(
            lambda result, s=session: self._if_active(
                s, lambda: self.sync_scroll_fixed.emit(result)
            )
        )
        session.font_zoom_requested.connect(self.adjust_font_size)
        self.drop_controller.watch(session.editor, text_fallback=True)
        self.drop_controller.watch(session.editor.viewport(), text_fallback=True)
        self.drop_controller.watch_web_view(session.preview.view)
        self._sessions.append(session)
        index = self.tabs.addTab(session.page, document.path.name)
        self.tabs.setTabToolTip(index, str(document.path))
        self.central_stack.setCurrentWidget(self.tabs)
        self._refresh_tab_titles()
        self._update_document_actions()
        return session

    def _if_active(self, session: DocumentSession, callback: Callable[[], object]) -> None:
        if session is self.active_session and not session.closed:
            callback()

    def activate_session(self, session: DocumentSession) -> None:
        if session in self._sessions:
            self.tabs.setCurrentWidget(session.page)
            session.activate()

    @Slot(int)
    def _on_current_tab_changed(self, _index: int) -> None:
        session = self.active_session
        if session is not None:
            session.activate()
            if self._find_dialog is not None:
                self._find_dialog.editor = session.editor
            self.render_label.setText(session.render_text)
        elif self._find_dialog is not None:
            self._find_dialog.hide()
        self._update_title()
        self._update_status()
        self._update_links_view()
        self._update_document_actions()
        self.active_session_changed.emit(session)

    def _on_session_modified(self, session: DocumentSession) -> None:
        self._refresh_tab_titles()
        if session is self.active_session:
            self._update_title()

    def _on_session_rendered(self, session: DocumentSession, stats: object) -> None:
        if session is self.active_session:
            self.render_completed.emit(stats)

    def tab_title(self, session: DocumentSession) -> str:
        index = self.tabs.indexOf(session.page)
        return self.tabs.tabText(index) if index >= 0 else ""

    def _refresh_tab_titles(self) -> None:
        names: dict[str, int] = {}
        for session in self._sessions:
            key = session.path.name.casefold()
            names[key] = names.get(key, 0) + 1
        for session in self._sessions:
            index = self.tabs.indexOf(session.page)
            if index < 0:
                continue
            title = session.path.name
            if names[title.casefold()] > 1:
                # Same file name in different folders: show the parent folder as well.
                title = f"{title} — {session.path.parent.name or session.path.parent}"
            if session.is_modified():
                title += " *"
            self.tabs.setTabText(index, title)
            self.tabs.setTabToolTip(index, str(session.path))

    def _update_title(self, _modified: bool | None = None) -> None:
        session = self.active_session
        if session is None:
            self.setWindowTitle(APP_NAME)
            return
        marker = " *" if session.is_modified() else ""
        self.setWindowTitle(f"{APP_NAME} - {session.path.name}{marker}")

    def _update_position(self) -> None:
        editor = self.editor
        if editor is None:
            self.position_label.setText("")
            return
        cursor = editor.textCursor()
        self.position_label.setText(
            f"줄 {cursor.blockNumber() + 1}, 칸 {cursor.positionInBlock() + 1}"
        )

    def _update_status(self) -> None:
        session = self.active_session
        if session is None:
            self.path_label.setText("파일을 열어 주세요.")
            for label in (self.format_label, self.position_label, self.link_label):
                label.setText("")
            self.render_label.setText("")
            return
        document = session.document
        self.path_label.setText(str(document.path))
        bom = " · BOM" if document.format.bom else ""
        self.format_label.setText(
            f"{document.format.encoding.upper()}{bom} · {document.format.newline_label}"
        )
        missing = sum(item.status in {"없음", "대상없음", "차단"} for item in session.links)
        self.link_label.setText(f"연결 {len(session.links)} · 문제 {missing}")
        self._update_position()

    def _update_links_view(self) -> None:
        session = self.active_session
        self.problems.set_links(session.links if session else [])
        self._update_status()

    def _update_document_actions(self) -> None:
        has_document = self.active_session is not None
        for action in self._document_actions:
            action.setEnabled(has_document)
        self.markdown_actions.set_enabled(has_document)
        self.central_stack.setCurrentWidget(self.tabs if self._sessions else self.welcome)
        if not self._sessions:
            self._rebuild_welcome_recent()

    # ----- opening files ----------------------------------------------------------------------

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
        for item in valid:
            action = self.recent_menu.addAction(item)
            action.triggered.connect(
                lambda _checked=False, path=item: self.open_paths([path], origin="recent")
            )
        if hasattr(self, "welcome_recent"):
            self._rebuild_welcome_recent()

    def _rebuild_welcome_recent(self) -> None:
        self.welcome_recent.clear()
        for item in (entry for entry in self.recent_files() if Path(entry).exists()):
            list_item = QListWidgetItem(Path(item).name)
            list_item.setToolTip(item)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.welcome_recent.addItem(list_item)

    def _open_recent_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_paths([path], origin="recent")

    @Slot()
    def choose_document(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "마크다운 파일 열기", "", OPEN_FILTER)
        if paths:
            self.open_paths(paths, origin="menu")

    def open_document(self, path: str | Path) -> bool:
        """Open one file in a new tab (or activate its tab). Kept for callers and tests."""
        return self.open_paths([path], origin="menu").any_document

    def open_paths(
        self,
        paths: Iterable[str | Path],
        *,
        origin: str = "menu",
        skipped: Iterable[tuple[str, str]] = (),
    ) -> OpenSummary:
        """Common entry for menu, recent files, command line, links, help and drops."""
        summary = OpenSummary(skipped=list(skipped))
        target: DocumentSession | None = None
        for raw in paths:
            path = Path(raw)
            existing = self.find_session(path)
            if existing is not None:
                summary.already_open.append(existing.path)
                target = existing
                continue
            document = self._load_for_open(path, origin, summary)
            if document is None:
                continue
            existing = self.find_session(document.path)
            if existing is not None:
                summary.already_open.append(existing.path)
                target = existing
                continue
            target = self._create_session(document)
            summary.opened.append(document.path)
            self._remember_recent(document.path)
            self.document_opened.emit(str(document.path))
        if target is not None:
            self.activate_session(target)
        self._report_open_summary(summary, origin)
        return summary

    def _load_for_open(
        self, path: Path, origin: str, summary: OpenSummary
    ) -> LoadedDocument | None:
        options: dict[str, bool] = {}
        for _attempt in range(3):
            try:
                return load_document(path, **options)
            except DocumentError as exc:
                message = str(exc)
                if (
                    "확장자" in message
                    and origin != "drop"
                    and "allow_unusual_extension" not in options
                ):
                    answer = QMessageBox.question(
                        self, "확장자 확인", f"{path.name}\n{message}\n그래도 열까요?"
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        summary.skipped.append((path.name, "사용자가 취소함"))
                        return None
                    options["allow_unusual_extension"] = True
                    continue
                if "너무 큽니다" in message and "allow_large" not in options:
                    answer = QMessageBox.question(
                        self, "큰 파일", f"{path.name}\n{message}\n그래도 열까요?"
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        summary.skipped.append((path.name, "사용자가 취소함"))
                        return None
                    options["allow_large"] = True
                    continue
                summary.failed.append((path.name, message))
                return None
        return None

    def _report_open_summary(self, summary: OpenSummary, origin: str) -> None:
        single_open = len(summary.opened) == 1 and not (
            summary.already_open or summary.failed or summary.skipped
        )
        session = self.active_session
        if single_open and session is not None and session.document.warnings:
            self.statusBar().showMessage(" ".join(session.document.warnings), 12000)
        elif summary.status_text():
            self.statusBar().showMessage(summary.status_text(), 12000)
        if summary.failed or (origin == "drop" and summary.skipped and not summary.any_document):
            title = "파일 열기 실패" if summary.failed else "열 수 있는 파일 없음"
            QMessageBox.warning(self, title, "\n".join(summary.problem_lines()))

    def handle_drop(self, plan: DropPlan) -> None:
        """Callback of the drop controller (runs after the drag has finished)."""
        if self._shut_down:
            return
        self.open_paths(plan.paths, origin="drop", skipped=plan.skipped)

    def _explain_rejected_drop(self, plan: DropPlan) -> None:
        """Non-blocking hint while dragging items that cannot be opened (no modal dialog)."""
        reasons = ", ".join(f"{Path(name).name or name}({reason})" for name, reason in plan.skipped)
        self.statusBar().showMessage(f"열 수 없는 항목: {reasons}", 8000)

    # ----- editing commands (always the active tab) --------------------------------------

    def _editor_call(self, method: str) -> None:
        editor = self.editor
        if editor is not None:
            getattr(editor, method)()

    def _apply_edit(self, result: EditResult) -> None:
        editor = self.editor
        if editor is None:
            return
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(result.start)
        cursor.setPosition(result.end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(result.replacement)
        cursor.setPosition(result.selection_start)
        cursor.setPosition(result.selection_end, QTextCursor.MoveMode.KeepAnchor)
        cursor.endEditBlock()
        editor.setTextCursor(cursor)
        editor.setFocus()

    @Slot(str)
    def apply_command(self, command: str) -> None:
        session = self.active_session
        if session is None:
            return
        editor = session.editor
        text = editor.raw_text()
        cursor = editor.textCursor()
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
                str(session.path.parent),
                "이미지 (*.png *.jpg *.jpeg *.gif *.svg *.webp *.bmp)",
            )
            if not path:
                return
            relative = os.path.relpath(path, session.path.parent).replace("\\", "/")
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

    def _ensure_find_dialog(self) -> FindReplaceDialog | None:
        editor = self.editor
        if editor is None:
            return None
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(editor, self)
        self._find_dialog.editor = editor
        return self._find_dialog

    def show_find(self) -> None:
        dialog = self._ensure_find_dialog()
        if dialog is None:
            return
        dialog.replace_edit.setVisible(False)
        dialog.show()
        dialog.raise_()
        dialog.find_edit.setFocus()

    def show_replace(self) -> None:
        dialog = self._ensure_find_dialog()
        if dialog is None:
            return
        dialog.replace_edit.setVisible(True)
        dialog.show()
        dialog.raise_()

    def find_next(self) -> None:
        if self._find_dialog is not None and self._ensure_find_dialog() is not None:
            self._find_dialog.find_next()

    def ask_go_to_line(self) -> None:
        editor = self.editor
        if editor is None:
            return
        line, ok = QInputDialog.getInt(
            self,
            "줄로 이동",
            "줄 번호",
            editor.textCursor().blockNumber() + 1,
            1,
            max(1, editor.blockCount()),
        )
        if ok:
            self.go_to_line(line)

    @Slot(int)
    def go_to_line(self, line: int) -> None:
        editor = self.editor
        if editor is None:
            return
        block = editor.document().findBlockByNumber(max(0, line - 1))
        if block.isValid():
            editor.setTextCursor(QTextCursor(block))
            editor.centerCursor()
            editor.setFocus()

    @Slot()
    def start_render(self) -> None:
        session = self.active_session
        if session is not None:
            session.start_render()

    @Slot()
    def fix_sync_scroll(self) -> None:
        session = self.active_session
        if session is not None:
            session.fix_sync_scroll()

    # ----- global view settings (applied to every tab) -----------------------------------

    def set_view_mode(self, mode: str) -> None:
        if mode not in VIEW_MODES:
            mode = "both"
        self.view_mode = mode
        self.view_mode_actions[mode].setChecked(True)
        for session in self._sessions:
            session.set_view_mode(mode)
        self.settings.setValue("view/mode", mode)

    @Slot(bool)
    def toggle_word_wrap(self, enabled: bool) -> None:
        self.word_wrap_enabled = enabled
        for session in self._sessions:
            session.editor.set_word_wrap(enabled)
        self.settings.setValue("view/word_wrap", enabled)

    @Slot(bool)
    def toggle_external_images(self, enabled: bool) -> None:
        self.allow_external_images = enabled
        # One guard serves every tab, so the setting is global by construction.
        shared_network_guard().allow_external_images = enabled
        for session in self._sessions:
            session.set_external_images(enabled)

    @Slot(bool)
    def toggle_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        self.setStyleSheet(DARK_STYLE if enabled else "")
        self._apply_tab_style()
        for session in self._sessions:
            session.set_dark_mode(enabled)
        self.settings.setValue("view/dark_mode", enabled)

    @Slot(int)
    def adjust_font_size(self, steps: int) -> None:
        self.set_font_size(self.font_size + steps)

    def set_font_size(self, size: int) -> None:
        bounded = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(size)))
        self.font_size = bounded
        for session in self._sessions:
            session.set_font_size(bounded)
        self.font_size_label.setText(f"글자 {bounded}")
        self.font_decrease_button.setEnabled(bounded > MIN_FONT_SIZE)
        self.font_increase_button.setEnabled(bounded < MAX_FONT_SIZE)
        self.settings.setValue("view/font_size", bounded)

    def adjust_letter_spacing(self, steps: int) -> None:
        self.set_letter_spacing(step_letter_spacing(self.letter_spacing, steps))

    def set_letter_spacing(self, percent: int, *, announce: bool = True) -> None:
        """Editor-only letter spacing (PRD 4차 R4-01). The preview is left unchanged."""
        value = clamp_letter_spacing(percent)
        self.letter_spacing = value
        for session in self._sessions:
            session.set_letter_spacing(value)
        self.letter_spacing_label.setText(f"간격 {value}%")
        self.letter_spacing_larger_action.setEnabled(value < MAX_LETTER_SPACING)
        self.letter_spacing_smaller_action.setEnabled(value > MIN_LETTER_SPACING)
        self.letter_spacing_reset_action.setEnabled(value != DEFAULT_LETTER_SPACING)
        self.settings.setValue("view/letter_spacing", value)
        if announce:
            self.statusBar().showMessage(f"편집기 글간격 {value}%", 5000)

    @Slot(bool)
    def toggle_sync_scroll(self, enabled: bool) -> None:
        self.sync_scroll_enabled = enabled
        self.settings.setValue("view/sync_scroll", enabled)
        for session in self._sessions:
            session.set_sync_scroll(enabled)

    @Slot(bool)
    def toggle_auto_indent(self, enabled: bool) -> None:
        self.auto_indent_enabled = enabled
        for session in self._sessions:
            session.editor.set_auto_indent(enabled)
        self.settings.setValue("edit/auto_indent", enabled)

    # ----- saving (active tab only) ---------------------------------------------------------

    def _choose_save_target(self) -> Path | None:
        session = self.active_session
        if session is None:
            return None
        current = session.path
        candidate = dated_path(current, self.date_provider())

        def taken(path: Path) -> bool:
            return self._is_open_elsewhere(path, session)

        if current in self.session_saved_paths and current == candidate:
            return current
        if taken(candidate):
            box = QMessageBox(self)
            box.setWindowTitle("다른 탭에서 열려 있는 파일")
            box.setText(
                f"저장할 파일이 다른 탭에서 열려 있어 덮어쓸 수 없습니다.\n{candidate.name}"
            )
            numbered = box.addButton("번호 붙여 저장", QMessageBox.ButtonRole.ActionRole)
            box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is numbered:
                return first_available_path(candidate, taken)
            return None
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
            return first_available_path(candidate, taken)
        return None

    @Slot()
    def save_document(self) -> bool:
        if self.active_session is None:
            return False
        target = self._choose_save_target()
        return False if target is None else self.save_to_path(target)

    def save_to_path(self, target: str | Path) -> bool:
        session = self.active_session
        if session is None:
            return False
        target_path = Path(target).resolve()
        owner = self.find_session(target_path)
        if owner is not None and owner is not session:
            QMessageBox.warning(
                self,
                "다른 탭에서 열려 있는 파일",
                f"다른 탭에서 열려 있는 파일에는 저장할 수 없습니다.\n{target_path}",
            )
            return False
        document = session.document
        editor = session.editor
        try:
            payload = encode_document(
                document, editor.raw_text(), edited=editor.document().isModified()
            )
        except DocumentError as exc:
            if "표현할 수 없는" not in str(exc):
                QMessageBox.critical(self, "저장 실패", str(exc))
                return False
            answer = QMessageBox.question(self, "UTF-8로 저장", f"{exc}\nUTF-8로 저장할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
            payload = editor.raw_text().replace("\n", document.format.newline).encode("utf-8")
        try:
            atomic_write(target_path, payload)
            new_document = load_document(
                target_path, allow_unusual_extension=True, allow_large=True
            )
        except DocumentError as exc:
            QMessageBox.critical(self, "저장 실패", str(exc))
            return False
        self.session_saved_paths.add(target_path)
        editor.document().setModified(False)
        session.set_document(new_document)
        self._remember_recent(target_path)
        self._refresh_tab_titles()
        self._update_title()
        self._update_status()
        self.statusBar().showMessage(f"저장했습니다: {target_path.name}", 8000)
        return True

    @Slot()
    def save_as(self) -> bool:
        session = self.active_session
        if session is None:
            return False
        suggested = dated_path(session.path, self.date_provider())
        path, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", str(suggested), OPEN_FILTER
        )
        if not path:
            return False
        target = Path(path).resolve()
        owner = self.find_session(target)
        if owner is not None and owner is not session:
            QMessageBox.warning(
                self,
                "다른 탭에서 열려 있는 파일",
                f"이 파일은 다른 탭에서 열려 있어 저장하지 않았습니다.\n{target}",
            )
            self.activate_session(owner)
            return False
        if target == session.path:
            answer = QMessageBox.warning(
                self,
                "원본 덮어쓰기",
                "원본 파일을 덮어씁니다. 계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        elif target.parent != session.path.parent:
            broken = sum(1 for item in session.links if item.status == "정상" and item.resolved)
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

    # ----- closing tabs and the window -----------------------------------------------------

    def _confirm_close(self, session: DocumentSession) -> bool:
        """Ask about unsaved changes of one tab. Returns False when closing must stop."""
        if not session.is_modified():
            return True
        self.activate_session(session)
        box = QMessageBox(self)
        box.setWindowTitle("저장하지 않은 변경")
        box.setText(f"'{session.path.name}'의 변경 내용을 저장할까요?")
        save_button = box.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("저장 안 함", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save_button:
            return self.save_document()
        return box.clickedButton() is discard_button

    def close_session(self, session: DocumentSession, *, confirm: bool = True) -> bool:
        if session not in self._sessions:
            return False
        if confirm and not self._confirm_close(session):
            return False
        if self._find_dialog is not None and self._find_dialog.editor is session.editor:
            self._find_dialog.hide()
        if self.active_session is session:
            self._saved_splitter_state = session.splitter.saveState()
        session.shutdown()
        self._sessions.remove(session)
        index = self.tabs.indexOf(session.page)
        if index >= 0:
            self.tabs.removeTab(index)
        session.page.deleteLater()
        session.deleteLater()
        self._refresh_tab_titles()
        self._on_current_tab_changed(self.tabs.currentIndex())
        return True

    @Slot()
    def close_active_tab(self) -> bool:
        session = self.active_session
        return self.close_session(session) if session is not None else False

    @Slot(int)
    def _on_tab_close_requested(self, index: int) -> None:
        session = self._session_for_page(self.tabs.widget(index))
        if session is not None:
            self.close_session(session)

    def _sessions_in_tab_order(self) -> list[DocumentSession]:
        pages = (self.tabs.widget(index) for index in range(self.tabs.count()))
        return [session for page in pages if (session := self._session_for_page(page))]

    def close_other_sessions(self, keep: DocumentSession | None) -> bool:
        """Close every tab except ``keep`` in tab order; stops at the first cancelled prompt."""
        if keep is None or keep not in self._sessions:
            return False
        for session in self._sessions_in_tab_order():
            if session is not keep and not self.close_session(session):
                return False
        self.activate_session(keep)
        return True

    def close_all_sessions(self) -> bool:
        """Close every tab in tab order; stops at the first cancelled prompt."""
        return all(self.close_session(session) for session in self._sessions_in_tab_order())

    def tab_context_menu(self, index: int) -> QMenu | None:
        """Right-click menu of one tab (built separately so it can be tested without exec)."""
        session = self._session_for_page(self.tabs.widget(index))
        if session is None:
            return None
        menu = QMenu(self)
        entries = (
            (CLOSE_TAB, lambda s=session: self.close_session(s)),
            ("다른 탭 닫기", lambda s=session: self.close_other_sessions(s)),
            ("모든 탭 닫기", self.close_all_sessions),
            (None, None),
            (
                "파일 위치 열기",
                lambda s=session: self.external_opener(QUrl.fromLocalFile(str(s.path.parent))),
            ),
            ("전체 경로 복사", lambda s=session: QApplication.clipboard().setText(str(s.path))),
        )
        for text, handler in entries:
            if text is None:
                menu.addSeparator()
                continue
            action = menu.addAction(text)
            # triggered(bool) must not reach the handler's default arguments.
            action.triggered.connect(lambda _checked=False, run=handler: run())
        menu.actions()[1].setEnabled(len(self._sessions) > 1)
        return menu

    @Slot(QPoint)
    def _show_tab_context_menu(self, position: QPoint) -> None:
        tab_bar = self.tabs.tabBar()
        menu = self.tab_context_menu(tab_bar.tabAt(position))
        if menu is not None:
            menu.exec(tab_bar.mapToGlobal(position))
            menu.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        # Middle-click on a tab closes it, as in browsers and most editors.
        if (
            watched is self.tabs.tabBar()
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.MiddleButton
        ):
            index = self.tabs.tabBar().tabAt(event.position().toPoint())
            session = self._session_for_page(self.tabs.widget(index)) if index >= 0 else None
            if session is not None:
                self.close_session(session)
                return True
        return super().eventFilter(watched, event)

    def shutdown_sessions(self) -> None:
        """Release every tab (idempotent). Used by closeEvent and the application exit."""
        if self._shut_down:
            return
        self._shut_down = True
        for session in list(self._sessions):
            session.shutdown()
        self.thread_pool.waitForDone(5000)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._shut_down:
            for session in list(self._sessions):
                if not self._confirm_close(session):
                    event.ignore()
                    return
            self._save_settings()
            self.shutdown_sessions()
        _live_windows.discard(self)
        if not _live_windows:
            release_shared_network_guard()
        event.accept()

    # ----- links, help and drag-and-drop ----------------------------------------------------

    @Slot(str)
    def open_link(self, target: str) -> None:
        session = self.active_session
        if session is not None:
            self._open_link_from(session, target)

    def _open_link_from(self, session: DocumentSession, target: str) -> None:
        parsed = urlparse(target)
        if parsed.scheme.lower() in {"javascript", "vbscript"}:
            self.statusBar().showMessage("안전을 위해 위험한 링크를 차단했습니다.", 8000)
            return
        if parsed.scheme.lower() in {"http", "https", "mailto"}:
            self.external_opener(QUrl(target))
            return
        clean = unquote(parsed.path).replace("/", os.sep)
        path = Path(clean) if re_drive_path(clean) else (session.path.parent / clean)
        path = path.resolve()
        if not path.exists():
            QMessageBox.warning(self, "파일 없음", f"파일을 찾을 수 없습니다:\n{path}")
            return
        if is_markdown_path(path):
            self.open_paths([path], origin="link")
        else:
            self.external_opener(QUrl.fromLocalFile(str(path)))

    def open_file_location(self) -> None:
        session = self.active_session
        if session is not None:
            self.external_opener(QUrl.fromLocalFile(str(session.path.parent)))

    def open_help(self) -> None:
        path = Path(__file__).resolve().parents[3] / "docs" / "사용설명서.md"
        if path.exists():
            self.open_paths([path], origin="help")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "MarkdownEditor 정보",
            "MarkdownEditor 0.1.0\n\n"
            "Python · PySide6 · QtWebEngine · markdown-it-py · Mermaid\n"
            "자세한 라이선스는 THIRD_PARTY_NOTICES.md를 참고하세요.",
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        self.drop_controller.handle(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        self.drop_controller.handle(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.drop_controller.handle(event)


def _as_path_list(value: str | Path | Sequence[str | Path] | None) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, str | Path):
        return [Path(value)]
    return [Path(item) for item in value]


def re_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in {"\\", "/"}


def _setting_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
