from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from markdowneditor.core.opening import is_markdown_path

if TYPE_CHECKING:
    from markdowneditor.gui.main_window import MainWindow


class MarkdownApplication(QApplication):
    """Route Finder/Dock document events to tabs, including events during startup."""

    def __init__(self, argv: list[str]) -> None:
        self.window: MainWindow | None = None
        self.pending_paths: list[str] = []
        self._scheduled = False
        super().__init__(argv)

    def set_window(self, window: MainWindow | None) -> None:
        self.window = window
        self._schedule_open()

    def event(self, event: QEvent) -> bool:
        if event.type() != QEvent.Type.FileOpen or not isinstance(event, QFileOpenEvent):
            return super().event(event)
        url = event.url()
        if not url.isLocalFile() or not is_markdown_path(url.toLocalFile()):
            return super().event(event)
        self.pending_paths.append(url.toLocalFile())
        self._schedule_open()
        event.accept()
        return True

    def _schedule_open(self) -> None:
        if self.window is not None and self.pending_paths and not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(0, self, self._open_pending)

    def _open_pending(self) -> None:
        self._scheduled = False
        window = self.window
        if window is None or not self.pending_paths:
            return
        paths, self.pending_paths = self.pending_paths, []
        window.open_paths(paths, origin="finder")
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
