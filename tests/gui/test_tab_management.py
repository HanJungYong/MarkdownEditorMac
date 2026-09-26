from __future__ import annotations

from pathlib import Path

import pytest
from gui_helpers import write_markdown
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from markdowneditor.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


def _open(qtbot, window: MainWindow, path: Path):  # noqa: ANN001, ANN202
    assert window.open_document(path)
    session = window.active_session
    qtbot.waitUntil(lambda: session.preview_render_ready, timeout=30_000)
    return session


def _three_tabs(qtbot, window: MainWindow, tmp_path: Path):  # noqa: ANN001, ANN202
    return [
        _open(qtbot, window, write_markdown(tmp_path / f"{name}.md", f"# {name}\n"))
        for name in ("가", "나", "다")
    ]


def test_tab_context_menu_offers_close_location_and_path(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    first, second, third = _three_tabs(qtbot, window, tmp_path)
    opened: list[QUrl] = []
    window.external_opener = lambda url: not opened.append(url)
    menu = window.tab_context_menu(window.tabs.indexOf(second.page))
    assert menu is not None
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
    assert list(actions) == [
        "탭 닫기",
        "다른 탭 닫기",
        "모든 탭 닫기",
        "파일 위치 열기",
        "전체 경로 복사",
    ]

    actions["전체 경로 복사"].trigger()
    assert QApplication.clipboard().text() == str(second.path)
    actions["파일 위치 열기"].trigger()
    assert opened and Path(opened[-1].toLocalFile()) == second.path.parent

    actions["다른 탭 닫기"].trigger()
    assert window.sessions == (second,)
    assert window.active_session is second
    assert first.closed and third.closed
    single = window.tab_context_menu(0)
    assert not single.actions()[1].isEnabled()  # nothing else to close
    assert window.tab_context_menu(5) is None


def test_close_other_tabs_stops_at_the_first_cancel(
    qtbot,
    app_window,
    tmp_path: Path,
    dialogs,  # noqa: ANN001
) -> None:
    window = app_window
    first, second, third = _three_tabs(qtbot, window, tmp_path)
    first.editor.insertPlainText("수정 ")
    third.editor.insertPlainText("수정 ")
    dialogs.answer("취소")
    assert not window.close_other_sessions(second)
    assert window.sessions == (first, second, third)  # cancelled on the first tab in order
    dialogs.answer("저장 안 함", "저장 안 함")
    assert window.close_other_sessions(second)
    assert window.sessions == (second,)
    assert (tmp_path / "가.md").read_text(encoding="utf-8") == "# 가\n"


def test_close_all_tabs_from_the_file_menu(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    _three_tabs(qtbot, window, tmp_path)
    file_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "파일(&F)")
    texts = [action.text() for action in file_menu.actions()]
    assert texts.index("탭 닫기") < texts.index("다른 탭 닫기") < texts.index("모든 탭 닫기")
    window.close_all_action.trigger()
    assert window.sessions == ()
    assert window.central_stack.currentWidget() is window.welcome
    assert not window.close_all_action.isEnabled()
    assert not window.close_others_action.isEnabled()


def test_middle_click_closes_the_clicked_tab(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    first, second, third = _three_tabs(qtbot, window, tmp_path)
    tab_bar = window.tabs.tabBar()
    center = tab_bar.tabRect(window.tabs.indexOf(second.page)).center()
    qtbot.mouseClick(tab_bar, Qt.MouseButton.MiddleButton, pos=center)
    assert window.sessions == (first, third)
    assert second.closed


def test_letter_spacing_reset_returns_to_default(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    session = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    reset = window.letter_spacing_reset_action
    view_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "보기(&V)")
    assert reset in view_menu.actions() and reset.text() == "글간격 기본값"
    assert not reset.isEnabled()
    window.set_letter_spacing(130)
    assert reset.isEnabled()
    reset.trigger()
    assert window.letter_spacing == 100
    assert session.editor.font().letterSpacing() == pytest.approx(100)
    assert not reset.isEnabled()


def test_word_wrap_and_view_mode_are_remembered(qtbot, app_window, tmp_path: Path) -> None:  # noqa: ANN001
    window = app_window
    session = _open(qtbot, window, write_markdown(tmp_path / "a.md", "# A\n"))
    window.wrap_action.setChecked(False)
    window.view_mode_actions["editor"].trigger()
    assert window.view_mode == "editor"
    assert window.view_mode_actions["editor"].isChecked()
    assert not window.view_mode_actions["both"].isChecked()
    assert session.editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert session.left_panel.isVisible() and not session.preview.isVisible()

    window.settings.sync()
    settings = QSettings(window.settings.fileName(), QSettings.Format.IniFormat)
    restored = MainWindow(settings=settings)
    qtbot.addWidget(restored)
    restored.show()
    assert not restored.wrap_action.isChecked()
    assert restored.view_mode == "editor" and restored.view_mode_actions["editor"].isChecked()
    # In "편집만" the preview is hidden and Chromium pauses its animation frames, so the
    # render report arrives only once the preview is shown again.
    assert restored.open_document(write_markdown(tmp_path / "b.md", "# B\n"))
    new_tab = restored.active_session
    assert new_tab.editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert not new_tab.preview.isVisible()
    restored.view_mode_actions["both"].trigger()
    assert new_tab.preview.isVisible()
    qtbot.waitUntil(lambda: new_tab.preview_render_ready, timeout=30_000)
    restored.close()

    settings.setValue("view/mode", "없는 값")
    settings.sync()
    fallback = MainWindow(settings=settings)
    qtbot.addWidget(fallback)
    assert fallback.view_mode == "both"
    fallback.close()
