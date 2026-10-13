"""GUI 小工具：图标加载、路径省略、家族徽标。"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QFileIconProvider, QStyle

from .. import config
from ..model import Family, Profile

ICON_SIZE = 40


def elide_path(path: str, limit: int = 58) -> str:
    if len(path) <= limit:
        return path
    head = path[: limit // 2 - 2]
    tail = path[-(limit // 2 - 1):]
    return f"{head}…{tail}"


def family_badge(family: Family) -> str:
    return {
        Family.ELECTRON: "Electron",
        Family.WEBVIEW2: "WebView2",
        Family.JAVA: "Java",
        Family.NODE: "Node",
        Family.CLI: "命令行",
        Family.NATIVE: "原生",
        Family.UWP: "UWP",
        Family.UNKNOWN: "未知",
    }.get(family, "未知")


def profile_icon(profile: Profile) -> QIcon:
    cached = config.icon_path(profile.id)
    if cached.is_file():
        pixmap = QPixmap(str(cached))
        if not pixmap.isNull():
            return QIcon(pixmap)

    target = profile.spec.target
    if target and os.path.isfile(target) and QApplication.instance() is not None:
        provider = QFileIconProvider()
        from PyQt6.QtCore import QFileInfo

        icon = provider.icon(QFileInfo(target))
        if not icon.isNull():
            return icon

    app = QApplication.instance()
    if app is not None:
        return app.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
    return QIcon()


def profile_tooltip(profile: Profile) -> str:
    lines = [
        f"名称：{profile.name}",
        f"家族：{profile.spec.family.label}",
        f"目标：{profile.spec.target}",
        f"架构：{profile.spec.arch}    子系统：{profile.spec.subsystem}",
        f"启动次数：{profile.launch_count}",
    ]
    if profile.spec.family_evidence:
        lines.append("判定依据：" + "；".join(profile.spec.family_evidence))
    if profile.adopted_shortcut:
        lines.append(f"已接管快捷方式：{profile.adopted_shortcut}")
    return "\n".join(lines)


def icon_size() -> QSize:
    return QSize(ICON_SIZE, ICON_SIZE)


_APP_ICON: QIcon | None = None


def app_icon() -> QIcon:
    """程序自己的图标：现画一个，省得带二进制资源。"""
    global _APP_ICON
    if _APP_ICON is not None:
        return _APP_ICON

    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QBrush, QColor, QPainter, QPen

    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QBrush(QColor("#2563eb")))
    painter.setPen(QPen(QColor("#1d4ed8"), 2))
    painter.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 14, 14)

    painter.setPen(QPen(QColor("#ffffff"), 4))
    painter.drawEllipse(QRectF(17, 17, size - 34, size - 34))
    painter.drawLine(size // 2, 17, size // 2, size - 17)
    painter.drawLine(17, size // 2, size - 17, size // 2)
    painter.end()

    _APP_ICON = QIcon(pixmap)
    return _APP_ICON


def mono_font_family() -> str:
    return "Consolas"


__all__ = [
    "elide_path",
    "family_badge",
    "profile_icon",
    "profile_tooltip",
    "icon_size",
    "app_icon",
    "mono_font_family",
    "Qt",
    "Path",
]
