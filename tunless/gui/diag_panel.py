"""诊断面板：现代化深空微晶监控看板，实时反馈应用代理状态。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..diag import verdict as verdict_mod
from ..diag.clashpipe import ClashApi
from ..model import ProxyEndpoint
from . import theme_tokens as tok
from .modern_widgets import FluidButton, StatusPill

REFRESH_MS = 2000
BANNER_OBJECT = {"ok": "BannerOk", "leak": "BannerWarn", "idle": "BannerIdle", "dead": "BannerIdle"}


class DiagPanel(QWidget):
    """现代化网络连接诊断与分流看板。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pid: int | None = None
        self._endpoint: ProxyEndpoint | None = None
        self._clash: ClashApi | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # 顶部监控状态卡
        status_card = QFrame()
        status_card.setObjectName("GlassCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(8)

        head_row = QHBoxLayout()
        self.target_label = QLabel("未跟踪进程")
        self.target_label.setObjectName("CardTitle")
        head_row.addWidget(self.target_label)

        self.pill = StatusPill("就绪", "neutral")
        head_row.addWidget(self.pill)
        head_row.addStretch(1)

        self.refresh_button = QPushButton("立即刷新")
        self.refresh_button.clicked.connect(self.refresh)
        head_row.addWidget(self.refresh_button)
        status_layout.addLayout(head_row)

        self.banner = QLabel("还没有正在跟踪的进程。点「用代理启动」或「诊断」开始。")
        self.banner.setObjectName("BannerIdle")
        self.banner.setWordWrap(True)
        status_layout.addWidget(self.banner)

        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        status_layout.addWidget(self.hint)

        layout.addWidget(status_card)

        # 实时连接表格卡片
        table_card = QFrame()
        table_card.setObjectName("GlassCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_layout.setSpacing(6)

        table_header = QLabel("活跃 TCP 链路捕获")
        table_header.setObjectName("CardSubtitle")
        table_layout.addWidget(table_header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["进程", "目标连接", "TCP 状态", "流量归属"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_layout.addWidget(self.table, 1)

        layout.addWidget(table_card, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------ 控制

    def watch(self, pid: int, endpoint: ProxyEndpoint, clash: ClashApi | None = None) -> None:
        self._pid = pid
        self._endpoint = endpoint
        self._clash = clash
        self.target_label.setText(f"跟踪进程 PID: {pid}")
        self.pill.set_status(f"PID {pid} 监控中", "brand")
        self.timer.start()
        self.refresh()

    def stop(self) -> None:
        self.timer.stop()
        self._pid = None
        self.target_label.setText("未跟踪进程")
        self.pill.set_status("已停止", "neutral")
        self.banner.setText("已停止跟踪。")
        self.banner.setObjectName("BannerIdle")
        self._restyle()
        self.table.setRowCount(0)

    def _restyle(self) -> None:
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        if self._pid is None or self._endpoint is None:
            return
        result = verdict_mod.diagnose(self._pid, self._endpoint, self._clash)

        self.banner.setText(result.summary)
        self.banner.setObjectName(BANNER_OBJECT.get(result.status, "BannerIdle"))
        self._restyle()
        self.hint.setText(result.hint)

        if result.status == "ok":
            self.pill.set_status("代理生效中", "success")
        elif result.status == "leak":
            self.pill.set_status("存在直连泄露", "warn")
        elif result.status == "dead":
            self.pill.set_status("进程已退出", "neutral")
        else:
            self.pill.set_status("等待连接", "brand")

        rows = (
            [(item, "经代理") for item in result.via_proxy]
            + [(item, "直连公网") for item in result.direct_public]
            + [(item, "本地/内网") for item in result.local]
        )
        self.table.setRowCount(len(rows))
        for index, (item, kind) in enumerate(rows):
            values = [item.get("process", "?"), item.get("remote", "?"), item.get("state", "?"), kind]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if kind == "经代理":
                    cell.setForeground(Qt.GlobalColor.green)
                elif kind == "直连公网":
                    cell.setForeground(Qt.GlobalColor.yellow)
                else:
                    cell.setForeground(Qt.GlobalColor.lightGray)
                self.table.setItem(index, column, cell)

        if result.status == "dead":
            self.timer.stop()
