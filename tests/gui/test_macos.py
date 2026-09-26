from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QAction, QFileOpenEvent, QKeySequence
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.gui


def test_finder_events_queue_during_startup_and_reuse_open_tabs(
    qtbot, qapp, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    first = tmp_path / "한글 문서.md"
    second = tmp_path / "다른 문서.markdown"
    first.write_text("# 첫 문서\n", encoding="utf-8")
    second.write_text("# 다음 문서\n", encoding="utf-8")
    handler = qapp
    try:
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(str(first)))
        assert handler.pending_paths == [str(first)]
        assert not app_window.sessions
        handler.set_window(app_window)
        qtbot.waitUntil(lambda: len(app_window.sessions) == 1)
        initial = app_window.active_session
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(str(second)))
        qtbot.waitUntil(lambda: len(app_window.sessions) == 2)
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(str(first)))
        qtbot.waitUntil(lambda: app_window.active_session is initial)
        assert len(app_window.sessions) == 2
        assert not handler.pending_paths
        # Remote URLs must not be interpreted as local documents.
        QCoreApplication.sendEvent(qapp, QFileOpenEvent(QUrl("https://example.com/document.md")))
        assert not handler.pending_paths
    finally:
        handler.set_window(None)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native shortcut bindings")
def test_mac_shortcuts_avoid_hide_and_find_next_conflicts(
    qtbot, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    edit_menu = next(a.menu() for a in app_window.menuBar().actions() if a.text() == "편집(&E)")
    actions = {a.text(): a for a in edit_menu.actions()}
    assert actions["바꾸기"].shortcut() == QKeySequence("Ctrl+Shift+H")
    assert actions["바꾸기"].shortcut() != QKeySequence("Ctrl+H")
    assert actions["다음 찾기"].shortcut() == QKeySequence("Ctrl+G")
    assert actions["줄로 이동"].shortcut() == QKeySequence("Ctrl+L")
    sequences = [
        action.shortcut().toString()
        for action in app_window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]
    assert len(sequences) == len(set(sequences))
    for name in ("a.md", "b.md"):
        path = tmp_path / name
        path.write_text("# 탭 이동\n", encoding="utf-8")
        assert app_window.open_document(path)
    first, second = app_window.sessions
    qtbot.waitUntil(lambda: second.preview_render_ready, timeout=30_000)
    app_window.activateWindow()
    # A Python test runner is not a foreground .app; activate Qt's shortcut context.
    QApplication.setActiveWindow(app_window)
    second.editor.setFocus()
    qtbot.keyClick(second.editor, Qt.Key.Key_Tab, Qt.KeyboardModifier.MetaModifier)
    assert app_window.active_session is first
    qtbot.keyClick(
        first.editor,
        Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert app_window.active_session is second
