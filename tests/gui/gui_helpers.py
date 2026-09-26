from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QWidget

SURVEY = "설문지_기업 인공지능 활용 실태조사.md"
RFP = "차세대무역플랫폼 구축 사업 1단계 제안요청서.md"


def sample_root() -> Path:
    return Path(__file__).resolve().parents[2] / "samples"


def copy_sample(name: str, destination: Path) -> Path:
    """Copy a read-only sample with its _assets/_validation folders into ``destination``."""
    source = sample_root() / name
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    shutil.copy2(source, target)
    for suffix in ("_assets", "_validation"):
        folder = source.with_name(f"{source.stem}{suffix}")
        if folder.is_dir():
            shutil.copytree(folder, destination / folder.name, dirs_exist_ok=True)
    return target


def write_markdown(path: Path, text: str = "# 문서\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def open_scratch_document(qtbot, window, tmp_path: Path, text: str = "# 문서\n") -> Path:  # noqa: ANN001
    """The editor exists per tab now, so controls are exercised on an opened document."""
    path = write_markdown(tmp_path / "scratch.md", text)
    with qtbot.waitSignal(window.render_completed, timeout=20_000):
        assert window.open_document(path)
    return path


def file_mime(items: Iterable[Path | str]) -> QMimeData:
    """Build drag data like Explorer does: local paths become file URLs, strings stay URLs."""
    urls = [
        QUrl.fromLocalFile(str(item)) if isinstance(item, Path) else QUrl(item) for item in items
    ]
    mime = QMimeData()
    mime.setUrls(urls)
    return mime


def send_drag_and_drop(
    widget: QWidget,
    mime: QMimeData,
    *,
    proposed: Qt.DropAction = Qt.DropAction.CopyAction,
) -> tuple[QDragEnterEvent, QDropEvent]:
    """Deliver DragEnter, DragMove and Drop to one concrete widget (not the main window)."""
    point = QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2))
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(
        point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    enter.setDropAction(proposed)
    QApplication.sendEvent(widget, enter)
    move = QDragMoveEvent(
        point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    move.setDropAction(proposed)
    QApplication.sendEvent(widget, move)
    drop = QDropEvent(
        QPointF(point), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    drop.setDropAction(proposed)
    QApplication.sendEvent(widget, drop)
    return enter, drop
