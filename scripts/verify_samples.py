from __future__ import annotations

# ruff: noqa: E402
import argparse
import hashlib
import json
import os
import shutil
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

from PySide6.QtCore import QCoreApplication, QEventLoop, QSettings, Qt, QTimer

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from markdowneditor.core.file_io import load_document
from markdowneditor.core.links import inspect_links
from markdowneditor.core.naming import dated_path
from markdowneditor.core.renderer import render_markdown
from markdowneditor.gui.fonts import DEFAULT_FONT_SIZE, FONT_FAMILY
from markdowneditor.gui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = [
    {
        "key": "survey",
        "path": ROOT / "Samples" / "설문지_기업 인공지능 활용 실태조사.md",
        "sha256": "199c443b79e03fbe4c080cbd71addb0af559232607c8c03303f808bb974ea506",
        "tables": 23,
        "images": 0,
        "headings": 10,
    },
    {
        "key": "proposal",
        "path": ROOT / "Samples" / "차세대무역플랫폼 구축 사업 1단계 제안요청서.md",
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

    application = QApplication.instance() or QApplication(sys.argv[:1])
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
            window.close()
            window.deleteLater()
            application.processEvents()

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
        mermaid_window.close()
        mermaid_window.deleteLater()
        application.processEvents()

        security_copy = temp_root / "security.md"
        shutil.copy2(ROOT / "tests" / "fixtures" / "security.md", security_copy)
        security_window = isolated_window(temp_root, "security")
        security_window.show()
        security_stats, _ = wait_for_render(
            security_window, lambda: security_window.open_document(security_copy)
        )
        security_screen = screenshots / f"{stamp}_security.png"
        if capture_window(security_window, security_screen):
            screenshot_paths.append(security_screen)
        blocked_requests = security_window.preview.network_guard.blocked_requests
        security_window.close()
        security_window.deleteLater()
        application.processEvents()

        indentation_window = isolated_window(temp_root, "indentation")
        indentation_window.editor.setEnabled(True)
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
        indentation_window.close()
        indentation_window.deleteLater()
        application.processEvents()

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

    screenshots_ok = len(screenshot_paths) == 5 and all(
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

    counts = Counter(item["status"] for item in results)
    if counts["FAIL"]:
        overall = "FAIL"
    elif any(counts[key] for key in ("WARN", "NOT_CHECKED", "BASELINE_CHANGED")):
        overall = "WARN"
    else:
        overall = "PASS"
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "overall_status": overall,
        "status_counts": dict(counts),
        "application": "MarkdownEditor 0.1.0",
        "samples": [str(item["path"]) for item in SAMPLES],
        "results": results,
    }
    json_path = reports / f"verification_{stamp}.json"
    md_path = reports / f"verification_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# MarkdownEditor 샘플 검증 보고서",
        "",
        f"- 생성: {report['generated_at']}",
        f"- 전체 상태: **{overall}**",
        f"- 상태 집계: `{json.dumps(dict(counts), ensure_ascii=False)}`",
        "",
        "| ID | 검사 | 상태 | 결과 |",
        "|---|---|---|---|",
    ]
    for item in results:
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
    return report, md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MarkdownEditor 실제 샘플 인수 검증")
    parser.add_argument("--visual-confirmed", action="store_true")
    parser.add_argument("--visual-note", default="")
    return parser.parse_args()


def main() -> int:
    report, md_path, json_path = run(parse_args())
    print(f"전체 상태: {report['overall_status']}")
    print(f"보고서: {md_path}")
    print(f"JSON: {json_path}")
    print(f"상태 집계: {json.dumps(report['status_counts'], ensure_ascii=False)}")
    return 1 if report["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
