from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget

from markdowneditor.core.opening import DropEntry, DropPlan, classify_drop

TEXT_FALLBACK_PROPERTY = "markdownEditorDropTextFallback"
WEB_VIEW_PROPERTY = "markdownEditorDropWebView"
_DRAG_EVENTS = {QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop}


def plan_from_mime(mime: QMimeData | None) -> DropPlan | None:
    """Classify dragged URLs. Returns None when the drag carries no URLs at all."""
    if mime is None or not mime.hasUrls():
        return None
    entries = []
    for url in mime.urls():
        if url.isLocalFile():
            local = url.toLocalFile()
            entries.append(DropEntry(display=local, local_path=local))
        else:
            entries.append(DropEntry(display=url.toString()))
    return classify_drop(entries)


class FileDropController(QObject):
    """Routes Explorer file drops from every target widget to one open callback.

    Qt delivers drag events to the deepest widget that accepts drops: the editor viewport
    and the WebEngine render widget consume them before the main window sees them, so this
    filter is installed on those widgets as well as used by the main window itself.
    """

    def __init__(
        self,
        on_drop: Callable[[DropPlan], None],
        parent: QObject | None = None,
        *,
        on_reject: Callable[[DropPlan], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_drop = on_drop
        # Qt never delivers the Drop of a rejected drag, so the reason is shown while dragging.
        self._on_reject = on_reject

    def watch(self, widget: QWidget, *, text_fallback: bool = False) -> None:
        """Intercept file drops on ``widget``.

        With ``text_fallback`` the widget keeps its normal behaviour for drags that carry no
        local files (moving text inside the editor, text or web links from other apps).
        """
        widget.setProperty(TEXT_FALLBACK_PROPERTY, text_fallback)
        widget.installEventFilter(self)

    def watch_web_view(self, view: QWidget) -> None:
        """Watch a QWebEngineView and every render widget it creates now or later."""
        view.setProperty(WEB_VIEW_PROPERTY, True)
        view.installEventFilter(self)
        for child in view.findChildren(QWidget):
            self.watch(child)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type == QEvent.Type.ChildAdded and watched.property(WEB_VIEW_PROPERTY):
            child = event.child()
            if isinstance(child, QWidget):
                self.watch(child)
            return False
        if event_type in _DRAG_EVENTS:
            text_fallback = bool(watched.property(TEXT_FALLBACK_PROPERTY))
            return self.handle(event, text_fallback=text_fallback)
        return False

    def handle(self, event: QEvent, *, text_fallback: bool = False) -> bool:
        """Handle one drag event. Returns True when the event must not reach the widget."""
        plan = plan_from_mime(event.mimeData())
        if plan is None or not plan.has_local_files:
            if text_fallback:
                return False
            if event.type() == QEvent.Type.Drop and plan is not None:
                self._dispatch(plan)
            event.ignore()
            return True
        if event.type() in {QEvent.Type.DragEnter, QEvent.Type.DragMove}:
            if plan.can_open:
                self._accept_copy(event)
            else:
                event.ignore()
                if event.type() == QEvent.Type.DragEnter and self._on_reject is not None:
                    self._on_reject(plan)
            return True
        if plan.can_open:
            self._accept_copy(event)
        else:
            event.ignore()
        self._dispatch(plan)
        return True

    @staticmethod
    def _accept_copy(event: QEvent) -> None:
        # Never acceptProposedAction(): if Explorer proposes a move (Shift, same drive)
        # answering "moved" could make the source treat the original file as moved.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _dispatch(self, plan: DropPlan) -> None:
        # Return to Explorer's drag loop first; dialogs are shown on the next event-loop turn.
        QTimer.singleShot(0, self, lambda: self._on_drop(plan))
