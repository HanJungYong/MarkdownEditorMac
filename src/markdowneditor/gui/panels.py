from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDockWidget, QTreeWidget, QTreeWidgetItem, QWidget

from markdowneditor.core.links import LinkReference


class ProblemsDock(QDockWidget):
    line_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("연결 문제", parent)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["상태", "종류", "대상", "줄"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(self._activate)
        self.setWidget(self.tree)

    def set_links(self, links: list[LinkReference]) -> None:
        self.tree.clear()
        for link in links:
            item = QTreeWidgetItem([link.status, link.kind, link.target, str(link.line)])
            item.setData(0, 256, link.line)
            item.setToolTip(2, link.resolved or link.target)
            self.tree.addTopLevelItem(item)
        for column in range(4):
            self.tree.resizeColumnToContents(column)

    def _activate(self, item: QTreeWidgetItem) -> None:
        self.line_requested.emit(int(item.data(0, 256)))
