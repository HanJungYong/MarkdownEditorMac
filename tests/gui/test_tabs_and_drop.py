from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from gui_helpers import RFP, copy_sample, file_mime, send_drag_and_drop, write_markdown
from PySide6.QtCore import QMimeData, QSettings, Qt
from PySide6.QtGui import QAction, QFont, QFontMetrics, QTextCursor
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication, QWidget

from markdowneditor.core.naming import dated_path
from markdowneditor.gui import preview as preview_module
from markdowneditor.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


def _open(qtbot, window: MainWindow, path: Path):  # noqa: ANN001, ANN202
    """Open one file and wait for *that* tab's preview (other tabs may re-render meanwhile)."""
    assert window.open_document(path)
    session = window.active_session
    qtbot.waitUntil(lambda: session.preview_render_ready, timeout=30_000)
    return session


def _js(qtbot, session, script: str):  # noqa: ANN001, ANN202
    values: list[object] = []
    session.preview.page.runJavaScript(script, values.append)
    qtbot.waitUntil(lambda: bool(values), timeout=5000)
    return values[-1]


def _h1(qtbot, session) -> str:  # noqa: ANN001
    return _js(qtbot, session, "(document.querySelector('h1')||{}).textContent || ''")


def _dnd_target(widget: QWidget) -> QWidget:
    """Qt's own rule: the drop goes to the nearest widget (or ancestor) accepting drops."""
    current = widget
    while current is not None and not current.acceptDrops():
        current = current.parentWidget()
    assert current is not None
    return current


def _shortcuts(window: MainWindow) -> list[str]:
    return [
        action.shortcut().toString()
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    ]


# ----- R4-01 letter spacing ---------------------------------------------------------------


def test_letter_spacing_menu_steps_all_tabs_and_persists(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    first = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# 문서 A\n가나다라\n"))
    second = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# 문서 B\n마바사아\n"))
    larger = window.letter_spacing_larger_action
    smaller = window.letter_spacing_smaller_action
    assert larger.text() == "글간격 크게" and smaller.text() == "글간격 작게"
    view_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "보기(&V)")
    assert {larger, smaller} <= set(view_menu.actions())
    assert window.letter_spacing_label.text() == "간격 100%"

    before_width = first.editor.fontMetrics().horizontalAdvance("가나다라마바사")
    larger.trigger()
    for session in (first, second):
        font = session.editor.font()
        assert font.letterSpacingType() == QFont.SpacingType.PercentageSpacing
        assert font.letterSpacing() == pytest.approx(105)
    assert first.editor.fontMetrics().horizontalAdvance("가나다라마바사") > before_width
    assert "편집기 글간격 105%" in window.statusBar().currentMessage()
    smaller.trigger()
    assert first.editor.font().letterSpacing() == pytest.approx(100)

    for _ in range(20):
        larger.trigger()
    assert window.letter_spacing == 150 and not larger.isEnabled() and smaller.isEnabled()
    for _ in range(20):
        smaller.trigger()
    assert window.letter_spacing == 80 and not smaller.isEnabled() and larger.isEnabled()

    window.set_letter_spacing(120)
    # The preview's letter spacing is not changed by the editor setting.
    assert _js(qtbot, first, "getComputedStyle(document.body).letterSpacing") in {"normal", "0px"}
    # Preserved across font size, theme and new tabs.
    window.adjust_font_size(2)
    window.dark_mode_action.setChecked(True)
    third = _open(qtbot, window, write_markdown(tmp_path / "c.md", "# 문서 C\n"))
    for session in (first, second, third):
        assert session.editor.font().letterSpacing() == pytest.approx(120)
        assert session.editor.font().pointSize() == window.font_size
    assert window.settings.value("view/letter_spacing") in (120, "120")

    window.settings.sync()
    restored = MainWindow(
        settings=QSettings(window.settings.fileName(), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(restored)
    assert restored.letter_spacing == 120
    assert restored.letter_spacing_label.text() == "간격 120%"
    restored.close()


def test_letter_spacing_keeps_line_numbers_readable_on_large_sample(
    qtbot, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    window = app_window
    session = _open(qtbot, window, copy_sample(RFP, tmp_path))
    window.set_letter_spacing(150)
    editor = session.editor
    assert editor.blockCount() >= 4000
    area = editor.line_number_area
    assert area.font().letterSpacing() == pytest.approx(100)
    needed = QFontMetrics(area.font()).horizontalAdvance("9999")
    assert area.width() >= needed
    assert editor.viewport().geometry().left() > area.geometry().right()
    assert not editor.document().isModified()


# ----- R4-02 tabs ---------------------------------------------------------------------------


def test_two_tabs_keep_documents_previews_and_state_apart(
    qtbot, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    window = app_window
    folder_a = tmp_path / "가 폴더"
    folder_b = tmp_path / "나 폴더"
    a = _open(qtbot, window, write_markdown(folder_a / "문서.md", "# 문서 A\n\n본문 A\n"))
    b = _open(qtbot, window, write_markdown(folder_b / "문서.md", "# 문서 B\n\n본문 B\n"))
    assert window.tabs.count() == 2
    # Same file name in two folders: titles are told apart by the parent folder.
    assert window.tab_title(a) == "문서.md — 가 폴더"
    assert window.tab_title(b) == "문서.md — 나 폴더"
    assert window.tabs.tabToolTip(window.tabs.indexOf(a.page)) == str(a.path)
    assert a.preview.document_dir == folder_a.resolve()
    assert b.preview.document_dir == folder_b.resolve()
    assert _h1(qtbot, b) == "문서 B"

    window.activate_session(a)
    assert window.windowTitle() == "MarkdownEditor - 문서.md"
    assert _h1(qtbot, a) == "문서 A"
    cursor = a.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    a.editor.setTextCursor(cursor)
    with qtbot.waitSignal(a.render_completed, timeout=20_000):
        a.editor.insertPlainText("\n추가 A")
    assert a.is_modified() and not b.is_modified()
    assert window.tab_title(a).endswith(" *") and not window.tab_title(b).endswith(" *")
    assert window.windowTitle().endswith(" *")
    assert "추가 A" not in b.editor.raw_text()
    assert "추가 A" not in _js(qtbot, b, "document.body.innerText")
    assert "추가 A" in _js(qtbot, a, "document.body.innerText")

    # Cursor, selection and undo history survive a round trip through the other tab.
    cursor = a.editor.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
    a.editor.setTextCursor(cursor)
    window.activate_session(b)
    assert window.editor is b.editor
    window.activate_session(a)
    assert (a.editor.textCursor().selectionStart(), a.editor.textCursor().selectionEnd()) == (2, 5)
    a.editor.undo()
    assert "추가 A" not in a.editor.raw_text()


def test_menu_commands_follow_the_active_tab(qtbot, app_window, tmp_path: Path, dialogs) -> None:  # noqa: ANN001
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "alpha\n"))
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "beta\n"))
    edit_menu = next(x.menu() for x in window.menuBar().actions() if x.text() == "편집(&E)")
    actions = {action.text(): action for action in edit_menu.actions()}

    window.activate_session(a)
    actions["모두 선택"].trigger()
    assert a.editor.textCursor().selectedText().replace(" ", "\n") == "alpha\n"
    assert not b.editor.textCursor().hasSelection()
    QApplication.clipboard().setText("붙인 글")
    actions["붙여넣기"].trigger()
    assert a.editor.raw_text().startswith("붙인 글") and b.editor.raw_text() == "beta\n"
    actions["실행 취소"].trigger()
    assert a.editor.raw_text() == "alpha\n"

    window.activate_session(b)
    window.markdown_actions.actions_by_command["bold"].trigger()
    assert "**굵은 글씨**" in b.editor.raw_text() and "**" not in a.editor.raw_text()

    window.show_replace()
    assert window._find_dialog.editor is b.editor
    window.activate_session(a)
    assert window._find_dialog.editor is a.editor

    window.wrap_action.setChecked(False)
    assert a.editor.lineWrapMode() == b.editor.lineWrapMode()
    window.wrap_action.setChecked(True)

    # One QAction per shortcut even with two tab toolbars.
    shortcuts = _shortcuts(window)
    assert len(shortcuts) == len(set(shortcuts))
    assert a.toolbar.actions_by_command["bold"] is b.toolbar.actions_by_command["bold"]


def test_reopening_a_file_activates_its_tab(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    doc = write_markdown(
        tmp_path / "한글 폴더" / "같은 파일.md", "# 같은 파일\n\n[다른](다른.md)\n"
    )
    other = write_markdown(tmp_path / "한글 폴더" / "다른.md", "# 다른\n")
    first = _open(qtbot, window, doc)
    _open(qtbot, window, other)
    assert window.tabs.count() == 2
    for variant in (
        doc,
        *([Path(str(doc).upper())] if Path(str(doc).upper()).exists() else []),
        Path(str(doc).replace("\\", "/")),
        doc.parent / ".." / doc.parent.name / doc.name,
    ):
        window.activate_session(window.sessions[1])
        assert window.open_document(variant)
        assert window.active_session is first
        assert window.tabs.count() == 2
    cwd = Path.cwd()
    try:
        os.chdir(doc.parent)
        window.activate_session(window.sessions[1])
        assert window.open_document(Path(doc.name))
        assert window.active_session is first
    finally:
        os.chdir(cwd)
    window.open_paths([str(doc)], origin="recent")
    assert window.tabs.count() == 2
    window.activate_session(first)
    window.open_link("다른.md")
    assert window.active_session is window.sessions[1] and window.tabs.count() == 2
    assert "이미 열림 1" in window.statusBar().currentMessage()


def test_saving_one_tab_never_touches_another_open_file(
    qtbot,
    app_window,
    tmp_path: Path,
    dialogs,
    monkeypatch,  # noqa: ANN001
) -> None:
    window = app_window
    window.date_provider = lambda: date(2026, 9, 26)
    other = _open(qtbot, window, write_markdown(tmp_path / "기타.md", "# 기타\n"))
    dated_file = write_markdown(tmp_path / "보고서_20260926.md", "# 오늘 사본\n")
    dated_tab = _open(qtbot, window, dated_file)
    original = _open(qtbot, window, write_markdown(tmp_path / "보고서.md", "# 원본\n"))
    other.editor.insertPlainText("기타 수정 ")
    original.editor.insertPlainText("원본 수정 ")
    window.activate_session(original)

    # The dated target is open in another tab: no overwrite option, numbered save instead.
    dialogs.answer("번호 붙여 저장")
    assert window.save_document()
    # macOS ignores QMessageBox window titles; verify the user-visible explanation.
    assert "다른 탭에서 열려 있어 덮어쓸 수 없습니다" in dialogs.seen[-1][1]
    assert dated_file.name in dialogs.seen[-1][1]
    assert original.path.name == "보고서_20260926_2.md"
    assert dated_file.read_text(encoding="utf-8") == "# 오늘 사본\n"
    assert not dated_tab.is_modified()
    assert other.is_modified() and window.tab_title(other).endswith(" *")
    assert not original.is_modified() and not window.tab_title(original).endswith(" *")
    assert (tmp_path / "보고서.md").read_text(encoding="utf-8") == "# 원본\n"

    original.editor.insertPlainText("다시 ")
    dialogs.answer("취소")
    assert not window.save_document()
    assert original.is_modified()

    # Save As onto a file that another tab has open is refused and that tab is shown.
    monkeypatch.setattr(
        "markdowneditor.gui.main_window.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(other.path), ""),
    )
    assert not window.save_as()
    assert window.active_session is other
    assert other.path.read_text(encoding="utf-8") == "# 기타\n"
    assert len({session.key for session in window.sessions}) == len(window.sessions)


def test_closing_modified_tabs_offers_save_discard_and_cancel(
    qtbot,
    app_window,
    tmp_path: Path,
    dialogs,  # noqa: ANN001
) -> None:
    window = app_window
    window.date_provider = lambda: date(2026, 9, 26)
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# B\n"))
    c = _open(qtbot, window, write_markdown(tmp_path / "c.md", "# C\n"))
    d = _open(qtbot, window, write_markdown(tmp_path / "d.md", "# D\n"))
    for session in (a, b, c):
        session.editor.insertPlainText("수정 ")

    dialogs.answer("취소")
    assert not window.close_session(a)
    assert a in window.sessions and "'a.md'" in dialogs.seen[-1][1]
    dialogs.answer("저장 안 함")
    assert window.close_session(a)
    assert a not in window.sessions and a.closed
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "# A\n"

    dialogs.answer("저장")
    assert window.close_session(b)
    assert (tmp_path / "b_20260926.md").read_text(encoding="utf-8").startswith("수정 ")

    write_markdown(tmp_path / "c_20260926.md", "# 이미 있음\n")
    dialogs.answer("저장", "취소")  # save chosen, then the existing-file dialog is cancelled
    assert not window.close_session(c)
    assert c in window.sessions and c.is_modified()

    window.activate_session(d)
    window.close_tab_action.trigger()  # unmodified: closes without a dialog
    assert d not in window.sessions
    assert [session.path.name for session in window.sessions] == ["c.md"]


def test_window_close_cancel_keeps_every_tab(qtbot, app_window, tmp_path: Path, dialogs) -> None:  # noqa: ANN001
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# B\n"))
    a.editor.insertPlainText("수정 ")
    b.editor.insertPlainText("수정 ")
    dialogs.answer("저장 안 함", "취소")
    assert not window.close()
    assert window.isVisible()
    assert window.sessions == (a, b)
    assert a.is_modified() and b.is_modified() and not a.closed and not b.closed


def test_last_tab_close_shows_welcome_that_accepts_drops(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    assert window.close_active_tab()
    assert window.sessions == ()
    assert window.central_stack.currentWidget() is window.welcome
    assert window.editor is None and window.windowTitle() == "MarkdownEditor"
    assert not window.close_tab_action.isEnabled()
    assert not window.markdown_actions.actions_by_command["bold"].isEnabled()
    assert window.welcome_recent.count() >= 1

    target = _dnd_target(window.welcome)
    assert target is window  # the welcome page itself does not accept drops
    dropped = write_markdown(tmp_path / "새 문서 (1).md", "# 새 문서\n")
    enter, drop = send_drag_and_drop(target, file_mime([dropped]))
    assert enter.isAccepted() and drop.isAccepted()
    qtbot.waitUntil(lambda: len(window.sessions) == 1, timeout=10_000)
    assert window.active_session.path == dropped.resolve()
    assert window.close_tab_action.isEnabled()


def test_closing_a_tab_keeps_the_shared_request_guard(
    qtbot,
    app_window,
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    calls: list[object] = []
    original = QWebEngineProfile.setUrlRequestInterceptor

    def recording(profile, interceptor):  # noqa: ANN001, ANN202
        calls.append(interceptor)
        return original(profile, interceptor)

    monkeypatch.setattr(QWebEngineProfile, "setUrlRequestInterceptor", recording)
    window = app_window
    a = _open(
        qtbot,
        window,
        write_markdown(tmp_path / "a.md", "# A\n![원격](https://example.com/a.png)\n"),
    )
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# B\n"))
    guard = preview_module.shared_network_guard()
    assert a.preview.network_guard is guard and b.preview.network_guard is guard
    window.close_session(b)
    assert None not in calls
    assert preview_module._guard_installed
    assert not guard.allow_external_images
    window.external_action.setChecked(True)
    assert guard.allow_external_images and a.allow_external_images
    window.external_action.setChecked(False)
    assert not guard.allow_external_images


def test_late_render_results_never_reach_another_or_closed_tab(
    qtbot,
    app_window,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# 문서 A\n"))
    b = _open(qtbot, window, copy_sample(RFP, tmp_path / "rfp"))
    updates: list[int] = []
    original_update = a.preview.update_html
    a.preview.update_html = lambda html, revision, lines: (  # type: ignore[method-assign]
        updates.append(revision),
        original_update(html, revision, lines),
    )
    stale = a._revision
    a._revision += 1  # a newer render is pending, so the older result must be dropped
    a._renderer_finished(stale, b._last_render_result)
    assert updates == []
    a._revision = stale

    b.editor.insertPlainText("변경 ")
    b.start_render()
    window.close_session(b, confirm=False)
    qtbot.wait(1500)  # let any late thread-pool result, poll timer or JS callback arrive
    assert b.closed and b not in window.sessions
    window.activate_session(a)
    assert _h1(qtbot, a) == "문서 A"
    assert updates == []


def test_reordered_tabs_save_and_close_the_right_document(
    qtbot,
    app_window,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    window = app_window
    window.date_provider = lambda: date(2026, 9, 26)
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# B\n"))
    c = _open(qtbot, window, write_markdown(tmp_path / "c.md", "# C\n"))
    window.tabs.tabBar().moveTab(0, 2)  # a moves to the end: b, c, a
    assert [window.tabs.indexOf(s.page) for s in (b, c, a)] == [0, 1, 2]
    window.tabs.setCurrentIndex(2)
    assert window.active_session is a
    a.editor.insertPlainText("수정 ")
    assert window.save_document()
    assert (tmp_path / "a_20260926.md").exists()
    assert not (tmp_path / "b_20260926.md").exists() and not b.is_modified()
    window.tabs.setCurrentIndex(0)
    assert window.close_active_tab()
    assert window.sessions == (c, a) or set(window.sessions) == {c, a}


# ----- R4-03 drag and drop ------------------------------------------------------------------


def test_file_drop_on_editor_opens_tab_and_inserts_no_text(
    qtbot, app_window, tmp_path: Path
) -> None:  # noqa: ANN001
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# 문서 A\n"))
    dropped = write_markdown(tmp_path / "한글 폴더 (1)" / "끌어 놓은 문서.md", "# 끌어 놓은 문서\n")
    source_bytes = dropped.read_bytes()
    viewport = a.editor.viewport()
    assert _dnd_target(viewport) is viewport
    before = a.editor.raw_text()
    enter, drop = send_drag_and_drop(
        viewport, file_mime([dropped]), proposed=Qt.DropAction.MoveAction
    )
    assert enter.isAccepted() and drop.isAccepted()
    assert drop.dropAction() == Qt.DropAction.CopyAction  # never answer "moved" to Explorer
    qtbot.waitUntil(lambda: len(window.sessions) == 2, timeout=10_000)
    assert a.editor.raw_text() == before and not a.is_modified()
    assert "file:" not in a.editor.raw_text()
    assert window.active_session.path == dropped.resolve()
    assert dropped.read_bytes() == source_bytes


def test_file_drop_on_the_webengine_widget_keeps_the_preview_shell(
    qtbot,
    app_window,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    from PySide6.QtWebEngineCore import QWebEngineSettings

    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# 문서 A\n"))
    view = a.preview.view
    proxy = view.focusProxy()
    assert proxy is not None and _dnd_target(proxy) is proxy
    assert not a.preview.page.settings().testAttribute(
        QWebEngineSettings.WebAttribute.NavigateOnDropEnabled
    )
    shell_url = view.url().toString()
    dropped = write_markdown(tmp_path / "미리보기에 놓기.md", "# 미리보기에 놓기\n")
    enter, drop = send_drag_and_drop(proxy, file_mime([dropped]))
    assert enter.isAccepted() and drop.isAccepted()
    qtbot.waitUntil(lambda: len(window.sessions) == 2, timeout=10_000)
    qtbot.wait(300)
    assert view.url().toString() == shell_url
    window.activate_session(a)
    assert _h1(qtbot, a) == "문서 A"


def test_drop_on_tab_bar_opens_many_in_order_with_summary(
    qtbot,
    app_window,
    tmp_path: Path,
    dialogs,  # noqa: ANN001
) -> None:
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    b = write_markdown(tmp_path / "b 문서.md", "# B\n")
    c = write_markdown(tmp_path / "c (사본).markdown", "# C\n")
    image = tmp_path / "그림.png"
    image.write_bytes(b"\x89PNG\r\n")
    target = _dnd_target(window.tabs.tabBar())
    assert target is window
    mime = file_mime([b, image, "https://example.com/remote.md", c, a.path, b])
    enter, drop = send_drag_and_drop(target, mime)
    assert enter.isAccepted() and drop.isAccepted()
    qtbot.waitUntil(lambda: len(window.sessions) == 3, timeout=10_000)
    assert [session.path.name for session in window.sessions] == ["a.md", b.name, c.name]
    assert window.active_session is a  # last item in drop order was the already-open file
    message = window.statusBar().currentMessage()
    assert "열림 2" in message and "이미 열림 1" in message and "건너뜀 2" in message
    assert dialogs.seen == []  # something opened, so no warning dialog


def test_invalid_drop_inserts_nothing_and_explains(
    qtbot, app_window, tmp_path: Path, dialogs
) -> None:  # noqa: ANN001
    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    image = tmp_path / "그림.png"
    image.write_bytes(b"\x89PNG\r\n")
    before = a.editor.raw_text()
    enter, drop = send_drag_and_drop(a.editor.viewport(), file_mime([image, tmp_path]))
    # Rejected at DragEnter (forbidden cursor); Qt then never delivers the Drop.
    assert not enter.isAccepted() and not drop.isAccepted()
    message = window.statusBar().currentMessage()
    assert "열 수 없는 항목" in message and "그림.png(마크다운 파일이 아님)" in message
    qtbot.wait(100)
    assert dialogs.seen == []  # a hint, not a modal dialog
    assert a.editor.raw_text() == before and not a.is_modified()
    assert len(window.sessions) == 1


def test_text_and_link_drags_into_editor_keep_default_behaviour(
    qtbot,
    app_window,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    from PySide6.QtCore import QUrl

    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    text_mime = QMimeData()
    text_mime.setText("끌어온 글")
    send_drag_and_drop(a.editor.viewport(), text_mime)
    assert "끌어온 글" in a.editor.raw_text()
    link_mime = QMimeData()
    link_mime.setUrls([QUrl("https://example.com/page")])
    link_mime.setText("https://example.com/page")
    send_drag_and_drop(a.editor.viewport(), link_mime)
    assert "https://example.com/page" in a.editor.raw_text()
    assert len(window.sessions) == 1


def test_ctrl_tab_and_ctrl_w_from_editor_and_preview(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    from PySide6.QtGui import QKeySequence

    window = app_window
    a = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    b = _open(qtbot, window, write_markdown(tmp_path / "b.md", "# B\n"))
    window.activate_session(a)
    qtbot.keyClick(a.editor, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert window.active_session is b
    assert not a.is_modified() and a.editor.raw_text() == "# A\n"
    proxy = b.preview.view.focusProxy()
    qtbot.keyClick(proxy, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    # Keys on the WebEngine widget go through Chromium first and come back asynchronously.
    qtbot.waitUntil(lambda: window.active_session is a, timeout=5000)
    qtbot.keyClick(
        a.editor,
        Qt.Key.Key_Backtab,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.active_session is b
    assert QKeySequence("Ctrl+W") in window.close_tab_action.shortcuts()
    window.close_tab_action.trigger()
    assert window.sessions == (a,)
    shortcuts = _shortcuts(window)
    assert len(shortcuts) == len(set(shortcuts))


def test_theme_switch_keeps_status_and_marks_the_active_tab(
    qtbot,
    app_window,
    tmp_path: Path,  # noqa: ANN001
) -> None:
    window = app_window
    _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    status = window.statusBar()
    status.showMessage("정렬 메시지", 5000)
    assert not window.path_label.isVisible()
    window.dark_mode_action.setChecked(True)
    qtbot.wait(100)  # let Qt's queued re-layout run
    # The message stays and the path label stays hidden instead of being drawn under it.
    assert status.currentMessage() == "정렬 메시지"
    assert not window.path_label.isVisible()
    # The active tab is marked by an accent bar and bold text in both themes.
    assert "border-top: 3px solid #60a5fa" in window.tabs.tabBar().styleSheet()
    window.dark_mode_action.setChecked(False)
    qtbot.wait(100)
    assert not window.path_label.isVisible()
    assert "border-top: 3px solid #2563eb" in window.tabs.tabBar().styleSheet()
    assert "font-weight: bold" in window.tabs.tabBar().styleSheet()


def test_command_line_files_open_as_tabs(qtbot, tmp_path: Path) -> None:  # noqa: ANN001
    first = write_markdown(tmp_path / "첫째.md", "# 첫째\n")
    second = write_markdown(tmp_path / "둘째 문서.md", "# 둘째\n")
    settings = QSettings(str(tmp_path / "cli.ini"), QSettings.Format.IniFormat)
    window = MainWindow([first, second], settings=settings)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: len(window.sessions) == 2, timeout=20_000)
    assert [session.path for session in window.sessions] == [first.resolve(), second.resolve()]
    assert window.active_session.path == second.resolve()
    assert dated_path(first, date(2026, 9, 26)).name == "첫째_20260926.md"
    window.close()
