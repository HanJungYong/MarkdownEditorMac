from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from markdowneditor.gui.main_window import MainWindow


class DialogScript:
    """Answers modal dialogs in order so GUI tests never block on a window.

    ``answer("저장 안 함")`` clicks that button on the next ``QMessageBox.exec()``;
    ``answer("Yes")``/``answer("No")`` answer the next static ``question``/``warning`` that
    offers Yes/No. An unscripted blocking dialog fails the test instead of hanging.
    Informational warnings are recorded in ``seen`` and return immediately.
    """

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.seen: list[tuple[str, str]] = []

    def answer(self, *texts: str) -> None:
        self.answers.extend(texts)

    def exec_box(self, box: QMessageBox) -> int:
        self.seen.append((box.windowTitle(), box.text()))
        if not self.answers:
            raise AssertionError(f"예상하지 못한 대화상자: {box.windowTitle()} / {box.text()}")
        wanted = self.answers.pop(0)
        for button in box.buttons():
            if button.text() == wanted:
                button.click()
                return 0
        labels = [button.text() for button in box.buttons()]
        raise AssertionError(f"대화상자에 '{wanted}' 버튼이 없습니다: {labels}")

    def static(self, kind: str):  # noqa: ANN201
        def handler(_parent, title, text, buttons=None, *_args, **_kwargs):  # noqa: ANN001, ANN202
            self.seen.append((title, text))
            asks_yes_no = kind == "question" or (
                buttons is not None and buttons & QMessageBox.StandardButton.Yes
            )
            if not asks_yes_no:
                return QMessageBox.StandardButton.Ok
            if not self.answers:
                raise AssertionError(f"예상하지 못한 질문: {title} / {text}")
            wanted = self.answers.pop(0)
            return (
                QMessageBox.StandardButton.Yes if wanted == "Yes" else QMessageBox.StandardButton.No
            )

        return handler


@pytest.fixture(autouse=True)
def dialogs(monkeypatch: pytest.MonkeyPatch) -> DialogScript:
    script = DialogScript()
    monkeypatch.setattr(QMessageBox, "exec", lambda box: script.exec_box(box))
    for kind in ("question", "warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(script.static(kind)))
    return script


def _discard_all_changes(window: MainWindow) -> None:
    # Tests edit documents on purpose; closing must not stop at the unsaved-changes dialog.
    for session in window.sessions:
        session.editor.document().setModified(False)


@pytest.fixture
def app_window(qtbot, tmp_path: Path):  # noqa: ANN001
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    # pytest-qt closes registered widgets before fixture teardown runs, so the discard
    # must happen in before_close_func.
    qtbot.addWidget(window, before_close_func=_discard_all_changes)
    window.show()
    yield window
    _discard_all_changes(window)
    window.close()
    window.deleteLater()
    QApplication.processEvents()
