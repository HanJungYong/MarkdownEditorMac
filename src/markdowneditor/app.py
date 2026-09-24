from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MarkdownEditor Windows GUI")
    parser.add_argument("file", nargs="?", help="열 Markdown 파일")
    parser.add_argument("--disable-gpu", action="store_true", help="QtWebEngine GPU 비활성화")
    parser.add_argument("--version", action="version", version="MarkdownEditor 0.1.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.disable_gpu:
        current = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        if "--disable-gpu" not in current:
            os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{current} --disable-gpu".strip()

    from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
    from PySide6.QtWidgets import QApplication

    from markdowneditor.gui.fonts import register_pretendard_fonts

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("MarkdownEditor")
    application.setApplicationVersion("0.1.0")
    application.setOrganizationName("OpenAI-Cowork")
    register_pretendard_fonts()

    translator = QTranslator(application)
    translation_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Korean), "qtbase", "_", translation_dir):
        application.installTranslator(translator)

    from markdowneditor.gui.main_window import MainWindow

    initial = Path(args.file).resolve() if args.file else None
    window = MainWindow(initial)
    window.show()
    result = application.exec()
    window.preview.shutdown()
    window.deleteLater()
    application.processEvents()
    return result
