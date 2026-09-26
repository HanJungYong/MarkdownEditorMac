from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from gui_helpers import open_scratch_document as _open_scratch_document
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QAction, QDropEvent, QTextCursor, QWheelEvent
from PySide6.QtWebEngineCore import QWebEnginePage

from markdowneditor.core.naming import dated_path
from markdowneditor.gui.fonts import DEFAULT_FONT_SIZE, FONT_FAMILY

pytestmark = pytest.mark.gui


def _sample_root() -> Path:
    return Path(__file__).resolve().parents[2] / "Samples"


def test_open_render_edit_and_save_sample(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    source = _sample_root() / "설문지_기업 인공지능 활용 실태조사.md"
    copy = tmp_path / source.name
    shutil.copy2(source, copy)
    validation = _sample_root() / "설문지_기업 인공지능 활용 실태조사_validation"
    shutil.copytree(validation, tmp_path / validation.name)
    original = copy.read_bytes()

    window = app_window
    # No document yet: the welcome page is shown and there is no preview to align.
    assert window.preview is None
    assert window.central_stack.currentWidget() is window.welcome
    with qtbot.waitSignal(window.render_completed, timeout=20_000) as blocker:
        assert window.open_document(copy)
        assert window.preview.sync_fix_button.text() == "Sync Scroll 위치맞춤"
        assert not window.preview.sync_fix_button.isEnabled()
    assert window.preview.sync_fix_button.isEnabled()
    stats = blocker.args[0]
    assert stats["tables"] == 23
    assert stats["scriptPwned"] is False
    assert (
        window.editor.viewport().geometry().left()
        > window.editor.line_number_area.geometry().right()
    )

    cursor = window.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    window.editor.setTextCursor(cursor)
    with qtbot.waitSignal(window.render_completed, timeout=10_000):
        window.editor.insertPlainText("\n\n**GUI 검증 문장**\n")
        assert not window.preview.sync_fix_button.isEnabled()
    assert window.preview.sync_fix_button.isEnabled()
    assert "GUI 검증 문장" in window.editor.raw_text()

    output = dated_path(copy, date.today())
    assert window.save_to_path(output)
    assert copy.read_bytes() == original
    assert output.exists()


def test_mermaid_fixture_renders_and_isolates_error(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    source = Path(__file__).resolve().parents[1] / "fixtures" / "mermaid_flowchart.md"
    copy = tmp_path / source.name
    shutil.copy2(source, copy)
    window = app_window
    with qtbot.waitSignal(window.render_completed, timeout=30_000) as blocker:
        assert window.open_document(copy)
    stats = blocker.args[0]
    assert stats["mermaidSvg"] == 3
    assert stats["mermaidErrors"] == 1
    light_contrast = stats["mermaidContrast"]
    assert light_contrast["theme"] == "light"
    assert light_contrast["missing"] == []

    with qtbot.waitSignal(window.render_completed, timeout=30_000) as blocker:
        window.dark_mode_action.setChecked(True)
    dark_stats = blocker.args[0]
    assert dark_stats["mermaidSvg"] == 3
    assert dark_stats["mermaidErrors"] == 1
    dark_contrast = dark_stats["mermaidContrast"]
    assert dark_contrast["theme"] == "dark"
    assert dark_contrast["missing"] == []
    assert dark_contrast["minimumRatio"] >= 4.5, dark_contrast
    assert all(sample["ratio"] >= 4.5 for sample in dark_contrast["samples"])


def test_large_sample_renders_tables_and_images(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    source = _sample_root() / "차세대무역플랫폼 구축 사업 1단계 제안요청서.md"
    copy = tmp_path / source.name
    shutil.copy2(source, copy)
    for suffix in ("_assets", "_validation"):
        folder = _sample_root() / f"{source.stem}{suffix}"
        shutil.copytree(folder, tmp_path / folder.name)

    window = app_window
    with qtbot.waitSignal(window.render_completed, timeout=30_000) as blocker:
        assert window.open_document(copy)
    stats = blocker.args[0]
    assert stats["tables"] == 238
    assert stats["images"] == 7
    assert stats["imagesLoaded"] == 7, stats
    assert stats["imageErrors"] == 0
    assert stats["headings"] == 61

    window.preview.sync_checkbox.setChecked(True)
    editor_scroll = window.editor.verticalScrollBar()
    assert editor_scroll.maximum() > 0
    editor_scroll.setValue(editor_scroll.maximum() // 2)
    qtbot.wait(150)
    editor_line = window.editor.first_visible_source_line()
    viewer_lines: list[float] = []
    window.preview.page.runJavaScript("window.markdownEditorSourceLineAtTop()", viewer_lines.append)
    qtbot.waitUntil(lambda: bool(viewer_lines), timeout=3000)
    assert viewer_lines[-1] == pytest.approx(editor_line, abs=3)

    reported_lines: list[float] = []
    cursor_position = window.editor.textCursor().position()
    window.preview.scroll_source_line_changed.connect(reported_lines.append)
    window.preview.page.runJavaScript("window.markdownEditorSetScrollRatio(0.8, true)")
    qtbot.wait(200)
    assert reported_lines
    viewer_lines.clear()
    window.preview.page.runJavaScript("window.markdownEditorSourceLineAtTop()", viewer_lines.append)
    qtbot.waitUntil(lambda: bool(viewer_lines), timeout=3000)
    assert window.editor.first_visible_source_line() == pytest.approx(viewer_lines[-1], abs=4), (
        editor_scroll.value(),
        editor_scroll.maximum(),
        window.editor.blockCount(),
        reported_lines[-1],
        window.active_session._pending_preview_source_line,
        window.active_session.preview_sync_timer.isActive(),
    )
    assert window.editor.textCursor().position() == cursor_position

    window.preview.sync_checkbox.setChecked(False)
    editor_scroll.setValue(editor_scroll.maximum() // 3)
    expected_line = window.editor.first_visible_source_line()
    editor_value = editor_scroll.value()
    with qtbot.waitSignal(window.sync_scroll_fixed, timeout=3000) as blocker:
        qtbot.mouseClick(window.preview.sync_fix_button, Qt.MouseButton.LeftButton)
    result = blocker.args[0]
    assert isinstance(result, dict), repr(result)
    assert result["mode"] == "source-line"
    qtbot.wait(100)
    viewer_lines.clear()
    window.preview.page.runJavaScript("window.markdownEditorSourceLineAtTop()", viewer_lines.append)
    qtbot.waitUntil(lambda: bool(viewer_lines), timeout=3000)
    assert viewer_lines[-1] == pytest.approx(expected_line, abs=3)
    assert editor_scroll.value() == editor_value
    assert window.preview.sync_fix_button.isEnabled()
    assert "편집기 기준으로" in window.statusBar().currentMessage()


def test_security_fixture_does_not_execute_script(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    source = Path(__file__).resolve().parents[1] / "fixtures" / "security.md"
    copy = tmp_path / source.name
    shutil.copy2(source, copy)
    window = app_window
    with qtbot.waitSignal(window.render_completed, timeout=20_000) as blocker:
        assert window.open_document(copy)
    stats = blocker.args[0]
    assert stats["scriptPwned"] is False
    assert stats["tables"] == 1


def test_external_and_local_links_use_injected_opener_and_navigation_is_blocked(
    qtbot, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    source = tmp_path / "링크.md"
    local = tmp_path / "한글 파일.csv"
    source.write_text("# 링크\n", encoding="utf-8")
    local.write_text("a,b\n1,2\n", encoding="utf-8")
    window = app_window
    with qtbot.waitSignal(window.render_completed, timeout=20_000):
        assert window.open_document(source)

    opened: list[str] = []
    window.external_opener = lambda url: not opened.append(url.toString())
    window.open_link("https://example.com/path")
    window.open_link("한글%20파일.csv")
    assert opened[0] == "https://example.com/path"
    assert QUrl(opened[1]).toLocalFile() == str(local.resolve()).replace("\\", "/")

    with qtbot.waitSignal(window.preview.page.blocked_navigation) as blocker:
        accepted = window.preview.page.acceptNavigationRequest(
            QUrl("https://example.com/blocked"),
            QWebEnginePage.NavigationType.NavigationTypeLinkClicked,
            True,
        )
    assert accepted is False
    assert blocker.args == ["https://example.com/blocked"]


def test_toolbar_undo_shortcuts_date_provider_and_drop(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    source = tmp_path / "끌어놓기.md"
    source.write_text("첫 줄\n둘째 줄\n", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window = app_window
    with qtbot.waitSignal(window.render_completed, timeout=20_000):
        window.dropEvent(event)
    assert event.isAccepted()
    assert window.document_data is not None
    assert window.document_data.path == source.resolve()

    for command, expected in (
        ("bold", "**굵은 글씨**"),
        ("heading:2", "## 첫 줄"),
        ("table", "| 열 1 | 열 2 | 열 3 |"),
        ("mermaid", "flowchart TD"),
    ):
        before = window.editor.raw_text()
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        window.editor.setTextCursor(cursor)
        window.apply_command(command)
        assert expected in window.editor.raw_text()
        window.editor.undo()
        assert window.editor.raw_text() == before

    shortcuts = [
        action.shortcut().toString()
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]
    assert len(shortcuts) == len(set(shortcuts))

    window.date_provider = lambda: date(2026, 9, 19)
    assert window._choose_save_target() == tmp_path / "끌어놓기_20260919.md"


def test_prd_theme_editor_font_and_zoom_controls(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    _open_scratch_document(qtbot, window, tmp_path)
    window.set_font_size(DEFAULT_FONT_SIZE)
    window.dark_mode_action.setChecked(False)

    assert window.editor.extraSelections() == []
    assert window.editor.dark_mode is False
    assert "#ffffff" in window.editor.styleSheet()
    assert "#f2f4f7" in window.editor.styleSheet()
    assert FONT_FAMILY.lower() in window.editor.font().family().lower()
    assert window.editor.font().pointSize() == DEFAULT_FONT_SIZE
    assert window.preview.controls.minimumHeight() == window.preview.controls.maximumHeight()
    assert window.preview.sync_checkbox.parent() is window.preview.controls

    qtbot.mouseClick(window.font_increase_button, Qt.MouseButton.LeftButton)
    assert window.font_size == DEFAULT_FONT_SIZE + 1
    assert window.editor.font().pointSize() == DEFAULT_FONT_SIZE + 1
    assert window.preview.view.zoomFactor() == pytest.approx(
        (DEFAULT_FONT_SIZE + 1) / DEFAULT_FONT_SIZE
    )

    editor_wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    window.editor.wheelEvent(editor_wheel)
    assert window.font_size == DEFAULT_FONT_SIZE + 2

    preview_wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    window.preview.view.wheelEvent(preview_wheel)
    assert window.font_size == DEFAULT_FONT_SIZE + 1

    window.dark_mode_action.setChecked(True)
    assert window.dark_mode is True
    assert window.preview.dark_mode is True
    assert window.editor.dark_mode is True
    assert "#050607" in window.editor.styleSheet()
    assert "#f2f4f7" in window.editor.styleSheet()
    assert "#17191d" in window.styleSheet()


def test_prd_auto_indent_tab_and_markdown_continuation(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    _open_scratch_document(qtbot, window, tmp_path)
    editor = window.editor
    editor.setEnabled(True)

    assert window.indent_action.isChecked()
    assert editor.auto_indent_enabled is True

    editor.setPlainText("본문")
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.raw_text() == "본문  "

    editor.setPlainText("첫째\n둘째")
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.Start)
    cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.raw_text() == "  첫째\n  둘째"

    cases = (
        (True, "  일반", "  일반\n  "),
        (True, "- 목록", "- 목록\n- "),
        (True, "* [x] 완료", "* [x] 완료\n* [ ] "),
        (True, "7. 번호", "7. 번호\n8. "),
        (True, "> 인용", "> 인용\n> "),
        (True, "  - 중첩", "  - 중첩\n  - "),
        (False, "  일반", "  일반\n"),
        (False, "  - 중첩", "  - 중첩\n- "),
    )
    for enabled, source, expected in cases:
        window.indent_action.setChecked(enabled)
        editor.setPlainText(source)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        qtbot.keyClick(editor, Qt.Key.Key_Return)
        assert editor.raw_text() == expected

    assert window.settings.value("edit/auto_indent", type=bool) is False
