"""系统托盘。"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..model import Profile
from .widgets import app_icon, profile_icon

MAX_RECENT = 5


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window) -> None:
        super().__init__(app_icon(), window)
        self.window_ref = window
        self.setToolTip("TunlessProxy —— 免 TUN 的按应用代理启动器")

        self.menu = QMenu()
        self.recent_menu = QMenu("最近的应用", self.menu)
        self.menu.addMenu(self.recent_menu)

        self.show_action = QAction("打开主窗口", self.menu)
        self.show_action.triggered.connect(window.bring_to_front)
        self.menu.addAction(self.show_action)

        self.shell_action = QAction("打开代理终端", self.menu)
        self.shell_action.triggered.connect(window.open_proxy_shell)
        self.menu.addAction(self.shell_action)

        self.test_action = QAction("测试代理连通性", self.menu)
        self.test_action.triggered.connect(window.test_endpoint)
        self.menu.addAction(self.test_action)

        self.menu.addSeparator()
        self.quit_action = QAction("退出", self.menu)
        self.quit_action.triggered.connect(window.quit_app)
        self.menu.addAction(self.quit_action)

        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        self.set_recent([])

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.window_ref.bring_to_front()

    def set_recent(self, profiles: list[Profile]) -> None:
        self.recent_menu.clear()
        if not profiles:
            placeholder = QAction("（还没有应用）", self.recent_menu)
            placeholder.setEnabled(False)
            self.recent_menu.addAction(placeholder)
            return
        ordered = sorted(profiles, key=lambda p: p.last_launched_at, reverse=True)[:MAX_RECENT]
        for profile in ordered:
            action = QAction(profile_icon(profile), profile.name, self.recent_menu)
            action.triggered.connect(
                lambda _checked=False, pid=profile.id: self.window_ref.launch_profile(pid)
            )
            self.recent_menu.addAction(action)

    def notify(self, title: str, message: str) -> None:
        self.showMessage(title, message, app_icon(), 4000)
