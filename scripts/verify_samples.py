from __future__ import annotations

# ruff: noqa: E402
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QMimeData,
    QPoint,
    QPointF,
    QSettings,
    Qt,
    QTimer,
    QUrl,
)

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
    QGuiApplication,
    QTextCursor,
)
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from markdowneditor.core.file_io import load_document
from markdowneditor.core.links import inspect_links
from markdowneditor.core.naming import dated_path
from markdowneditor.core.renderer import render_markdown
from markdowneditor.gui import preview as preview_module
from markdowneditor.gui.fonts import DEFAULT_FONT_SIZE, FONT_FAMILY
from markdowneditor.gui.main_window import MainWindow
from markdowneditor.gui.preview import shared_network_guard

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    {
        "key": "survey",
        "path": ROOT / "samples" / "설문지_기업 인공지능 활용 실태조사.md",
        "sha256": "199c443b79e03fbe4c080cbd71addb0af559232607c8c03303f808bb974ea506",
        "tables": 23,
        "images": 0,
        "headings": 10,
    },
    {
        "key": "proposal",
        "path": ROOT / "samples" / "차세대무역플랫폼 구축 사업 1단계 제안요청서.md",
        "sha256": "7af22c18bcffc0bedf3868ba39c5261c1c06f03636005fa17b9c3f289ea93895",
        "tables": 238,
        "images": 7,
        "headings": 61,
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_render(
    window: MainWindow,
    action: Callable[[], Any],
    timeout_ms: int = 30_000,
) -> tuple[dict[str, Any] | None, float]:
    loop = QEventLoop()
    received: list[dict[str, Any]] = []

    def completed(value: object) -> None:
        if isinstance(value, dict):
            received.append(value)
            loop.quit()

    window.render_completed.connect(completed)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    started = time.perf_counter()
    action()
    timer.start(timeout_ms)
    loop.exec()
    elapsed = (time.perf_counter() - started) * 1000
    timer.stop()
    window.render_completed.disconnect(completed)
    return (received[-1] if received else None), elapsed


def copy_sample(source: Path, destination: Path) -> Path:
    target = destination / source.name
    shutil.copy2(source, target)
    for suffix in ("_assets", "_validation"):
        sibling = source.parent / f"{source.stem}{suffix}"
        if sibling.exists():
            shutil.copytree(sibling, destination / sibling.name)
    return target


def capture_window(window: MainWindow, path: Path) -> bool:
    window.showNormal()
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return False
    available = screen.availableGeometry()
    width = min(1200, max(900, available.width() - 80))
    height = min(800, max(650, available.height() - 80))
    window.setGeometry(available.x() + 40, available.y() + 40, width, height)
    window.raise_()
    window.activateWindow()
    QApplication.processEvents()
    QTest.qWait(350)
    image = window.grab()
    return not image.isNull() and image.save(str(path), "PNG")


def javascript_value(window: MainWindow, script: str, timeout_ms: int = 3000) -> object:
    loop = QEventLoop()
    received: list[object] = []

    def completed(value: object) -> None:
        received.append(value)
        loop.quit()

    window.preview.page.runJavaScript(script, completed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return received[-1] if received else None


def isolated_window(settings_root: Path, name: str) -> MainWindow:
    settings = QSettings(str(settings_root / f"{name}.ini"), QSettings.Format.IniFormat)
    return MainWindow(settings=settings)


def close_window(window: MainWindow) -> None:
    """Close a verification window without the unsaved-changes dialog (edits are on copies)."""
    for session in window.sessions:
        session.editor.document().setModified(False)
    window.close()
    window.deleteLater()
    QApplication.processEvents()


def open_scratch(window: MainWindow, path: Path, text: str) -> dict[str, Any] | None:
    """Open a small document; since 4차 the editor exists per tab, not before a file is open."""
    path.write_text(text, encoding="utf-8")
    stats, _ = wait_for_render(window, lambda: window.open_document(path))
    return stats


def add_result(
    results: list[dict[str, Any]],
    test_id: str,
    title: str,
    status: str,
    reason: str,
    evidence: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    results.append(
        {
            "id": test_id,
            "title": title,
            "status": status,
            "reason": reason,
            "evidence": evidence or [],
            "metrics": metrics or {},
        }
    )


EXTRA_SAMPLES = [
    ROOT / "samples" / "2.AI기반 불공정거래 대응체계_제안요청서.md",
    ROOT / "samples" / "KT DS_케이뱅크_GPU 플랫폼 구축_제안서_GPT_OpenShift AI_20260803.md",
]


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 15_000) -> bool:
    deadline = time.perf_counter() + timeout_ms / 1000
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        QTest.qWait(25)
    return bool(predicate())


def open_tab(window: MainWindow, path: Path, timeout_ms: int = 30_000) -> Any:
    """Open ``path`` as a tab and wait until *that* tab's preview finished rendering."""
    if not window.open_document(path):
        raise RuntimeError(f"탭을 열지 못했습니다: {path}")
    session = window.active_session
    if session is None or not wait_until(lambda: session.preview_render_ready, timeout_ms):
        raise RuntimeError(f"미리보기 렌더가 끝나지 않았습니다: {path}")
    return session


def _run_js(page_call: Callable[[Callable[[object], None]], None], timeout_ms: int) -> object:
    loop = QEventLoop()
    received: list[object] = []

    def completed(value: object) -> None:
        received.append(value)
        loop.quit()

    page_call(completed)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return received[-1] if received else None


def session_stats(session: Any) -> dict[str, Any]:
    # Nested JS objects do not survive runJavaScript's QVariant conversion reliably,
    # so the stats travel as a JSON string (the same way the preview bridge sends them).
    raw = session_js(
        session,
        "JSON.stringify(window.markdownEditorStats ? window.markdownEditorStats() : null)",
    )
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError:
        value = None
    return value if isinstance(value, dict) else {}


def session_js(session: Any, script: str, timeout_ms: int = 3000) -> object:
    return _run_js(lambda done: session.preview.page.runJavaScript(script, done), timeout_ms)


class ScriptedDialogs:
    """Answer modal dialogs in order during automated checks; unscripted ones are recorded."""

    STATIC = ("question", "warning", "critical", "information")

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.seen: list[tuple[str, str]] = []
        self.unexpected: list[tuple[str, str]] = []
        self._saved: dict[str, Any] = {}

    def answer(self, *texts: str) -> None:
        self.answers.extend(texts)

    def _exec(self, box: QMessageBox) -> int:
        self.seen.append((box.windowTitle(), box.text()))
        if not self.answers:
            self.unexpected.append((box.windowTitle(), box.text()))
            wanted = "취소"
        else:
            wanted = self.answers.pop(0)
        for button in box.buttons():
            if button.text() == wanted:
                button.click()
                return 0
        self.unexpected.append((box.windowTitle(), f"버튼 없음: {wanted}"))
        return 0

    def _static(self, _parent, title, text, *_args, **_kwargs):  # noqa: ANN001, ANN202
        self.seen.append((title, text))
        if self.answers and self.answers[0] in {"Yes", "No"}:
            answer = self.answers.pop(0)
            if answer == "Yes":
                return QMessageBox.StandardButton.Yes
            return QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.Ok

    def __enter__(self) -> ScriptedDialogs:
        self._saved = {name: getattr(QMessageBox, name) for name in ("exec", *self.STATIC)}
        QMessageBox.exec = lambda box: self._exec(box)  # type: ignore[method-assign]
        for name in self.STATIC:
            setattr(QMessageBox, name, staticmethod(self._static))
        return self

    def __exit__(self, *_exc: object) -> None:
        for name, value in self._saved.items():
            setattr(QMessageBox, name, value)


def append_text(session: Any, text: str) -> None:
    """Type at the end of the document so front matter stays intact in screenshots."""
    cursor = session.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    session.editor.setTextCursor(cursor)
    session.editor.insertPlainText(text)


def dnd_target(widget: QWidget) -> QWidget:
    """Qt's rule for real drags: the nearest widget (or ancestor) that accepts drops."""
    current = widget
    while current is not None and not current.acceptDrops():
        current = current.parentWidget()
    return current if current is not None else widget


def send_file_drop(
    widget: QWidget,
    items: list[Path | str],
    proposed: Qt.DropAction = Qt.DropAction.CopyAction,
) -> tuple[QDragEnterEvent, QDropEvent]:
    """Deliver DragEnter, DragMove and Drop to one concrete widget, like a Qt drag would."""
    mime = QMimeData()
    mime.setUrls(
        [QUrl.fromLocalFile(str(item)) if isinstance(item, Path) else QUrl(item) for item in items]
    )
    point = QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2))
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    buttons, modifiers = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(point, actions, mime, buttons, modifiers)
    enter.setDropAction(proposed)
    QApplication.sendEvent(widget, enter)
    move = QDragMoveEvent(point, actions, mime, buttons, modifiers)
    move.setDropAction(proposed)
    QApplication.sendEvent(widget, move)
    drop = QDropEvent(QPointF(point), actions, mime, buttons, modifiers)
    drop.setDropAction(proposed)
    QApplication.sendEvent(widget, drop)
    return enter, drop


def process_memory() -> dict[str, Any]:
    """Working set of this process and its QtWebEngineProcess children (PowerShell/CIM)."""
    pid = os.getpid()
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
        f"$c = @(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' | "
        "Where-Object { $_.Name -eq 'QtWebEngineProcess.exe' }); "
        "[pscustomobject]@{app=[math]::Round($p.WorkingSetSize/1MB,1); "
        "web=[math]::Round((($c | Measure-Object WorkingSetSize -Sum).Sum)/1MB,1); "
        "count=$c.Count} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        data = json.loads(completed.stdout.strip())
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return {
        "app_mb": data.get("app"),
        "webengine_mb": data.get("web") or 0,
        "webengine_processes": data.get("count"),
    }


def _result(ok: bool, pass_text: str, fail_text: str, **metrics: Any) -> dict[str, Any]:
    return {
        "status": "PASS" if ok else "FAIL",
        "reason": pass_text if ok else fail_text,
        "metrics": metrics,
    }


class FourthRound:
    """S24~S28 on copies of the samples: letter spacing, tabs, save/close, drops, regressions."""

    def __init__(self, temp_root: Path, screenshots: Path, stamp: str) -> None:
        self.work = temp_root / "fourth"
        self.work.mkdir()
        self.screenshot_dir = screenshots
        self.stamp = stamp
        self.screenshots: list[Path] = []
        self.copies: dict[str, Path] = {}
        for item in SAMPLES:
            folder = self.work / item["key"]
            folder.mkdir()
            self.copies[item["key"]] = copy_sample(item["path"], folder)
        self.extras: list[Path] = []
        for index, extra in enumerate(EXTRA_SAMPLES, start=1):
            if extra.exists():
                folder = self.work / f"extra{index}"
                folder.mkdir()
                self.extras.append(copy_sample(extra, folder))
        self.mermaid_copy = self.work / "mermaid_flowchart.md"
        shutil.copy2(ROOT / "tests" / "fixtures" / "mermaid_flowchart.md", self.mermaid_copy)
        self.windows: list[MainWindow] = []

    def window(self, name: str) -> MainWindow:
        window = isolated_window(self.work, name)
        window.show()
        self.windows.append(window)
        return window

    def shot(self, window: MainWindow, name: str) -> None:
        path = self.screenshot_dir / f"{self.stamp}_{name}.png"
        if capture_window(window, path):
            self.screenshots.append(path)

    def run(self) -> dict[str, dict[str, Any]]:
        checks: dict[str, dict[str, Any]] = {}
        for check_id, method in (
            ("S24", self.letter_spacing),
            ("S25", self.document_tabs),
            ("S26", self.save_and_close),
            ("S27", self.drops),
            ("S28", self.regressions),
        ):
            try:
                checks[check_id] = method()
            except Exception as exc:  # noqa: BLE001 - a crashed check is a failed check
                checks[check_id] = {
                    "status": "FAIL",
                    "reason": f"검사 중 예외가 발생했습니다: {type(exc).__name__}: {exc}",
                    "metrics": {},
                }
            finally:
                for window in self.windows:
                    close_window(window)
                self.windows.clear()
        return checks

    def letter_spacing(self) -> dict[str, Any]:
        window = self.window("spacing")
        survey = open_tab(window, self.copies["survey"])
        proposal = open_tab(window, self.copies["proposal"])
        tabs = [survey, proposal]
        larger = window.letter_spacing_larger_action
        smaller = window.letter_spacing_smaller_action
        view_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "보기(&V)")
        labels_ok = (
            larger.text() == "글간격 크게"
            and smaller.text() == "글간격 작게"
            and {larger, smaller} <= set(view_menu.actions())
        )
        self.shot(window, "spacing_100")
        larger.trigger()
        up_ok = all(s.editor.font().letterSpacing() == 105 for s in tabs)
        up_ok = up_ok and window.letter_spacing_label.text() == "간격 105%"
        smaller.trigger()
        down_ok = all(s.editor.font().letterSpacing() == 100 for s in tabs)
        for _ in range(20):
            larger.trigger()
        upper_ok = window.letter_spacing == 150 and not larger.isEnabled() and smaller.isEnabled()
        area = proposal.editor.line_number_area
        line_ok = (
            area.font().letterSpacing() == 100
            and area.width() >= QFontMetrics(area.font()).horizontalAdvance("9999")
            and proposal.editor.viewport().geometry().left() > area.geometry().right()
        )
        self.shot(window, "spacing_150")
        for _ in range(20):
            smaller.trigger()
        lower_ok = window.letter_spacing == 80 and not smaller.isEnabled() and larger.isEnabled()
        window.set_letter_spacing(115)
        preview_spacing = session_js(survey, "getComputedStyle(document.body).letterSpacing")
        window.adjust_font_size(1)
        window.dark_mode_action.setChecked(True)
        scratch_path = self.work / "새 탭.md"
        scratch_path.write_text("# 새 탭\n", encoding="utf-8")
        scratch = open_tab(window, scratch_path)
        keep_ok = all(
            s.editor.font().letterSpacing() == 115
            and s.editor.font().pointSize() == window.font_size
            for s in (*tabs, scratch)
        )
        window.dark_mode_action.setChecked(False)
        window.adjust_font_size(-1)
        window.settings.sync()
        restored = MainWindow(
            settings=QSettings(window.settings.fileName(), QSettings.Format.IniFormat)
        )
        restore_ok = restored.letter_spacing == 115
        restore_ok = restore_ok and restored.letter_spacing_label.text() == "간격 115%"
        close_window(restored)
        ok = all((labels_ok, up_ok, down_ok, upper_ok, lower_ok, line_ok, keep_ok, restore_ok))
        ok = ok and preview_spacing in {"normal", "0px"}
        return _result(
            ok,
            "보기 메뉴의 글간격 크게·작게가 모든 탭 편집기를 "
            "5%씩 바꾸고 80~150%에서 멈추며, 150%에서도 "
            "4자리 줄 번호가 잘리지 않았습니다. 미리보기 "
            "자간은 그대로이고 글자 크기·다크 모드·새 탭과 "
            "다시 실행 뒤에도 유지되었습니다.",
            "글간격 동작 중 기준을 충족하지 못한 항목이 있습니다.",
            menu_labels=labels_ok,
            step_up=up_ok,
            step_down=down_ok,
            upper_bound=upper_ok,
            lower_bound=lower_ok,
            line_numbers_at_150=line_ok,
            kept_after_font_theme_new_tab=keep_ok,
            restored_from_settings=restore_ok,
            preview_letter_spacing=preview_spacing,
        )

    def document_tabs(self) -> dict[str, Any]:
        window = self.window("tabs")
        memory = {"0": process_memory()}
        open_ms: dict[str, float] = {}
        sessions: list[Any] = []
        paths = [self.copies["survey"], self.copies["proposal"], *self.extras]
        for count, path in enumerate(paths, start=1):
            started = time.perf_counter()
            sessions.append(open_tab(window, path))
            open_ms[str(count)] = round((time.perf_counter() - started) * 1000, 1)
            memory[str(count)] = process_memory()
        survey, proposal = sessions[0], sessions[1]
        pairs = ((survey, self.copies["survey"]), (proposal, self.copies["proposal"]))
        survey_stats = session_stats(survey)
        proposal_stats = session_stats(proposal)
        content_ok = all(s.editor.raw_text() == load_document(p).text for s, p in pairs)
        folders_ok = all(s.preview.document_dir == p.parent.resolve() for s, p in pairs)
        titles_ok = all(
            window.tab_title(s) == p.name
            and window.tabs.tabToolTip(window.tabs.indexOf(s.page)) == str(s.path)
            for s, p in pairs
        )
        render_ok = (
            survey_stats.get("tables") == 23
            and proposal_stats.get("tables") == 238
            and proposal_stats.get("imagesLoaded") == 7
        )
        count_before = window.tabs.count()
        window.activate_session(proposal)
        window.open_document(self.copies["survey"])
        reopen_ok = window.tabs.count() == count_before and window.active_session is survey
        self.shot(window, "tabs_survey")
        append_text(proposal, "탭 격리 확인 ")
        isolation_ok = (
            proposal.is_modified()
            and not survey.is_modified()
            and window.tab_title(proposal).endswith(" *")
            and not window.tab_title(survey).endswith(" *")
        )
        window.activate_session(proposal)
        wait_until(lambda: proposal.preview_render_ready)
        self.shot(window, "tabs_proposal")
        self.tabs_window = window
        self.tab_sessions = sessions
        self.windows.remove(window)  # kept open for S26
        ok = all((content_ok, folders_ok, titles_ok, render_ok, reopen_ok, isolation_ok))
        return _result(
            ok,
            f"두 인수 샘플과 추가 자료를 탭 {len(sessions)}개로 동시에 열었고, "
            "탭별 원문·미리보기(표 23/238, 이미지 7)·기준 폴더·제목·수정 상태가 분리되었으며, "
            "같은 파일을 다시 열면 탭을 "
            "새로 만들지 않고 기존 탭을 활성화했습니다.",
            "다중 탭 격리 기준 중 충족하지 못한 항목이 있습니다.",
            content=content_ok,
            folders=folders_ok,
            titles=titles_ok,
            render={
                "survey_tables": survey_stats.get("tables"),
                "proposal_tables": proposal_stats.get("tables"),
                "proposal_images_loaded": proposal_stats.get("imagesLoaded"),
            },
            reopen_activates_existing=reopen_ok,
            modified_isolation=isolation_ok,
            open_to_render_ms_by_tab_count=open_ms,
            memory_by_tab_count=memory,
        )

    def save_and_close(self) -> dict[str, Any]:
        window = self.tabs_window
        self.windows.append(window)
        survey, proposal = self.tab_sessions[0], self.tab_sessions[1]
        today = date.today()
        with ScriptedDialogs() as dialogs:
            append_text(survey, "설문 수정 ")
            window.activate_session(proposal)
            original_bytes = self.copies["proposal"].read_bytes()
            saved_ok = window.save_document() and not proposal.is_modified()
            saved_ok = saved_ok and dated_path(self.copies["proposal"], today).exists()
            saved_ok = saved_ok and self.copies["proposal"].read_bytes() == original_bytes
            other_kept = survey.is_modified() and window.tab_title(survey).endswith(" *")
            dated_survey = dated_path(self.copies["survey"], today)
            dated_survey.write_bytes(self.copies["survey"].read_bytes())
            dated_tab = open_tab(window, dated_survey)
            window.activate_session(survey)
            dialogs.answer("번호 붙여 저장")
            conflict_ok = (
                window.save_document()
                and survey.path.name == f"{dated_survey.stem}_2{dated_survey.suffix}"
                and dated_survey.read_bytes() == self.copies["survey"].read_bytes()
                and any(title == "다른 탭에서 열려 있는 파일" for title, _ in dialogs.seen)
            )
            append_text(survey, "다시 ")
            dialogs.answer("취소")
            cancel_ok = not window.close_session(survey) and survey in window.sessions
            dialogs.answer("저장 안 함")
            discard_ok = window.close_session(survey) and survey not in window.sessions
            append_text(proposal, "종료 확인 ")
            append_text(dated_tab, "종료 확인 ")
            remaining = len(window.sessions)
            dialogs.answer("저장 안 함", "취소")
            app_cancel_ok = not window.close() and window.isVisible()
            app_cancel_ok = app_cancel_ok and len(window.sessions) == remaining
            unexpected = list(dialogs.unexpected)
        for session in list(window.sessions):
            session.editor.document().setModified(False)
            window.close_session(session)
        welcome_ok = (
            window.central_stack.currentWidget() is window.welcome
            and window.editor is None
            and not window.close_tab_action.isEnabled()
        )
        self.shot(window, "welcome")
        self.welcome_window = window
        self.windows.remove(window)  # reused empty for S27
        ok = all((saved_ok, other_kept, conflict_ok, cancel_ok, discard_ok, app_cancel_ok))
        ok = ok and welcome_ok and not unexpected
        return _result(
            ok,
            "한 탭의 날짜 저장이 다른 탭의 수정 상태를 바꾸지 "
            "않았고, 다른 탭에 열린 날짜 파일은 덮어쓰지 "
            "않고 번호를 붙여 저장했으며, 수정 탭 닫기의 "
            "취소·저장 안 함, 앱 종료 중 취소, 마지막 탭을 "
            "닫은 뒤 안내 화면을 확인했습니다.",
            "탭 저장·닫기 기준 중 충족하지 못한 항목이 있습니다.",
            dated_save=saved_ok,
            other_tab_kept_modified=other_kept,
            open_tab_not_overwritten=conflict_ok,
            close_cancel=cancel_ok,
            close_discard=discard_ok,
            app_close_cancel=app_cancel_ok,
            welcome_after_last_tab=welcome_ok,
            unexpected_dialogs=unexpected,
        )

    def drops(self) -> dict[str, Any]:
        window = self.welcome_window
        self.windows.append(window)
        folder = self.work / "끌어놓기 폴더 (한글)"
        folder.mkdir()
        names = (
            "안내 화면에 놓기.md",
            "편집기에 놓기.md",
            "미리보기에 놓기.md",
            "넷째 문서.md",
            "다섯째 (사본).markdown",
        )
        docs = []
        for name in names:
            path = folder / name
            path.write_text(f"# {Path(name).stem}\n", encoding="utf-8")
            docs.append(path)
        image = folder / "그림.png"
        image.write_bytes(b"\x89PNG\r\n")
        before = {str(path): sha256(path) for path in docs}

        target = dnd_target(window.welcome)
        _enter, drop = send_file_drop(target, [docs[0]])
        welcome_ok = target is window and drop.isAccepted()
        welcome_ok = welcome_ok and wait_until(lambda: len(window.sessions) == 1)
        first = window.active_session
        wait_until(lambda: first.preview_render_ready)
        text_before = first.editor.raw_text()
        _enter, drop = send_file_drop(first.editor.viewport(), [docs[1]], Qt.DropAction.MoveAction)
        editor_ok = (
            drop.isAccepted()
            and drop.dropAction() == Qt.DropAction.CopyAction
            and wait_until(lambda: len(window.sessions) == 2)
            and first.editor.raw_text() == text_before
            and not first.is_modified()
        )
        second = window.active_session
        wait_until(lambda: second.preview_render_ready)
        proxy = second.preview.view.focusProxy()
        shell_url = second.preview.view.url().toString()
        preview_ok = proxy is not None and dnd_target(proxy) is proxy
        if preview_ok:
            _enter, drop = send_file_drop(proxy, [docs[2]])
            preview_ok = drop.isAccepted() and wait_until(lambda: len(window.sessions) == 3)
            preview_ok = preview_ok and second.preview.view.url().toString() == shell_url
        _enter, drop = send_file_drop(
            dnd_target(window.tabs.tabBar()),
            [docs[3], image, "https://example.com/remote.md", docs[4], docs[0], docs[3]],
        )
        message = ""
        multi_ok = drop.isAccepted() and wait_until(lambda: len(window.sessions) == 5)
        if multi_ok:
            message = window.statusBar().currentMessage()
            names_now = [session.path.name for session in window.sessions]
            multi_ok = names_now[-2:] == [docs[3].name, docs[4].name]
            multi_ok = multi_ok and all(
                part in message for part in ("열림 2", "이미 열림 1", "건너뜀 2")
            )
        editor = window.active_session.editor
        invalid_before = editor.raw_text()
        enter, _drop = send_file_drop(editor.viewport(), [image, folder])
        invalid_ok = (
            not enter.isAccepted()
            and editor.raw_text() == invalid_before
            and len(window.sessions) == 5
            and "열 수 없는 항목" in window.statusBar().currentMessage()
        )
        sources_ok = {str(path): sha256(path) for path in docs} == before
        ok = all((welcome_ok, editor_ok, preview_ok, multi_ok, invalid_ok, sources_ok))
        return _result(
            ok,
            "안내 화면·편집기 viewport·미리보기 렌더 "
            "위젯(focusProxy)·탭 표시줄에 놓은 한글·공백·괄호 "
            "경로의 마크다운이 새 탭으로 열렸고, 여러 "
            "파일·중복·무효 항목이 규칙대로 처리되었습니다. "
            "본문에 URL이 들어가지 않았고 미리보기 셸이 유지되었으며 항상 복사로 수락했습니다"
            "(합성 Qt 이벤트 경로 검증, 실제 Explorer 조작은 S29).",
            "끌어다 놓기 기준 중 충족하지 못한 항목이 있습니다.",
            welcome=welcome_ok,
            editor_viewport=editor_ok,
            webengine_focus_proxy=preview_ok,
            tab_bar_multi=multi_ok,
            tab_bar_status=message,
            invalid_rejected=invalid_ok,
            dropped_sources_unchanged=sources_ok,
        )

    def regressions(self) -> dict[str, Any]:
        window = self.window("regression")
        calls: list[object] = []
        original_set = QWebEngineProfile.setUrlRequestInterceptor

        def recording(profile: QWebEngineProfile, interceptor: object) -> None:
            calls.append(interceptor)
            original_set(profile, interceptor)

        QWebEngineProfile.setUrlRequestInterceptor = recording  # type: ignore[method-assign]
        try:
            mermaid = open_tab(window, self.mermaid_copy)
            proposal = open_tab(window, self.copies["proposal"])
            survey = open_tab(window, self.copies["survey"])
            headings = {
                "proposal": session_stats(proposal).get("headings"),
                "survey": session_stats(survey).get("headings"),
            }
            isolation_ok = headings == {"proposal": 61, "survey": 10}
            survey.preview.sync_checkbox.setChecked(True)
            sync_ok = window.sync_scroll_enabled and all(
                session.preview.sync_checkbox.isChecked() for session in window.sessions
            )
            survey.preview.sync_checkbox.setChecked(False)
            window.activate_session(proposal)
            fixed: list[object] = []
            window.sync_scroll_fixed.connect(fixed.append)
            proposal.preview.sync_fix_button.click()
            fix_ok = wait_until(lambda: bool(fixed), 5000) and isinstance(fixed[-1], dict)
            folder_ok = proposal.preview.document_dir == self.copies["proposal"].parent.resolve()
            window.adjust_font_size(1)
            font_ok = all(s.editor.font().pointSize() == window.font_size for s in window.sessions)
            window.adjust_font_size(-1)
            window.dark_mode_action.setChecked(True)
            window.activate_session(mermaid)
            wait_until(lambda: mermaid.preview_render_ready, 30_000)
            stats = session_stats(mermaid)
            contrast = stats.get("mermaidContrast") or {}
            mermaid_ok = (
                stats.get("mermaidSvg") == 3
                and stats.get("mermaidErrors") == 1
                and contrast.get("theme") == "dark"
                and float(contrast.get("minimumRatio", 0)) >= 4.5
            )
            theme_ok = all(s.editor.dark_mode and s.preview.dark_mode for s in window.sessions)
            self.shot(window, "tabs_dark")
            window.close_session(survey, confirm=False)
            guard_ok = None not in calls and preview_module._guard_installed
            guard_ok = guard_ok and shared_network_guard() is proposal.preview.network_guard
        finally:
            QWebEngineProfile.setUrlRequestInterceptor = original_set  # type: ignore[method-assign]
        ok = all((isolation_ok, sync_ok, fix_ok, folder_ok, font_ok, mermaid_ok, theme_ok))
        ok = ok and guard_ok
        return _result(
            ok,
            "탭 여러 개에서 탭별 렌더(제목 61/10개)가 섞이지 "
            "않았고, Sync Scroll 설정 공유와 위치맞춤, "
            "링크 기준 폴더, 글자 크기·다크 모드, Mermaid "
            "다크 대비가 정상이며, 탭을 닫아도 외부 요청 "
            "차단기가 유지되었습니다.",
            "탭 환경의 기존 기능 중 기준을 충족하지 못한 항목이 있습니다.",
            headings=headings,
            sync_scroll_shared=sync_ok,
            sync_fix=fix_ok,
            link_folder=folder_ok,
            font_size_all_tabs=font_ok,
            mermaid_dark=mermaid_ok,
            theme_all_tabs=theme_ok,
            request_guard_kept=guard_ok,
        )


def fourth_round_checks(temp_root: Path, screenshots: Path, stamp: str) -> dict[str, Any]:
    runner = FourthRound(temp_root, screenshots, stamp)
    checks = runner.run()
    return {"checks": checks, "screenshots": runner.screenshots}


def run(args: argparse.Namespace) -> tuple[dict[str, Any], Path, Path]:
    reports = ROOT / "reports"
    screenshots = reports / "screenshots"
    reports.mkdir(exist_ok=True)
    screenshots.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results: list[dict[str, Any]] = []
    initial_hashes = {str(item["path"]): sha256(item["path"]) for item in SAMPLES}

    baseline_ok = all(
        item["path"].exists() and initial_hashes[str(item["path"])] == item["sha256"]
        for item in SAMPLES
    )
    add_result(
        results,
        "S01",
        "경로·원본 기준선",
        "PASS" if baseline_ok else "BASELINE_CHANGED",
        "지정된 두 경로와 SHA-256이 기준선과 일치합니다."
        if baseline_ok
        else "파일 누락 또는 SHA-256 변경을 확인했습니다.",
        [str(item["path"]) for item in SAMPLES],
        initial_hashes,
    )

    core: dict[str, Any] = {}
    for item in SAMPLES:
        document = load_document(item["path"], allow_large=True)
        render = render_markdown(document.text)
        links = inspect_links(document.text, document.path)
        core[item["key"]] = {"document": document, "render": render, "links": links}

    format_ok = all(
        value["document"].format.encoding == "utf-8"
        and not value["document"].format.bom
        and value["document"].format.newline == "\n"
        for value in core.values()
    )
    add_result(
        results,
        "S02",
        "열기·형식",
        "PASS" if format_ok else "FAIL",
        "두 샘플의 UTF-8·BOM 없음·LF 형식을 확인했습니다."
        if format_ok
        else "형식이 기준과 다릅니다.",
        metrics={
            key: {
                "encoding": value["document"].format.encoding,
                "bom": bool(value["document"].format.bom),
                "newline": value["document"].format.newline_label,
                "bytes": len(value["document"].original_bytes),
                "lines": value["document"].line_count,
            }
            for key, value in core.items()
        },
    )

    front_matter_samples = {
        key: value
        for key, value in core.items()
        if value["document"].text.lstrip("\ufeff").startswith("---\n")
    }
    front_ok = bool(front_matter_samples) and all(
        'class="front-matter"' in value["render"].html
        and "<h2>source_file" not in value["render"].html
        for value in front_matter_samples.values()
    )
    add_result(
        results,
        "S03",
        "front matter",
        "PASS" if front_ok else "FAIL",
        (
            "YAML이 있는 샘플은 접이식 문서 정보로 렌더링되고, YAML이 없는 샘플은 "
            "일반 Markdown으로 처리됩니다."
        )
        if front_ok
        else "YAML이 있는 샘플의 렌더링 오류이거나 검사 대상이 없습니다.",
        metrics={
            "with_front_matter": sorted(front_matter_samples),
            "without_front_matter": sorted(set(core) - set(front_matter_samples)),
        },
    )

    _application = QApplication.instance() or QApplication(sys.argv[:1])
    gui_stats: dict[str, dict[str, Any]] = {}
    open_times: dict[str, float] = {}
    screenshot_paths: list[Path] = []
    edit_elapsed = 0.0
    edit_reflected = False
    toolbar_ok = False
    save_ok = False
    no_edit_bytes_ok = False
    dark_mode_ok = False
    editor_font_ok = False
    light_editor_ok = False
    dark_editor_ok = False
    editor_scrollbar_ok = False
    zoom_ok = False
    sync_scroll_ok = False
    sync_scroll_fix_ok = False
    indentation_ok = False

    with tempfile.TemporaryDirectory(prefix="markdowneditor_verify_") as temporary:
        temp_root = Path(temporary)
        for item in SAMPLES:
            sample_dir = temp_root / item["key"]
            sample_dir.mkdir()
            copy = copy_sample(item["path"], sample_dir)
            original_copy = copy.read_bytes()
            window = isolated_window(temp_root, item["key"])
            window.show()
            stats, elapsed = wait_for_render(
                window,
                lambda path=copy, current_window=window: current_window.open_document(path),
            )
            open_times[item["key"]] = elapsed
            gui_stats[item["key"]] = stats or {}

            editor_style = window.editor.styleSheet()
            editor_font_ok = editor_font_ok or (
                FONT_FAMILY.lower() in window.editor.font().family().lower()
                and window.editor.font().pointSize() == DEFAULT_FONT_SIZE
                and not window.editor.extraSelections()
            )
            light_editor_ok = light_editor_ok or (
                not window.editor.dark_mode and "#ffffff" in editor_style
            )
            editor_scrollbar_ok = editor_scrollbar_ok or (
                "QScrollBar:vertical" in editor_style
                and "#f2f4f7" in editor_style
                and "#98a2b3" in editor_style
            )

            if item["key"] == "proposal":
                dark_stats, _ = wait_for_render(
                    window,
                    lambda current_window=window: current_window.dark_mode_action.setChecked(True),
                )
                theme = javascript_value(window, "document.documentElement.dataset.theme")
                dark_mode_ok = bool(
                    dark_stats and theme == "dark" and window.dark_mode and window.preview.dark_mode
                )
                dark_editor_ok = window.editor.dark_mode and "#050607" in window.editor.styleSheet()

                window.set_font_size(DEFAULT_FONT_SIZE)
                window.adjust_font_size(1)
                zoom_ok = (
                    window.editor.font().pointSize() == DEFAULT_FONT_SIZE + 1
                    and abs(
                        window.preview.view.zoomFactor()
                        - (DEFAULT_FONT_SIZE + 1) / DEFAULT_FONT_SIZE
                    )
                    < 0.01
                )
                window.adjust_font_size(-1)

                window.preview.sync_checkbox.setChecked(True)
                editor_scroll = window.editor.verticalScrollBar()
                if editor_scroll.maximum() > 0:
                    editor_scroll.setValue(editor_scroll.maximum() // 2)
                    QTest.qWait(150)
                    editor_line = window.editor.first_visible_source_line()
                    preview_line = javascript_value(
                        window, "window.markdownEditorSourceLineAtTop()"
                    )
                    cursor_position = window.editor.textCursor().position()
                    javascript_value(window, "window.markdownEditorSetScrollRatio(0.8, true)")
                    QTest.qWait(250)
                    scrolled_preview_line = javascript_value(
                        window, "window.markdownEditorSourceLineAtTop()"
                    )
                    scrolled_editor_line = window.editor.first_visible_source_line()
                    sync_scroll_ok = bool(
                        isinstance(preview_line, int | float)
                        and isinstance(scrolled_preview_line, int | float)
                        and abs(float(preview_line) - editor_line) <= 3
                        and abs(float(scrolled_preview_line) - scrolled_editor_line) <= 4
                        and window.editor.textCursor().position() == cursor_position
                    )

                    window.preview.sync_checkbox.setChecked(False)
                    editor_scroll.setValue(editor_scroll.maximum() // 3)
                    expected_line = window.editor.first_visible_source_line()
                    editor_value = editor_scroll.value()
                    button = window.preview.sync_fix_button
                    button.click()
                    QTest.qWait(150)
                    fixed_preview_line = javascript_value(
                        window, "window.markdownEditorSourceLineAtTop()"
                    )
                    sync_scroll_fix_ok = bool(
                        button.text() == "Sync Scroll 위치맞춤"
                        and button.isEnabled()
                        and isinstance(fixed_preview_line, int | float)
                        and abs(float(fixed_preview_line) - expected_line) <= 3
                        and editor_scroll.value() == editor_value
                        and "편집기 기준으로" in window.statusBar().currentMessage()
                    )

            screenshot = screenshots / f"{stamp}_{item['key']}.png"
            if capture_window(window, screenshot):
                screenshot_paths.append(screenshot)

            if item["key"] == "survey":
                output = dated_path(copy, date.today())
                no_edit_bytes_ok = (
                    window.save_to_path(output) and output.read_bytes() == original_copy
                )
            else:
                marker = "MarkdownEditor 자동 검증 문장"
                block = window.editor.document().findBlockByNumber(3000)
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                window.editor.setTextCursor(cursor)
                edit_stats, edit_elapsed = wait_for_render(
                    window,
                    lambda current_window=window, current_marker=marker: (
                        current_window.editor.insertPlainText(f" {current_marker}")
                    ),
                )
                reflected: list[bool] = []
                check_loop = QEventLoop()

                def checked(
                    value: object,
                    target: list[bool] = reflected,
                    loop: QEventLoop = check_loop,
                ) -> None:
                    target.append(bool(value))
                    loop.quit()

                window.preview.page.runJavaScript(
                    f"document.body.innerText.includes({json.dumps(marker, ensure_ascii=False)})",
                    checked,
                )
                QTimer.singleShot(3000, check_loop.quit)
                check_loop.exec()
                edit_reflected = bool(edit_stats) and bool(reflected and reflected[0])

                command_results: dict[str, bool] = {}

                def command_round_trip(
                    command: str,
                    expected: str,
                    *,
                    select_marker: bool = False,
                    current_window: MainWindow = window,
                    current_marker: str = marker,
                    results_map: dict[str, bool] = command_results,
                ) -> None:
                    before = current_window.editor.raw_text()
                    cursor = current_window.editor.textCursor()
                    if select_marker:
                        marker_start = before.index(current_marker)
                        cursor.setPosition(marker_start)
                        cursor.setPosition(
                            marker_start + len(current_marker), QTextCursor.MoveMode.KeepAnchor
                        )
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.End)
                    current_window.editor.setTextCursor(cursor)
                    current_window.apply_command(command)
                    inserted = expected in current_window.editor.raw_text()
                    current_window.editor.undo()
                    results_map[command] = inserted and current_window.editor.raw_text() == before

                command_round_trip("bold", f"**{marker}**", select_marker=True)
                command_round_trip("heading:2", "## ")
                command_round_trip("table", "| 열 1 | 열 2 | 열 3 |")
                command_round_trip("mermaid", "flowchart TD")
                toolbar_ok = all(command_results.values())
                output = dated_path(copy, date.today())
                save_ok = (
                    window.save_to_path(output)
                    and output.exists()
                    and copy.read_bytes() == original_copy
                )
            close_window(window)

        mermaid_copy = temp_root / "mermaid_flowchart.md"
        shutil.copy2(ROOT / "tests" / "fixtures" / "mermaid_flowchart.md", mermaid_copy)
        mermaid_window = isolated_window(temp_root, "mermaid")
        mermaid_window.show()
        mermaid_stats, _ = wait_for_render(
            mermaid_window, lambda: mermaid_window.open_document(mermaid_copy)
        )
        mermaid_screen = screenshots / f"{stamp}_mermaid_light.png"
        if capture_window(mermaid_window, mermaid_screen):
            screenshot_paths.append(mermaid_screen)
        mermaid_dark_stats, _ = wait_for_render(
            mermaid_window, lambda: mermaid_window.dark_mode_action.setChecked(True)
        )
        javascript_value(
            mermaid_window,
            "(() => { const item = document.querySelectorAll('.mermaid-rendered')[1]; "
            "if (!item) return false; item.scrollIntoView({block:'start'}); return true; })()",
        )
        QTest.qWait(150)
        mermaid_dark_screen = screenshots / f"{stamp}_mermaid_dark.png"
        if capture_window(mermaid_window, mermaid_dark_screen):
            screenshot_paths.append(mermaid_dark_screen)
        close_window(mermaid_window)

        security_copy = temp_root / "security.md"
        shutil.copy2(ROOT / "tests" / "fixtures" / "security.md", security_copy)
        security_window = isolated_window(temp_root, "security")
        security_window.show()
        blocked_before_security = shared_network_guard().blocked_requests
        security_stats, _ = wait_for_render(
            security_window, lambda: security_window.open_document(security_copy)
        )
        security_screen = screenshots / f"{stamp}_security.png"
        if capture_window(security_window, security_screen):
            screenshot_paths.append(security_screen)
        # The request guard is shared by every tab and window, so count only this document.
        blocked_requests = (
            security_window.preview.network_guard.blocked_requests - blocked_before_security
        )
        close_window(security_window)

        indentation_window = isolated_window(temp_root, "indentation")
        indentation_window.show()
        open_scratch(indentation_window, temp_root / "indentation.md", "# 들여쓰기\n")
        editor = indentation_window.editor

        editor.setPlainText("본문")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        QTest.keyClick(editor, Qt.Key.Key_Tab)
        tab_ok = editor.raw_text() == "본문  "

        newline_cases = (
            (True, "  일반", "  일반\n  "),
            (True, "> 인용", "> 인용\n> "),
            (True, "- 목록", "- 목록\n- "),
            (True, "9. 번호", "9. 번호\n10. "),
            (False, "  - 중첩", "  - 중첩\n- "),
        )
        newline_results: list[bool] = []
        for enabled, source, expected in newline_cases:
            indentation_window.indent_action.setChecked(enabled)
            editor.setPlainText(source)
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            newline_results.append(editor.raw_text() == expected)
        indentation_ok = tab_ok and all(newline_results)
        close_window(indentation_window)

        fourth = fourth_round_checks(temp_root, screenshots, stamp)
        screenshot_paths.extend(fourth["screenshots"])

    table_ok = all(
        gui_stats.get(item["key"], {}).get("tables") == item["tables"] for item in SAMPLES
    )
    add_result(
        results,
        "S04",
        "표",
        "PASS" if table_ok else "FAIL",
        "실제 DOM 표 수가 설문지 23개, 제안요청서 238개입니다."
        if table_ok
        else "DOM 표 수가 기준과 다릅니다.",
        metrics={key: value.get("tables") for key, value in gui_stats.items()},
    )

    proposal_stats = gui_stats.get("proposal", {})
    images_ok = (
        proposal_stats.get("images") == 7
        and proposal_stats.get("imagesLoaded") == 7
        and proposal_stats.get("imageErrors") == 0
    )
    add_result(
        results,
        "S05",
        "이미지",
        "PASS" if images_ok else "FAIL",
        "제안요청서 이미지 7개가 모두 로드되었습니다. 설문지는 이미지가 없습니다."
        if images_ok
        else "일부 이미지가 로드되지 않았습니다.",
        metrics={
            "proposal": {
                key: proposal_stats.get(key) for key in ("images", "imagesLoaded", "imageErrors")
            },
            "survey": "NOT_APPLICABLE",
        },
    )

    link_problems = {
        key: [
            asdict(item) for item in value["links"] if item.status in {"없음", "대상없음", "차단"}
        ]
        for key, value in core.items()
    }
    links_ok = not any(link_problems.values())
    add_result(
        results,
        "S06",
        "연결 요소",
        "PASS" if links_ok else "FAIL",
        "모든 로컬 연결 요소와 내부 앵커 대상이 존재합니다."
        if links_ok
        else "누락되거나 차단된 연결 요소가 있습니다.",
        metrics={key: len(value["links"]) for key, value in core.items()},
    )

    internal = [
        item
        for item in core["proposal"]["links"]
        if item.target.startswith("#") and item.status == "정상"
    ]
    add_result(
        results,
        "S07",
        "앵커·링크",
        "PASS" if len(internal) == 4 else "FAIL",
        f"제안요청서 내부 앵커 링크 {len(internal)}개의 대상을 확인했습니다.",
        metrics={"valid_internal_anchors": len(internal)},
    )

    add_result(
        results,
        "S08",
        "편집 반영",
        "PASS" if edit_reflected and edit_elapsed <= 1000 else "WARN",
        f"문서 중간 편집이 미리보기에 {edit_elapsed:.1f}ms 만에 반영되었습니다.",
        metrics={"edit_to_preview_ms": round(edit_elapsed, 3), "reflected": edit_reflected},
    )
    add_result(
        results,
        "S09",
        "툴바·실행 취소",
        "PASS" if toolbar_ok else "FAIL",
        "굵게·제목·표·Mermaid 삽입과 각각 한 단계 실행 취소를 확인했습니다."
        if toolbar_ok
        else "툴바 또는 실행 취소 결과가 다릅니다.",
    )

    mermaid_ok = bool(
        mermaid_stats
        and mermaid_stats.get("mermaidSvg") == 3
        and mermaid_stats.get("mermaidErrors") == 1
        and mermaid_dark_stats
        and mermaid_dark_stats.get("mermaidSvg") == 3
        and mermaid_dark_stats.get("mermaidErrors") == 1
    )
    add_result(
        results,
        "S10",
        "Mermaid fixture",
        "PASS" if mermaid_ok else "FAIL",
        (
            "라이트·다크 모드에서 flowchart 2개와 sequenceDiagram 1개는 SVG, "
            "잘못된 1개는 오류 상자로 격리되었습니다."
        )
        if mermaid_ok
        else "Mermaid 렌더 수가 기준과 다릅니다.",
        metrics={"light": mermaid_stats or {}, "dark": mermaid_dark_stats or {}},
    )
    add_result(
        results,
        "S11",
        "날짜 저장",
        "PASS" if save_ok and no_edit_bytes_ok else "FAIL",
        "임시 사본에서 날짜 파일을 생성하고 원본 및 무편집 바이트 동일성을 확인했습니다."
        if save_ok and no_edit_bytes_ok
        else "날짜 저장 또는 원본 보존 기준을 충족하지 못했습니다.",
        metrics={"edited_save": save_ok, "unedited_byte_equal": no_edit_bytes_ok},
    )

    security_ok = bool(
        security_stats
        and security_stats.get("scriptPwned") is False
        and security_stats.get("tables") == 1
        and blocked_requests == 0
    )
    add_result(
        results,
        "S12",
        "보안",
        "PASS" if security_ok else "FAIL",
        "문서 스크립트가 실행되지 않았고 안전한 표는 유지되며 외부 요청이 없었습니다."
        if security_ok
        else "보안 fixture 기준을 충족하지 못했습니다.",
        metrics={"dom": security_stats or {}, "blocked_network_requests": blocked_requests},
    )

    render_times = {key: round(value["render"].elapsed_ms, 3) for key, value in core.items()}
    performance_ok = (
        render_times["proposal"] <= 200
        and all(value <= 3000 for value in open_times.values())
        and edit_elapsed <= 1000
    )
    add_result(
        results,
        "S13",
        "성능",
        "PASS" if performance_ok else "WARN",
        "Python 렌더, 첫 미리보기, 편집 반영 시간을 실측했습니다.",
        metrics={
            "python_render_ms": render_times,
            "open_to_preview_ms": {key: round(value, 3) for key, value in open_times.items()},
            "edit_to_preview_ms": round(edit_elapsed, 3),
        },
    )

    # 5 legacy screens + 6 for 4차 (spacing 100/150, two tabs, welcome, dark tabs).
    screenshots_ok = len(screenshot_paths) == 11 and all(
        path.stat().st_size > 0 for path in screenshot_paths
    )
    visual_status = "PASS" if args.visual_confirmed and screenshots_ok else "NOT_CHECKED"
    visual_reason = (
        args.visual_note
        if visual_status == "PASS"
        else "스크린샷은 생성했지만 에이전트의 육안 확인 전이므로 통과로 판정하지 않습니다."
    )
    add_result(
        results,
        "S14",
        "화면",
        visual_status,
        visual_reason,
        [str(path) for path in screenshot_paths],
        {"screenshots_created": len(screenshot_paths)},
    )

    final_hashes = {str(item["path"]): sha256(item["path"]) for item in SAMPLES}
    unchanged = final_hashes == initial_hashes
    add_result(
        results,
        "S15",
        "원본 불변",
        "PASS" if unchanged else "FAIL",
        "검증 전후 프로젝트 Samples 원본 SHA-256이 동일합니다."
        if unchanged
        else "프로젝트 샘플 원본이 변경되었습니다.",
        metrics={"before": initial_hashes, "after": final_hashes},
    )

    add_result(
        results,
        "S16",
        "다크 모드",
        "PASS" if dark_mode_ok else "FAIL",
        "보기 메뉴에서 다크 모드를 켜고 Qt GUI와 미리보기 DOM의 dark 테마 적용을 확인했습니다."
        if dark_mode_ok
        else "다크 모드 적용 결과가 기준과 다릅니다.",
    )
    add_result(
        results,
        "S17",
        "편집기·Pretendard",
        "PASS" if editor_font_ok else "FAIL",
        "현재 줄 하이라이트 제거, Pretendard와 기본 12pt 적용을 확인했습니다."
        if editor_font_ok
        else "편집기 배경·하이라이트·폰트 기준을 충족하지 못했습니다.",
        metrics={"font_family": FONT_FAMILY, "default_font_size": DEFAULT_FONT_SIZE},
    )
    add_result(
        results,
        "S18",
        "동시 글자 크기",
        "PASS" if zoom_ok else "FAIL",
        "상태바 조절 시 편집기 글자 크기와 미리보기 확대율이 함께 변경되었습니다."
        if zoom_ok
        else "편집기와 미리보기 글자 크기가 함께 변경되지 않았습니다.",
    )
    add_result(
        results,
        "S19",
        "줄 번호 기반 Sync Scroll",
        "PASS" if sync_scroll_ok else "FAIL",
        (
            "원문 줄 번호를 기준으로 편집기→미리보기와 미리보기→편집기 양방향 "
            "동기화 및 편집 커서 보존을 확인했습니다."
        )
        if sync_scroll_ok
        else "줄 번호 기반 양방향 스크롤 동기화 결과가 기준과 다릅니다.",
    )
    editor_theme_ok = light_editor_ok and dark_editor_ok and editor_scrollbar_ok
    add_result(
        results,
        "S20",
        "편집기 테마·스크롤바",
        "PASS" if editor_theme_ok else "FAIL",
        (
            "편집기는 라이트 모드에서 흰색, 다크 모드에서 검은색이며 "
            "세로·가로 스크롤바는 동일한 라이트 색상입니다."
        )
        if editor_theme_ok
        else "편집기 테마 또는 스크롤바 색상 기준을 충족하지 못했습니다.",
    )
    add_result(
        results,
        "S21",
        "들여쓰기·스마트 줄바꿈",
        "PASS" if indentation_ok else "FAIL",
        (
            "Tab을 공백 2칸으로 입력하고, 들여쓰기 설정과 인용·목록·번호 자동 계속을 "
            "실제 키 입력으로 확인했습니다."
        )
        if indentation_ok
        else "들여쓰기 또는 Markdown 표식 자동 계속 결과가 기준과 다릅니다.",
    )
    add_result(
        results,
        "S22",
        "Sync Scroll 위치맞춤",
        "PASS" if sync_scroll_fix_ok else "FAIL",
        (
            "Sync Scroll을 끈 상태에서도 버튼이 편집기의 첫 번째 보이는 줄을 기준으로 "
            "미리보기를 강제 정렬하고 상태 메시지를 표시했습니다."
        )
        if sync_scroll_fix_ok
        else "강제 위치맞춤 버튼의 정렬 또는 상태 표시 결과가 기준과 다릅니다.",
    )
    mermaid_contrast = mermaid_dark_stats.get("mermaidContrast", {}) if mermaid_dark_stats else {}
    contrast_samples = mermaid_contrast.get("samples", [])
    mermaid_contrast_ok = bool(
        mermaid_contrast.get("theme") == "dark"
        and not mermaid_contrast.get("missing")
        and len(contrast_samples) == 5
        and isinstance(mermaid_contrast.get("minimumRatio"), int | float)
        and float(mermaid_contrast["minimumRatio"]) >= 4.5
        and all(float(sample.get("ratio", 0)) >= 4.5 for sample in contrast_samples)
    )
    add_result(
        results,
        "S23",
        "Mermaid 다크 모드 대비",
        "PASS" if mermaid_contrast_ok else "FAIL",
        (
            "flowchart·sequenceDiagram의 선, 화살표 머리, 라벨과 메시지 글자 대비가 "
            f"모두 4.5:1 이상입니다(최소 {float(mermaid_contrast['minimumRatio']):.2f}:1)."
        )
        if mermaid_contrast_ok
        else "Mermaid 다크 모드의 색상 대비 또는 검사 요소가 기준을 충족하지 못했습니다.",
        [str(mermaid_dark_screen)],
        mermaid_contrast,
    )

    titles = {
        "S24": "편집기 글간격",
        "S25": "다중 문서 탭",
        "S26": "탭 저장·닫기",
        "S27": "끌어다 놓기(Qt 이벤트 경로)",
        "S28": "탭 회귀",
    }
    fourth_screens = {
        "S24": ("spacing_100", "spacing_150"),
        "S25": ("tabs_survey", "tabs_proposal"),
        "S26": ("welcome",),
        "S28": ("tabs_dark",),
    }
    for check_id, title in titles.items():
        check = fourth["checks"].get(check_id) or {
            "status": "FAIL",
            "reason": "검사가 실행되지 않았습니다.",
            "metrics": {},
        }
        evidence = [
            str(path)
            for path in fourth["screenshots"]
            if any(path.stem.endswith(f"_{name}") for name in fourth_screens.get(check_id, ()))
        ]
        add_result(
            results, check_id, title, check["status"], check["reason"], evidence, check["metrics"]
        )
    explorer_ok = bool(args.explorer_drop_confirmed and args.explorer_drop_note)
    add_result(
        results,
        "S29",
        "실제 Explorer 끌어다 놓기",
        "PASS" if explorer_ok else "NOT_CHECKED",
        args.explorer_drop_note
        if explorer_ok
        else (
            "실제 Windows Explorer에서 편집기·미리보기로 "
            "끌어다 놓는 조작은 이 자동 검증에서 수행하지 "
            "않았습니다. 수행한 뒤 --confirm-explorer-drop으로 증거와 함께 기록해야 합니다."
        ),
        list(args.explorer_drop_evidence or []),
    )

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "application": "MarkdownEditor 0.1.0",
        "samples": [str(item["path"]) for item in SAMPLES],
        "results": results,
    }
    json_path = reports / f"verification_{stamp}.json"
    md_path = reports / f"verification_{stamp}.md"
    write_report(report, md_path, json_path)
    return report, md_path, json_path


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    """Recompute the overall status from the results and write the JSON and Markdown report."""
    counts = Counter(item["status"] for item in report["results"])
    if counts["FAIL"]:
        overall = "FAIL"
    elif any(counts[key] for key in ("WARN", "NOT_CHECKED", "BASELINE_CHANGED")):
        overall = "WARN"
    else:
        overall = "PASS"
    report["overall_status"] = overall
    report["status_counts"] = dict(counts)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# MarkdownEditor 샘플 검증 보고서",
        "",
        f"- 생성: {report['generated_at']}",
        f"- 전체 상태: **{overall}**",
        f"- 상태 집계: `{json.dumps(dict(counts), ensure_ascii=False)}`",
    ]
    for confirmation in report.get("confirmations", []):
        lines.append(f"- 사후 확인: {confirmation['check']} · {confirmation['confirmed_at']}")
    lines.extend(["", "| ID | 검사 | 상태 | 결과 |", "|---|---|---|---|"])
    for item in report["results"]:
        reason = item["reason"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item['id']} | {item['title']} | {item['status']} | {reason} |")
    lines.extend(
        [
            "",
            "## 상세 측정값",
            "",
            "```json",
            json.dumps(report, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")


def confirm_existing_report(
    report_path: Path, check_id: str, note: str, evidence: list[str]
) -> tuple[dict[str, Any], Path, Path]:
    """Record a human/agent confirmation on an existing report instead of re-running it.

    The confirmed files are exactly the ones this report lists (plus any extra evidence),
    and their SHA-256 values are stored, so the report cannot point at unseen screenshots.
    """
    json_path = report_path.with_suffix(".json")
    md_path = report_path.with_suffix(".md")
    report = json.loads(json_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["results"] if entry["id"] == check_id)
    files = [Path(path) for path in [*item.get("evidence", []), *evidence]]
    missing = [str(path) for path in files if not path.is_file()]
    if missing or not note.strip() or not files:
        raise SystemExit(f"확인할 증거 파일이나 소견이 없습니다: {missing or '(소견/파일 없음)'}")
    item["status"] = "PASS"
    item["reason"] = note.strip()
    item["evidence"] = [str(path) for path in files]
    item.setdefault("metrics", {})["confirmed_files_sha256"] = {
        str(path): sha256(path) for path in files
    }
    report.setdefault("confirmations", []).append(
        {"check": check_id, "confirmed_at": datetime.now().astimezone().isoformat()}
    )
    write_report(report, md_path, json_path)
    return report, md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MarkdownEditor 실제 샘플 인수 검증")
    parser.add_argument(
        "--visual-confirmed", action="store_true", help="(구 방식) 같은 실행에서 확인"
    )
    parser.add_argument("--visual-note", default="")
    parser.add_argument(
        "--confirm-visual",
        metavar="REPORT",
        help="이미 만든 보고서(.json/.md)의 S14 캡처를 열어 본 뒤 그 보고서에 확인 결과를 기록",
    )
    parser.add_argument("--explorer-drop-confirmed", action="store_true")
    parser.add_argument("--explorer-drop-note", default="")
    parser.add_argument("--explorer-drop-evidence", nargs="*", default=[])
    parser.add_argument(
        "--confirm-explorer-drop",
        metavar="REPORT",
        help="실제 Explorer 끌어다 놓기(S29)를 수행한 뒤 증거와 함께 기존 보고서에 기록",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.confirm_visual:
        report, md_path, json_path = confirm_existing_report(
            Path(args.confirm_visual), "S14", args.visual_note, []
        )
    elif args.confirm_explorer_drop:
        report, md_path, json_path = confirm_existing_report(
            Path(args.confirm_explorer_drop),
            "S29",
            args.explorer_drop_note,
            list(args.explorer_drop_evidence),
        )
    else:
        report, md_path, json_path = run(args)
    print(f"전체 상태: {report['overall_status']}")
    print(f"보고서: {md_path}")
    print(f"JSON: {json_path}")
    print(f"상태 집계: {json.dumps(report['status_counts'], ensure_ascii=False)}")
    return 1 if report["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
