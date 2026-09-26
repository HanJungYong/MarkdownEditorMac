from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSignalBlocker, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from markdowneditor.core.file_io import LoadedDocument
from markdowneditor.core.links import LinkReference, inspect_links
from markdowneditor.core.opening import document_key
from markdowneditor.core.renderer import RenderResult, render_markdown
from markdowneditor.gui.editor import MarkdownEditorWidget
from markdowneditor.gui.preview import PreviewPane
from markdowneditor.gui.toolbar import MarkdownActions, MarkdownToolbar


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


@dataclass
class ViewState:
    """Application-wide view settings that every tab follows."""

    dark_mode: bool
    font_size: int
    letter_spacing: int
    auto_indent: bool
    word_wrap: bool
    allow_external_images: bool
    sync_scroll: bool
    view_mode: str


class DocumentSession(QObject):
    """Everything one document tab owns: file data, editor, preview, render and sync state."""

    render_completed = Signal(object)
    render_status_changed = Signal(str)
    links_changed = Signal()
    status_changed = Signal()
    modification_changed = Signal(bool)
    link_requested = Signal(str)
    status_message = Signal(str, int)
    sync_scroll_toggled = Signal(bool)
    sync_scroll_fixed = Signal(object)
    font_zoom_requested = Signal(int)

    def __init__(
        self,
        document: LoadedDocument,
        *,
        actions: MarkdownActions,
        thread_pool: QThreadPool,
        state: ViewState,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.document = document
        self.thread_pool = thread_pool
        self.links: list[LinkReference] = []
        self.closed = False
        self.activated = False
        self.preview_render_ready = False
        self.render_text = ""
        self.sync_scroll_enabled = state.sync_scroll
        self.allow_external_images = state.allow_external_images
        self._revision = 0
        self._last_render_result: RenderResult | None = None
        self._pending_preview_source_line = 1.0
        self._syncing_from_preview = False

        self.page = QWidget()
        self.toolbar = MarkdownToolbar(actions, self.page)
        self.editor = MarkdownEditorWidget(self.page)
        self.preview = PreviewPane(self.page)
        self.preview.set_control_height(self.toolbar.sizeHint().height())
        self.left_panel = QWidget(self.page)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.toolbar)
        left_layout.addWidget(self.editor)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self.page)
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([700, 700])
        page_layout = QVBoxLayout(self.page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self.splitter)

        self.render_timer = self._timer(300, self.start_render)
        self.editor_sync_timer = self._timer(30, self._apply_sync_from_editor)
        self.preview_sync_timer = self._timer(30, self._apply_sync_from_preview)

        self.editor.blockSignals(True)
        self.editor.setPlainText(document.text)
        self.editor.document().setModified(False)
        self.editor.blockSignals(False)
        self.apply_view_state(state)

        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self.status_changed)
        self.editor.document().modificationChanged.connect(self.modification_changed)
        self.editor.verticalScrollBar().valueChanged.connect(self._sync_from_editor)
        self.editor.font_zoom_requested.connect(self.font_zoom_requested)
        self.preview.render_completed.connect(self._preview_completed)
        self.preview.link_requested.connect(self.link_requested)
        self.preview.message_reported.connect(lambda message: self.status_message.emit(message, 0))
        self.preview.font_zoom_requested.connect(self.font_zoom_requested)
        self.preview.scroll_source_line_changed.connect(self._sync_from_preview)
        self.preview.sync_scroll_toggled.connect(self.sync_scroll_toggled)
        self.preview.sync_scroll_fix_requested.connect(self.fix_sync_scroll)

    def _timer(self, interval: int, slot) -> QTimer:  # noqa: ANN001
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    # ----- identity and state -------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.document.path

    @property
    def key(self) -> str:
        return document_key(self.document.path)

    def is_modified(self) -> bool:
        return self.editor.document().isModified()

    def set_document(self, document: LoadedDocument) -> None:
        """Adopt the reloaded file after a save (new path, same editor contents)."""
        self.document = document
        self.preview.set_document_directory(document.path.parent)
        self.refresh_links()
        self.status_changed.emit()

    def apply_view_state(self, state: ViewState) -> None:
        self.editor.set_markdown_font_size(state.font_size)
        self.editor.set_letter_spacing(state.letter_spacing)
        self.editor.set_auto_indent(state.auto_indent)
        self.editor.set_word_wrap(state.word_wrap)
        self.editor.set_dark_mode(state.dark_mode)
        self.preview.set_markdown_font_size(state.font_size)
        self.preview.set_dark_mode(state.dark_mode)
        self.preview.set_external_images(state.allow_external_images)
        self.allow_external_images = state.allow_external_images
        self.set_sync_scroll(state.sync_scroll)
        self.set_view_mode(state.view_mode)

    # ----- global settings pushed from the main window ------------------------------------

    def set_dark_mode(self, enabled: bool) -> None:
        self.editor.set_dark_mode(enabled)
        self.preview.set_dark_mode(enabled)
        self.start_render()

    def set_font_size(self, size: int) -> None:
        self.editor.set_markdown_font_size(size)
        self.preview.set_markdown_font_size(size)

    def set_letter_spacing(self, percent: int) -> None:
        self.editor.set_letter_spacing(percent)

    def set_external_images(self, enabled: bool) -> None:
        self.allow_external_images = enabled
        self.preview.set_external_images(enabled)
        self.start_render()

    def set_sync_scroll(self, enabled: bool) -> None:
        self.sync_scroll_enabled = enabled
        blocker = QSignalBlocker(self.preview.sync_checkbox)
        self.preview.sync_checkbox.setChecked(enabled)
        del blocker
        if enabled:
            QTimer.singleShot(0, self, self._sync_from_editor)

    def set_view_mode(self, mode: str) -> None:
        self.left_panel.setVisible(mode in {"both", "editor"})
        self.preview.setVisible(mode in {"both", "preview"})

    # ----- activation and rendering --------------------------------------------------------

    def activate(self) -> None:
        """Start the preview the first time the tab is shown (lazy WebEngine shell)."""
        if self.closed or self.activated:
            return
        self.activated = True
        self.preview.set_document_directory(self.document.path.parent)
        self.preview.ensure_started()
        self.refresh_links()
        self.start_render()

    def refresh_links(self) -> None:
        if self.closed:
            return
        self.links = inspect_links(self.editor.raw_text(), self.document.path)
        self.links_changed.emit()

    def _on_text_changed(self) -> None:
        if self.closed:
            return
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self.render_timer.start()
        self.status_changed.emit()

    @Slot()
    def start_render(self) -> None:
        if self.closed or not self.activated:
            return
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self._revision += 1
        task = RenderTask(self._revision, self.editor.raw_text(), self.allow_external_images)
        task.signals.finished.connect(self._renderer_finished)
        task.signals.failed.connect(self._renderer_failed)
        self.thread_pool.start(task)

    @Slot(int, object)
    def _renderer_finished(self, revision: int, result: RenderResult) -> None:
        if self.closed or revision != self._revision:
            return
        self._last_render_result = result
        self.render_text = f"Python {result.elapsed_ms:.0f}ms"
        self.render_status_changed.emit(self.render_text)
        self.preview.update_html(result.html, revision, self.editor.blockCount())
        self.refresh_links()

    @Slot(int, str)
    def _renderer_failed(self, revision: int, message: str) -> None:
        if self.closed or revision != self._revision:
            return
        self.preview_render_ready = False
        self.preview.set_sync_fix_enabled(False)
        self.status_message.emit(f"미리보기 생성 실패: {message}", 10000)

    @Slot(object)
    def _preview_completed(self, stats: object) -> None:
        if self.closed:
            return
        self.preview_render_ready = True
        self.preview.set_sync_fix_enabled(True)
        if isinstance(stats, dict):
            self.render_text = (
                f"{self._last_render_result.elapsed_ms:.0f}ms · "
                f"표 {stats.get('tables', 0)} · 이미지 {stats.get('imagesLoaded', 0)}"
                if self._last_render_result
                else "미리보기 완료"
            )
            self.render_status_changed.emit(self.render_text)
        self.render_completed.emit(stats)
        if self.sync_scroll_enabled:
            self._sync_from_editor()

    # ----- scroll synchronisation (within this tab only) ----------------------------------

    @Slot(int)
    def _sync_from_editor(self, _value: int = 0) -> None:
        if (
            self.closed
            or not self.sync_scroll_enabled
            or not self.preview_render_ready
            or self._syncing_from_preview
        ):
            return
        self.editor_sync_timer.start()

    @Slot()
    def _apply_sync_from_editor(self) -> None:
        if self.closed or not self.sync_scroll_enabled or not self.preview_render_ready:
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
        if self.closed or not self.sync_scroll_enabled or not self.preview_render_ready:
            return
        self._pending_preview_source_line = line
        self.preview_sync_timer.start()

    @Slot()
    def _apply_sync_from_preview(self) -> None:
        if self.closed or not self.sync_scroll_enabled or not self.preview_render_ready:
            return
        self._syncing_from_preview = True
        try:
            self.editor.scroll_source_line_to_top(self._pending_preview_source_line)
        finally:
            self._syncing_from_preview = False

    @Slot()
    def fix_sync_scroll(self) -> None:
        if self.closed:
            return
        if not self.preview_render_ready:
            self.status_message.emit("미리보기 렌더링이 끝난 후 위치를 맞출 수 있습니다.", 5000)
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
        if self.closed:
            return
        self.preview.set_sync_fix_enabled(self.preview_render_ready)
        if isinstance(result, dict) and result.get("ok"):
            self.status_message.emit("편집기 기준으로 미리보기 위치를 맞췄습니다.", 5000)
        else:
            self.status_message.emit("미리보기 위치를 맞추지 못했습니다.", 5000)
        self.sync_scroll_fixed.emit(result)

    # ----- teardown ------------------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop timers and release the WebEngine page. Late render results are ignored."""
        if self.closed:
            return
        self.closed = True
        for timer in (self.render_timer, self.editor_sync_timer, self.preview_sync_timer):
            timer.stop()
        self.preview.shutdown()
