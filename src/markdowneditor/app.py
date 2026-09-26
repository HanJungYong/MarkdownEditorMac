from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MarkdownEditor macOS / Windows GUI")
    parser.add_argument(
        "files", nargs="*", metavar="file", help="열 Markdown 파일(여러 개면 각각 탭으로 엽니다)"
    )
    parser.add_argument("--disable-gpu", action="store_true", help="QtWebEngine GPU 비활성화")
    parser.add_argument("--version", action="version", version="MarkdownEditor 0.1.0")
    return parser


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    # Files and options may be mixed (e.g. several files dropped on the .bat plus a flag).
    return build_parser().parse_intermixed_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    if args.disable_gpu:
        current = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--disable-gpu" not in current:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{current} --disable-gpu".strip()

    from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
    from PySide6.QtWidgets import QApplication

    from markdowneditor.gui.file_open import MarkdownApplication
    from markdowneditor.gui.fonts import register_pretendard_fonts

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    application = QApplication.instance() or MarkdownApplication(sys.argv[:1])
    application.setApplicationName("MarkdownEditor")
    application.setApplicationVersion("0.1.0")
    application.setOrganizationName("OpenAI-Cowork")
    register_pretendard_fonts()

    translator = QTranslator(application)
    translation_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Korean), "qtbase", "_", translation_dir):
        application.installTranslator(translator)

    from markdowneditor.gui.main_window import MainWindow
    from markdowneditor.gui.preview import release_shared_network_guard

    initial = [Path(item).resolve() for item in args.files]
    window = MainWindow(initial or None)
    if isinstance(application, MarkdownApplication):
        application.set_window(window)
    window.show()
    result = application.exec()
    # Every tab owns a WebEngine page; release all of them (safe with zero tabs).
    window.shutdown_sessions()
    release_shared_network_guard()
    if isinstance(application, MarkdownApplication):
        application.set_window(None)
    window.deleteLater()
    application.processEvents()
    return result
