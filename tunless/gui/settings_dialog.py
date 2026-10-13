"""现代化深空微晶设置对话框 (Settings Dialog)。"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from .. import config
from ..launch import admin_winhttp, proc
from . import theme_tokens as tok
from .modern_widgets import GlassCard, StatusPill


class SettingsDialog(QDialog):
    """深空曜石流体材质设置对话框。"""

    def __init__(
        self,
        cfg: dict,
        endpoint,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("首选项与网络端点设置")
        self.setMinimumWidth(580)
        self.cfg = cfg
        self.endpoint = endpoint
        settings = config.settings(cfg)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        # 卡片全部放进滚动区：内容可能超过 800px 屏的可用高度，
        # 不滚动的话「确定 / 取消」会被挤出屏幕。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self._body = body

        # 卡片加在这一层（滚动区内部），按钮组仍然固定在底部
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # ---------------- 代理端点卡片
        ep_card = GlassCard()
        ep_layout = QVBoxLayout(ep_card)
        ep_layout.setContentsMargins(16, 14, 16, 14)
        ep_layout.setSpacing(10)

        ep_header = QHBoxLayout()
        ep_title = QLabel("代理端点 (Proxy Endpoint)")
        ep_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {tok.TEXT_PRIMARY};")
        ep_header.addWidget(ep_title)
        self.ep_pill = StatusPill(f"{endpoint.source}", "brand")
        ep_header.addWidget(self.ep_pill)
        ep_header.addStretch(1)
        ep_layout.addLayout(ep_header)

        form = QFormLayout()
        form.setSpacing(10)
        ep_settings = settings.get("endpoint", {})
        manual = ep_settings.get("manual") or {}

        self.auto_box = QCheckBox("自动探测（优先读取 Clash Verge 配置，再探活常见端口）")
        self.auto_box.setChecked(bool(ep_settings.get("autoDetect", True)))
        form.addRow(self.auto_box)

        self.host_edit = QLineEdit(
            str(manual.get("host") or ep_settings.get("host") or "127.0.0.1")
        )
        form.addRow("监听地址：", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(
            int(manual.get("port") or ep_settings.get("mixedPort") or 7897)
        )
        form.addRow("混合端口：", self.port_spin)

        self.detected_label = QLabel(
            f"当前探活状态：{endpoint.host}:{endpoint.mixed_port}（来源：{endpoint.source}）"
        )
        self.detected_label.setObjectName("Hint")
        form.addRow(self.detected_label)
        ep_layout.addLayout(form)
        root.addWidget(ep_card)

        # ---------------- 行为与外观选项卡片
        bh_card = GlassCard()
        bh_layout = QVBoxLayout(bh_card)
        bh_layout.setContentsMargins(16, 14, 16, 14)
        bh_layout.setSpacing(10)

        bh_title = QLabel("行为与外观偏好")
        bh_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {tok.TEXT_PRIMARY};")
        bh_layout.addWidget(bh_title)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("系统视觉主题："))
        self.theme_combo = QComboBox()
        cur_theme = str(settings.get("theme", tok.DEFAULT_THEME_ID))
        for tid, th in tok.THEMES.items():
            self.theme_combo.addItem(f"{th.name} ({tid})", tid)
            if tid == cur_theme:
                self.theme_combo.setCurrentIndex(self.theme_combo.count() - 1)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)
        bh_layout.addLayout(theme_row)

        self.compact_box = QCheckBox("以「轻量便携模式」启动（点确定后立即切换）")
        self.compact_box.setChecked(bool(settings.get("compactMode", False)))
        bh_layout.addWidget(self.compact_box)

        self.shortcut_box = QCheckBox("添加新应用时，自动在桌面生成独立代理快捷方式")
        self.shortcut_box.setToolTip(
            "生成在桌面，删起来也方便；旧版本留在开始菜单里的那一份会被顺手清理"
        )
        self.shortcut_box.setChecked(config.shortcuts_enabled(settings))
        bh_layout.addWidget(self.shortcut_box)
        root.addWidget(bh_card)

        # ---------------- 机器级 WinHTTP 卡片
        wh_card = GlassCard()
        wh_layout = QVBoxLayout(wh_card)
        wh_layout.setContentsMargins(16, 14, 16, 14)
        wh_layout.setSpacing(10)

        wh_header = QHBoxLayout()
        wh_title = QLabel("机器级 WinHTTP 全局代理（系统扩展，谨慎使用）")
        wh_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {tok.TEXT_PRIMARY};")
        wh_header.addWidget(wh_title)
        wh_header.addStretch(1)
        wh_layout.addLayout(wh_header)

        warn = QLabel(
            "部分只走 WinHTTP 的原生启动器在「零代码注入」前提下需靠机器级全局开关生效。"
            "启用需要管理员权限并影响整机网络；本程序已建立自动安全备份，可一键还原。"
        )
        warn.setWordWrap(True)
        warn.setObjectName("Hint")
        wh_layout.addWidget(warn)

        self.winhttp_status = QLabel()
        self.winhttp_status.setWordWrap(True)
        self.winhttp_status.setStyleSheet(f"color: {tok.TEXT_SECONDARY}; font-family: {tok.FONT_MONO}; font-size: 11px;")
        wh_layout.addWidget(self.winhttp_status)

        btn_row = QHBoxLayout()
        self.winhttp_apply = QPushButton("启用 WinHTTP 代理（需管理员）")
        self.winhttp_apply.clicked.connect(self._apply_winhttp)
        btn_row.addWidget(self.winhttp_apply)

        self.winhttp_reset = QPushButton("还原系统配置")
        self.winhttp_reset.clicked.connect(self._reset_winhttp)
        btn_row.addWidget(self.winhttp_reset)
        btn_row.addStretch(1)
        wh_layout.addLayout(btn_row)
        root.addWidget(wh_card)

        # ---------------- 目录快捷入口卡片
        # 所有生成物都在同一个数据目录里（程序同级 data\），所以这里只给一个入口，
        # 外加"程序装在不可写位置时退回了哪里"的说明。
        dir_card = GlassCard()
        dir_layout = QHBoxLayout(dir_card)
        dir_layout.setContentsMargins(16, 12, 16, 12)
        dir_layout.setSpacing(10)

        dir_label = QLabel("存储位置：")
        dir_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {tok.TEXT_PRIMARY};")
        dir_layout.addWidget(dir_label)

        open_data = QPushButton("打开数据目录")
        open_data.setToolTip(
            f"{config.DATA_DIR}\n\n"
            "配置、图标、L3 私有配置、日志都在这里；整个文件夹可删可拷。"
        )
        open_data.clicked.connect(lambda _=False, p=str(config.DATA_DIR): self._open(p))
        dir_layout.addWidget(open_data)

        data_hint = QLabel(self._data_dir_text())
        data_hint.setObjectName("Hint")
        data_hint.setToolTip(str(config.DATA_DIR))
        dir_layout.addWidget(data_hint, 1)
        root.addWidget(dir_card)

        root.addStretch(1)

        # 底部对话框按钮组（放在滚动区之外，始终可见）
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._refresh_winhttp_status()
        self._fit_to_screen()

    def _data_dir_text(self) -> str:
        """一句话说清数据放哪儿了（以及为什么不在程序旁边）。"""
        if config.DATA_DIR_SOURCE == "portable":
            return "全部生成物都在程序同级的 data\\ 里，删/导出只需处理这一个文件夹"
        if config.DATA_DIR_SOURCE == "env":
            return f"由 TUNLESS_DATA_DIR 指定：{config.DATA_DIR}"
        return (
            "程序所在位置不可写，已退回 %APPDATA%\\TunlessProxy —— "
            "想放到程序旁边，把程序移到可写目录即可"
        )

    def _fit_to_screen(self) -> None:
        """按内容高度与可用屏幕高度决定初始尺寸。

        卡片总高约 785px，768p 笔记本的可用高度只有 700 出头；直接 `resize` 成
        内容高度会让底部按钮跑到屏幕外，所以这里取「内容高度」与「可用高度 - 边距」
        的较小值，超出的部分交给滚动区。

        高度必须从滚动区**内容**的 sizeHint 取：QScrollArea 自身的 sizeHint 只反映
        视口，照着它 resize 会得到一个 408px 高、需要大量滚动的窄窗。
        """
        self._body.adjustSize()
        wanted = self._body.sizeHint().height() + 40 + 60  # 上下边距 + 按钮行
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry().height()
            wanted = min(wanted, max(480, available - 80))
        self.resize(max(580, self.sizeHint().width()), wanted)

    # ------------------------------------------------------------ 行为

    def _open(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _refresh_winhttp_status(self) -> None:
        text = admin_winhttp.show()
        self.winhttp_status.setText(text or "(无输出)")
        self.winhttp_apply.setEnabled(proc.is_elevated())
        if not proc.is_elevated():
            self.winhttp_apply.setToolTip("需要以管理员身份运行本程序")

    def _apply_winhttp(self) -> None:
        settings = config.settings(self.cfg)
        original = admin_winhttp.show()
        settings["winhttpBackup"] = original
        self.cfg["settings"] = settings
        config.save(self.cfg)
        ok, message = admin_winhttp.set_proxy(self.host_edit.text().strip(), self.port_spin.value())
        self._refresh_winhttp_status()
        if ok:
            QMessageBox.information(self, "已启用", "机器级 WinHTTP 代理已设置。")
        else:
            QMessageBox.warning(self, "设置失败", message)

    def _reset_winhttp(self) -> None:
        settings = config.settings(self.cfg)
        backup = settings.get("winhttpBackup") or ""
        ok, message = admin_winhttp.restore(
            backup, self.host_edit.text().strip(), self.port_spin.value()
        )
        self._refresh_winhttp_status()
        if ok:
            QMessageBox.information(self, "已还原", "机器级 WinHTTP 代理已还原。")
        else:
            QMessageBox.warning(self, "还原失败", message)

    # ------------------------------------------------------------ 结果

    def apply_to_config(self) -> None:
        settings = config.settings(self.cfg)
        endpoint = settings.setdefault("endpoint", {})
        endpoint["autoDetect"] = self.auto_box.isChecked()
        endpoint["host"] = self.host_edit.text().strip() or "127.0.0.1"
        endpoint["mixedPort"] = self.port_spin.value()
        if not self.auto_box.isChecked():
            endpoint["manual"] = {
                "host": endpoint["host"],
                "port": self.port_spin.value(),
            }
        else:
            endpoint["manual"] = None
        settings["generateShortcuts"] = self.shortcut_box.isChecked()
        settings["compactMode"] = self.compact_box.isChecked()
        settings["theme"] = self.theme_combo.currentData() or tok.DEFAULT_THEME_ID
        self.cfg["settings"] = settings
        config.save(self.cfg)
