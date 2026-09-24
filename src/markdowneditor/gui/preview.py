from __future__ import annotations

import json
import os
import secrets
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from markdowneditor.gui.fonts import DEFAULT_FONT_SIZE, font_face_css


class PreviewBridge(QObject):
    link_requested = Signal(str)
    render_completed = Signal(object)
    message_reported = Signal(str)
    shell_ready = Signal()
    scroll_changed = Signal(float)
    scroll_source_line_changed = Signal(float)

    @Slot(str)
    def openLink(self, target: str) -> None:  # noqa: N802
        self.link_requested.emit(target)

    @Slot(str)
    def renderComplete(self, raw: str) -> None:  # noqa: N802
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = {"error": "미리보기 통계를 해석하지 못했습니다."}
        self.render_completed.emit(value)

    @Slot(str)
    def reportMessage(self, message: str) -> None:  # noqa: N802
        self.message_reported.emit(message)

    @Slot()
    def shellReady(self) -> None:  # noqa: N802
        self.shell_ready.emit()

    @Slot(float)
    def scrollChanged(self, ratio: float) -> None:  # noqa: N802
        self.scroll_changed.emit(max(0.0, min(1.0, ratio)))

    @Slot(float)
    def scrollSourceLineChanged(self, line: float) -> None:  # noqa: N802
        self.scroll_source_line_changed.emit(max(1.0, line))


class NetworkGuard(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.allow_external_images = False
        self.blocked_requests = 0

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        url = info.requestUrl()
        if url.scheme().lower() in {"http", "https"} and not self.allow_external_images:
            self.blocked_requests += 1
            info.block(True)


class SafePreviewPage(QWebEnginePage):
    blocked_navigation = Signal(str)
    console_message = Signal(str)

    def acceptNavigationRequest(  # noqa: N802
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        if (
            is_main_frame
            and navigation_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        ):
            self.blocked_navigation.emit(url.toString())
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    def javaScriptConsoleMessage(  # noqa: N802
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        self.console_message.emit(f"{level.name}: {message} ({source_id}:{line_number})")


class PreviewWebView(QWebEngineView):
    font_zoom_requested = Signal(int)

    def wheelEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.font_zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class PreviewPane(QWidget):
    render_completed = Signal(object)
    link_requested = Signal(str)
    message_reported = Signal(str)
    scroll_ratio_changed = Signal(float)
    scroll_source_line_changed = Signal(float)
    sync_scroll_toggled = Signal(bool)
    sync_scroll_fix_requested = Signal()
    font_zoom_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = PreviewWebView(self)
        self.controls = QWidget(self)
        controls_layout = QHBoxLayout(self.controls)
        controls_layout.setContentsMargins(10, 0, 10, 0)
        self.sync_checkbox = QCheckBox("Sync Scroll", self.controls)
        self.sync_checkbox.setToolTip("편집기와 미리보기 스크롤을 양방향으로 동기화")
        controls_layout.addWidget(self.sync_checkbox)
        self.sync_fix_button = QPushButton("Sync Scroll 위치맞춤", self.controls)
        self.sync_fix_button.setObjectName("syncScrollFixButton")
        self.sync_fix_button.setToolTip("편집기의 첫 번째 보이는 줄에 미리보기 위치를 맞춥니다.")
        self.sync_fix_button.setEnabled(False)
        controls_layout.addWidget(self.sync_fix_button)
        controls_layout.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.controls)
        layout.addWidget(self.view)

        # The process-wide profile outlives every test/app window. A short-lived
        # profile can crash Chromium during QApplication teardown on Windows.
        self.profile = QWebEngineProfile.defaultProfile()
        self.network_guard = NetworkGuard(QApplication.instance())
        self.profile.setUrlRequestInterceptor(self.network_guard)
        self.page = SafePreviewPage(self.profile, self.view)
        self.view.setPage(self.page)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)

        self.bridge = PreviewBridge(self)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.bridge.render_completed.connect(self._emit_render_completed)
        self.bridge.link_requested.connect(self.link_requested)
        self.bridge.message_reported.connect(self.message_reported)
        self.bridge.shell_ready.connect(self._on_shell_ready)
        self.bridge.scroll_changed.connect(self.scroll_ratio_changed)
        self.bridge.scroll_source_line_changed.connect(self.scroll_source_line_changed)
        self.sync_checkbox.toggled.connect(self.sync_scroll_toggled)
        self.sync_fix_button.clicked.connect(lambda: self.sync_scroll_fix_requested.emit())
        self.view.font_zoom_requested.connect(self.font_zoom_requested)
        self.view.loadFinished.connect(self._on_load_finished)

        self.document_dir = Path.cwd()
        self.allow_external_images = False
        self.dark_mode = False
        self.font_size = DEFAULT_FONT_SIZE
        self._shell_ready = False
        self._pending: tuple[str, int, int] | None = None
        self._last_revision = 0
        self._reported_revisions: set[int] = set()
        self.diagnostics: dict[str, object] = {}
        self._shut_down = False

    def set_document_directory(self, directory: str | Path) -> None:
        target = Path(directory).resolve()
        if target == self.document_dir and self._shell_ready:
            return
        self.document_dir = target
        self.reload_shell()

    def set_external_images(self, enabled: bool) -> None:
        self.allow_external_images = enabled
        self.network_guard.allow_external_images = enabled
        self.reload_shell()

    def set_control_height(self, height: int) -> None:
        self.controls.setFixedHeight(max(32, height))

    def set_dark_mode(self, enabled: bool) -> None:
        if self.dark_mode == enabled:
            return
        self.dark_mode = enabled
        self.reload_shell()

    def set_markdown_font_size(self, size: int) -> None:
        self.font_size = size
        self.view.setZoomFactor(size / DEFAULT_FONT_SIZE)

    def set_scroll_ratio(self, ratio: float) -> None:
        bounded = max(0.0, min(1.0, ratio))
        self.page.runJavaScript(
            "window.markdownEditorSetScrollRatio && "
            f"window.markdownEditorSetScrollRatio({bounded}, false);"
        )

    def set_sync_fix_enabled(self, enabled: bool) -> None:
        self.sync_fix_button.setEnabled(enabled)

    def align_to_source_line(
        self,
        line: int,
        total_lines: int,
        fallback_ratio: float,
        callback=None,  # noqa: ANN001
    ) -> None:  # noqa: ANN001
        script = (
            "window.markdownEditorAlignToSourceLine ? "
            f"window.markdownEditorAlignToSourceLine({max(1, line)}, "
            f"{max(1, total_lines)}, {max(0.0, min(1.0, fallback_ratio))}) : null"
        )
        if callback is None:
            self.page.runJavaScript(script)
        else:

            def decoded(value: object) -> None:
                if isinstance(value, str):
                    try:
                        callback(json.loads(value))
                    except json.JSONDecodeError:
                        callback(None)
                else:
                    callback(value)

            self.page.runJavaScript(f"JSON.stringify({script})", decoded)

    def reload_shell(self) -> None:
        self._shell_ready = False
        nonce = secrets.token_urlsafe(18)
        package_assets = files("markdowneditor").joinpath("assets")
        css_url = QUrl.fromLocalFile(
            str(package_assets.joinpath("preview", "preview.css"))
        ).toString()
        js_url = QUrl.fromLocalFile(
            str(package_assets.joinpath("preview", "preview.js"))
        ).toString()
        mermaid_url = QUrl.fromLocalFile(
            str(package_assets.joinpath("vendor", "mermaid", "mermaid.min.js"))
        ).toString()
        theme = "dark" if self.dark_mode else "light"
        embedded_fonts = font_face_css()
        remote_img = " https:" if self.allow_external_images else ""
        csp = (
            f"default-src 'none'; script-src 'nonce-{nonce}' qrc: file:; "
            "style-src file: 'unsafe-inline'; "
            f"img-src file: data:{remote_img}; font-src file: data:; "
            "connect-src 'none'; object-src 'none'; frame-src 'none'; "
            "base-uri 'none'; form-action 'none'"
        )
        shell = f"""<!doctype html>
<html lang="ko" data-theme="{theme}"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style nonce="{nonce}">{embedded_fonts}</style>
<link rel="stylesheet" href="{css_url}">
<title>MarkdownEditor 미리보기</title></head>
<body><main id="content"><p id="empty">마크다운 파일을 열어 주세요.</p></main>
<script nonce="{nonce}" src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script nonce="{nonce}" src="{mermaid_url}"></script>
<script nonce="{nonce}" src="{js_url}"></script>
</body></html>"""
        base = QUrl.fromLocalFile(str(self.document_dir) + os.sep)
        self.view.setHtml(shell, base)

    @Slot()
    def _on_shell_ready(self) -> None:
        self._shell_ready = True
        if self._pending is not None:
            html_value, revision, total_lines = self._pending
            self._pending = None
            self.update_html(html_value, revision, total_lines)

    @Slot(bool)
    def _on_load_finished(self, success: bool) -> None:
        self.diagnostics["loadFinished"] = success

        def inspected(value: object) -> None:
            if isinstance(value, dict):
                self.diagnostics.update(value)
                if value.get("update") == "function" and not self._shell_ready:
                    self._on_shell_ready()

        self.page.runJavaScript(
            "({update:typeof window.markdownEditorUpdate, "
            "channel:typeof window.QWebChannel, mermaid:typeof window.mermaid, "
            "transport:typeof window.qt})",
            inspected,
        )

    def update_html(self, html_value: str, revision: int, total_lines: int) -> None:
        self._last_revision = revision
        if not self._shell_ready:
            self._pending = (html_value, revision, total_lines)
            return

        def after_ratio(value: object) -> None:
            ratio = value if isinstance(value, int | float) else 0.0
            script = (
                "window.markdownEditorUpdate("
                f"{json.dumps(html_value, ensure_ascii=False)}, {float(ratio)}, "
                f"{revision}, {max(1, total_lines)});"
            )
            self.page.runJavaScript(script)
            QTimer.singleShot(750, lambda: self._poll_render(revision, 0))

        self.page.runJavaScript(
            "window.markdownEditorScrollRatio ? window.markdownEditorScrollRatio() : 0", after_ratio
        )

    @Slot(object)
    def _emit_render_completed(self, value: object) -> None:
        if isinstance(value, dict):
            revision = int(value.get("revision", 0))
            if revision in self._reported_revisions:
                return
            self._reported_revisions.add(revision)
        self.render_completed.emit(value)

    def _poll_render(self, revision: int, attempt: int) -> None:
        if revision in self._reported_revisions or revision != self._last_revision:
            return

        def received(value: object) -> None:
            if (
                isinstance(value, dict)
                and int(value.get("revision", 0)) == revision
                and not value.get("busy", True)
            ):
                self._emit_render_completed(value)
            elif attempt < 40:
                QTimer.singleShot(250, lambda: self._poll_render(revision, attempt + 1))

        self.request_stats(received)

    def request_stats(self, callback) -> None:  # noqa: ANN001
        self.page.runJavaScript(
            "window.markdownEditorStats ? window.markdownEditorStats() : null", callback
        )

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.view.stop()
        self.page.setWebChannel(None)
        self.profile.setUrlRequestInterceptor(None)
        self.page.deleteLater()
        self.view.deleteLater()
