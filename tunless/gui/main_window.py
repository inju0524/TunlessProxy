"""主窗口：支持标准完整模式与极致紧凑的轻量便携模式 (Mini Launcher Mode)。

支持：
- 完整模式 (1180x760) / 极致轻量模式 (340x390) 一键双向无缝切换
- 4 套内置次世代液态玻璃主题 (深空曜石 / 超白水晶 / 极光幻彩 / 微晶雾面) 实时热加载与对比度适配
- 状态与偏好持久化
"""

from __future__ import annotations

import functools
import inspect
import os
import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon,
    QPainter, QPainterPath, QPen
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import APP_NAME, config, service
from ..detect import endpoint as endpoint_mod
from ..detect.lnk import is_supported_drop
from ..diag.clashpipe import ClashApi
from ..launch import proc, shortcuts
from ..model import Profile
from . import icons, theme_tokens as tok
from .detail_panel import DetailPanel
from .diag_panel import DiagPanel
from .drop_list import (
    ProfileListWidget, ROLE_PROFILE_FAMILY, ROLE_PROFILE_ICON,
    ROLE_PROFILE_ID, ROLE_PROFILE_NAME, ROLE_PROFILE_TARGET
)
from .modern_widgets import DropZoneIsland, FluidButton, GlassCard, IconButton, StatusPill
from .settings_dialog import SettingsDialog
from .title_mark import TitleMark
from .tray import TrayIcon
from .widgets import app_icon, profile_icon
from .workers import EndpointTestWorker

DEFAULT_THEME = tok.DEFAULT_THEME_ID

#: 顶栏高度。软件名换成三段式静态字标之后不再需要为光晕留白，回到原本的 46px；
#: check_layout.py 直接引这个常量做判据（"字标不许撑高顶栏"）。
HEADER_HEIGHT = 46


def guarded(slot):
    """给会落盘 / 解析 / 建快捷方式的槽加一道兜底。

    为什么必须有：PyQt6 里由 C++ 触发的槽若抛出未捕获异常，Qt 会直接 qFatal ——
    进程以 0xC0000409 中止，`sys.excepthook` 拦不住（只来得及写一行崩溃日志）。
    而这些槽会写 config.json、解析 .lnk、调 WScript.Shell，磁盘满 / 权限不足 /
    杀软占用都能让它们抛 OSError。宁可弹个错误框、保留原状态，也不能把整个
    程序带走 —— 用户还在用它管着别的应用。

    **包装器必须按原槽的签名裁掉多余参数**。`functools.wraps` 会让 PyQt 认为这个
    可调用对象接受 `*args`，于是 `QPushButton.clicked(bool)` / `QAction.triggered(bool)`
    自带的那个 `False` 会被原样传进来 —— 而 `open_settings()` 这类槽不收参数，
    一按「设置」「重新解析」就是 TypeError（第一版就是这么挂的：点按钮弹"操作未完成"）。
    """
    try:
        parameters = inspect.signature(slot).parameters.values()
        accepted = len(
            [
                p for p in parameters
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
        ) - 1  # 减去 self
        accepted = max(accepted, 0)
    except (TypeError, ValueError):  # 拿不到签名（极少见）时按原样转发
        accepted = None

    @functools.wraps(slot)
    def wrapper(self, *args, **kwargs):
        try:
            if accepted is None:
                return slot(self, *args, **kwargs)
            return slot(self, *args[:accepted], **kwargs)
        except Exception as exc:  # noqa: BLE001 - 这里就是要兜住一切
            message = f"{slot.__name__}: {type(exc).__name__}: {exc}"
            try:
                log = config.log_path("crash.log")
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 槽异常 {message}\n")
            except OSError:
                pass
            try:
                QMessageBox.warning(self, "操作未完成", f"这一步失败了，其他功能不受影响。\n\n{message}")
            except Exception:  # noqa: BLE001
                pass
            return None

    return wrapper



class CompactItemDelegate(QStyledItemDelegate):
    """轻量模式专属的超紧凑条目委托 (行高 40px，高对比度自适应)。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 40)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        th = tok.get_current_theme()
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)

        if is_selected:
            bg_color = tok.parse_color(th.brand_primary)
            bg_color.setAlpha(40 if th.is_dark else 35)
            border_color = tok.parse_color(th.brand_primary)
            border_w = 1.5
        elif is_hover:
            bg_color = tok.parse_color(th.bg_card_hover)
            border_color = tok.parse_color(th.border_hover)
            border_w = 1.0
        else:
            bg_color = tok.parse_color(th.bg_card)
            border_color = tok.parse_color(th.border_subtle)
            border_w = 1.0

        painter.fillPath(path, QBrush(bg_color))
        painter.setPen(QPen(border_color, border_w))
        painter.drawRoundedRect(rect, 8, 8)

        # 图标 (24x24)
        icon: QIcon = index.data(ROLE_PROFILE_ICON)
        icon_rect = QRectF(rect.x() + 8, rect.y() + (rect.height() - 24) / 2.0, 24, 24)
        if icon and not icon.isNull():
            pixmap = icon.pixmap(24, 24)
            painter.drawPixmap(int(icon_rect.x()), int(icon_rect.y()), pixmap)

        # 文本与胶囊
        text_x = rect.x() + 38
        name = index.data(ROLE_PROFILE_NAME) or ""
        family_str = index.data(ROLE_PROFILE_FAMILY) or ""

        # 右侧彩色小胶囊 (根据家族配色，彻底告别纯黑色块)
        badge_w = len(family_str) * 9 + 12
        badge_rect = QRectF(rect.right() - badge_w - 6, rect.y() + (rect.height() - 18) / 2.0, badge_w, 18)

        # 文本根据剩余空间截断，彻底避免撑宽列表导致横向滚动条出现
        name_font = QFont(painter.font())
        name_font.setPointSize(9)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(tok.parse_color(th.text_primary))

        avail_w = int(rect.width() - 44 - badge_w - 6)
        elided_name = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(20, avail_w))
        painter.drawText(
            QRectF(text_x, rect.y(), avail_w, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided_name
        )

        if "Electron" in family_str:
            b_bg = QColor(99, 102, 241, 40 if th.is_dark else 28)
            b_fg = QColor(165, 180, 252) if th.is_dark else QColor(79, 70, 229)
        elif "WebView" in family_str:
            b_bg = QColor(14, 165, 233, 40 if th.is_dark else 28)
            b_fg = QColor(125, 211, 252) if th.is_dark else QColor(2, 132, 199)
        elif "命令" in family_str:
            b_bg = QColor(16, 185, 129, 40 if th.is_dark else 28)
            b_fg = QColor(110, 231, 183) if th.is_dark else QColor(5, 150, 105)
        else:
            b_bg = QColor(255, 255, 255, 25 if th.is_dark else 15)
            b_fg = tok.parse_color(th.text_secondary)

        painter.setBrush(QBrush(b_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 9, 9)

        badge_font = QFont(painter.font())
        badge_font.setPointSize(7)
        badge_font.setWeight(QFont.Weight.Medium)
        painter.setFont(badge_font)
        painter.setPen(b_fg)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, family_str)

        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict, server=None) -> None:
        super().__init__()
        self.cfg = cfg
        self.server = server
        # 诊断面板读的 Clash 配置必须和启动时用的是同一份，否则两边证据对不上
        self.clash = ClashApi(config.settings(cfg).get("clashConfigPath"))
        self._tray_notice_shown = False
        self._endpoint_worker: EndpointTestWorker | None = None
        self._test_buttons: list[QPushButton | QAction] = []
        self._syncing_selection = False
        self._last_status = ""

        # 读取保存的偏好 (默认采用极光幻彩星云深紫)
        settings = config.settings(cfg)
        self._compact_mode = bool(settings.get("compactMode", False))
        theme_id = str(settings.get("theme", DEFAULT_THEME))
        if theme_id not in tok.THEMES:
            # 配置被手改坏时不能让 THEMES[id] 直接 KeyError
            theme_id = DEFAULT_THEME
        tok.set_current_theme(theme_id)

        self.setWindowTitle("TunlessProxy")
        self.setWindowIcon(app_icon())
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_tray()
        self._wire_server()

        self.reload(select=None)
        self._apply_mode_layout()
        QTimer.singleShot(200, self._announce_endpoint)

    # ------------------------------------------------------------ 界面构建

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # 0. 完整模式视窗 (Full Mode Window)
        self.full_window = QWidget()
        self._build_full_ui(self.full_window)
        self.stack.addWidget(self.full_window)

        # 1. 极致轻量模式视窗 (Compact Mini Launcher Window: 340x390)
        self.compact_window = QWidget()
        self._build_compact_ui(self.compact_window)
        self.stack.addWidget(self.compact_window)

    def _build_full_ui(self, container: QWidget) -> None:
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(HEADER_HEIGHT)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(8)

        logo_label = QLabel()
        logo_label.setPixmap(app_icon().pixmap(22, 22))
        header_layout.addWidget(logo_label)

        # 软件名：三段式静态字标（Tunless ● Proxy）—— 细体灰白 / 绿色微点 / 冰蓝渐变粗体
        self.title_mark = TitleMark(pixel_size=14, spacing=4)
        header_layout.addWidget(self.title_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addSpacing(6)

        self.endpoint_pill = StatusPill("探测中…", "brand")
        self.endpoint_label = self.endpoint_pill.label
        header_layout.addWidget(self.endpoint_pill)

        header_layout.addStretch(1)

        # 切换轻量模式按钮
        self.mode_btn = FluidButton("轻量模式", variant="secondary")
        self.mode_btn.setIcon(icons.icon_collapse())
        self.mode_btn.setFixedHeight(30)
        self.mode_btn.setToolTip("切换到 340x385 的极致便携迷你启动器")
        self.mode_btn.clicked.connect(self.toggle_compact_mode)
        header_layout.addWidget(self.mode_btn)

        self.theme_btn = FluidButton("主题", variant="secondary")
        self.theme_btn.setIcon(icons.icon_palette())
        self.theme_btn.setFixedHeight(30)
        self._setup_theme_menu(self.theme_btn)
        header_layout.addWidget(self.theme_btn)

        self.test_btn = FluidButton("测试代理", variant="secondary")
        self.test_btn.setFixedHeight(30)
        self.test_btn.clicked.connect(self.test_endpoint)
        self._test_buttons.append(self.test_btn)
        header_layout.addWidget(self.test_btn)

        self.settings_btn = FluidButton("设置", variant="secondary")
        self.settings_btn.setFixedHeight(30)
        self.settings_btn.clicked.connect(self.open_settings)
        header_layout.addWidget(self.settings_btn)

        root.addWidget(header)

        # 主体左右分屏 (统一 24px 页面边距规范，稳定响应式最小宽度)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setContentsMargins(24, 16, 24, 16)
        self.splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setMinimumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)

        # 操作区域 (全宽添加按钮 + 紧凑刷新图标按钮并附带Tooltip，与下方列表严格等宽对齐)
        action_bar = QHBoxLayout()
        action_bar.setContentsMargins(2, 0, 2, 0)
        action_bar.setSpacing(6)

        add_btn = FluidButton("添加应用", variant="primary")
        add_btn.setIcon(icons.icon_plus("#ffffff", 13))
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self.pick_files)
        action_bar.addWidget(add_btn, 1)

        self.refresh_btn = IconButton(
            icons.icon_refresh,
            tooltip="重新解析应用文件与图标缓存",
            box=30,
            icon_size=15,
        )
        self.refresh_btn.clicked.connect(self.refresh_selected)
        action_bar.addWidget(self.refresh_btn)
        left_layout.addLayout(action_bar)

        # 3. 现代化应用卡片列表
        self.list_widget = ProfileListWidget()
        self.list_widget.setMinimumWidth(200)
        self.list_widget.pathsDropped.connect(self.handle_paths)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.list_widget, 1)

        self.drop_island = DropZoneIsland()
        self.drop_hint = self.drop_island
        left_layout.addWidget(self.drop_island)

        self.splitter.addWidget(left)

        # 右侧主控制中心 (概览 / 配置 / 诊断中心全宽大盘)
        self.detail = DetailPanel()
        self.detail.setMinimumWidth(550)
        self.detail.launchRequested.connect(self.launch_profile)
        self.detail.saveRequested.connect(self.save_profile)
        self.detail.deleteRequested.connect(self.delete_profile)
        self.detail.shortcutRequested.connect(self.create_shortcut)
        self.detail.adoptToggled.connect(self.toggle_adopt)
        self.detail.restoreRequested.connect(self.restore_adopted)
        self.detail.diagnoseRequested.connect(self.diagnose_profile)
        self.diag = self.detail.diag

        self.splitter.addWidget(self.detail)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([260, 580])

        root.addWidget(self.splitter, 1)

    def _build_compact_ui(self, container: QWidget) -> None:
        """构建 340x385 的极致紧凑迷你启动器。"""
        root = QVBoxLayout(container)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # 1. 迷你超薄顶栏 (32px)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        m_logo = QLabel()
        m_logo.setPixmap(app_icon().pixmap(18, 18))
        top_bar.addWidget(m_logo)

        # 轻量模式用同款字标，只是小一档（横向空间只有 340px）
        self.compact_title_mark = TitleMark(pixel_size=12, spacing=3)
        top_bar.addWidget(self.compact_title_mark, 0, Qt.AlignmentFlag.AlignVCenter)

        self.compact_endpoint_pill = StatusPill("在线", "brand")
        top_bar.addWidget(self.compact_endpoint_pill)
        top_bar.addStretch(1)

        # 主题文字小药丸按钮
        self.compact_theme_btn = QPushButton("主题")
        self.compact_theme_btn.setIcon(icons.icon_palette())
        self.compact_theme_btn.setFixedHeight(28)
        self.compact_theme_btn.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 500;")
        self.compact_theme_btn.setToolTip("切换外观主题")
        self._setup_theme_menu(self.compact_theme_btn)
        top_bar.addWidget(self.compact_theme_btn)

        # 展开完整模式图标按钮
        self.expand_btn = QPushButton("展开")
        self.expand_btn.setIcon(icons.icon_expand())
        self.expand_btn.setFixedHeight(28)
        self.expand_btn.setStyleSheet("padding: 2px 6px; font-size: 11px; font-weight: 500;")
        self.expand_btn.setToolTip("展开为完整调控与诊断看板")
        self.expand_btn.clicked.connect(self.toggle_compact_mode)
        top_bar.addWidget(self.expand_btn)

        root.addLayout(top_bar)

        # 2. 紧凑应用列表 (行高 40px，自适应滚动，严禁横向滚动条出现)
        self.compact_list = QListWidget()
        self.compact_list.setObjectName("ProfileList")
        self.compact_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.compact_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.compact_list.setSpacing(2)
        self.compact_delegate = CompactItemDelegate(self.compact_list)
        self.compact_list.setItemDelegate(self.compact_delegate)
        self.compact_list.currentItemChanged.connect(self._on_compact_selection_changed)
        tok.theme_mgr.themeChanged.connect(self.compact_list.viewport().update)
        root.addWidget(self.compact_list, 1)

        # 3. 极简启动控制区 (卡片高度 ~78px)
        action_card = GlassCard()
        act_layout = QVBoxLayout(action_card)
        act_layout.setContentsMargins(10, 8, 10, 8)
        act_layout.setSpacing(8)

        # 应用信息小条
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self.compact_app_icon = QLabel()
        self.compact_app_icon.setFixedSize(26, 26)
        info_row.addWidget(self.compact_app_icon)

        self.compact_app_title = QLabel("未选择应用")
        self.compact_app_title.setStyleSheet("font-size: 13px; font-weight: 600;")
        info_row.addWidget(self.compact_app_title, 1)

        self.compact_app_family = StatusPill("未运行", "neutral")
        info_row.addWidget(self.compact_app_family)
        act_layout.addLayout(info_row)

        # 启动代理按钮 (桌面级 32px 尺寸)
        self.compact_launch_btn = FluidButton("启动代理", variant="primary")
        self.compact_launch_btn.setIcon(icons.icon_play("#ffffff", 14))
        self.compact_launch_btn.setFixedHeight(32)
        self.compact_launch_btn.clicked.connect(self._on_compact_launch)
        act_layout.addWidget(self.compact_launch_btn)

        root.addWidget(action_card)

        # 4. 底部微型拖拽与添加入口 (高 34px)
        drop_bar = QFrame()
        drop_bar.setObjectName("GlassCard")
        drop_bar.setFixedHeight(34)
        d_layout = QHBoxLayout(drop_bar)
        d_layout.setContentsMargins(10, 2, 6, 2)
        d_layout.setSpacing(8)

        self.compact_drop_text = QLabel("拖入快捷方式或程序")
        self.compact_drop_text.setObjectName("Hint")
        d_layout.addWidget(self.compact_drop_text, 1)

        c_add_btn = QPushButton("添加")
        c_add_btn.setIcon(icons.icon_plus("#94a3b8", 12))
        c_add_btn.setFixedHeight(24)
        c_add_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        c_add_btn.clicked.connect(self.pick_files)
        d_layout.addWidget(c_add_btn)

        root.addWidget(drop_bar)

    def _setup_theme_menu(self, button: QPushButton) -> None:
        menu = QMenu(self)
        for theme_id, th in tok.THEMES.items():
            action = QAction(f"{th.name} ({theme_id})", self)
            action.triggered.connect(lambda _=False, tid=theme_id: self.switch_theme(tid))
            menu.addAction(action)
        # 点击时在按钮正下方弹出，避免 setMenu 自动画出畸形的小黑箭头
        from PyQt6.QtCore import QPoint
        button.clicked.connect(lambda: menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4))))

    @guarded
    def switch_theme(self, theme_id: str) -> None:
        if theme_id not in tok.THEMES:
            theme_id = DEFAULT_THEME
        tok.set_current_theme(theme_id)
        qss = tok.generate_qss()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        settings = config.settings(self.cfg)
        settings["theme"] = theme_id
        self.cfg["settings"] = settings
        config.save(self.cfg)
        self.status(f"已应用主题：{tok.THEMES[theme_id].name}")
        self._update_compact_card(self.current_profile())

    def toggle_compact_mode(self) -> None:
        self.set_compact_mode(not self._compact_mode)

    @guarded
    def set_compact_mode(self, compact: bool) -> None:
        self._compact_mode = compact
        settings = config.settings(self.cfg)
        settings["compactMode"] = compact
        self.cfg["settings"] = settings
        config.save(self.cfg)
        self._apply_mode_layout()

    def _apply_mode_layout(self) -> None:
        p = self.current_profile()
        cur_id = p.id if p else None
        if self._compact_mode:
            # 彻底隐藏完整视窗及其大尺寸约束
            self.full_window.hide()
            self.compact_window.show()
            self.stack.setCurrentIndex(1)
            # 隐藏状态栏与菜单栏，避免底部黑条与组件遮挡
            self.statusBar().hide()
            self.menuBar().hide()
            self.setMinimumSize(320, 360)
            self.setMaximumSize(380, 460)
            self.resize(340, 385)
            self.reload(select=cur_id)
        else:
            self.compact_window.hide()
            self.full_window.show()
            self.stack.setCurrentIndex(0)
            self.statusBar().show()
            self.menuBar().show()
            # 最小宽度保证右侧配置面板始终 ≥550px，配置页永不出现横向滚动条
            self.setMinimumSize(840, 480)
            self.setMaximumSize(16777215, 16777215)
            self.resize(840, 540)
            self.reload(select=cur_id)

    def _on_compact_launch(self) -> None:
        p = self.current_profile()
        if p is not None:
            self.launch_profile(p.id)

    def _update_compact_card(self, profile: Profile | None) -> None:
        th = tok.get_current_theme()
        if profile is None:
            self.compact_app_title.setText("未选择应用")
            self.compact_app_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {th.text_muted};")
            self.compact_app_family.set_status("未选择", "neutral")
            self.compact_app_icon.setPixmap(app_icon().pixmap(26, 26))
            self.compact_launch_btn.setEnabled(False)
        else:
            self.compact_app_title.setText(profile.name)
            self.compact_app_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {th.text_primary};")
            # 状态语言规范：统一为“运行中”或“未运行”
            active = service.active_process_for_profile(profile.id)
            if active:
                self.compact_app_family.set_status(f"● 运行中", "success")
            else:
                self.compact_app_family.set_status("未运行", "neutral")
            self.compact_app_icon.setPixmap(profile_icon(profile).pixmap(26, 26))
            self.compact_launch_btn.setEnabled(True)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        add_action = QAction("添加应用…", self)
        add_action.triggered.connect(self.pick_files)
        file_menu.addAction(add_action)
        shell_action = QAction("打开代理终端", self)
        shell_action.triggered.connect(self.open_proxy_shell)
        file_menu.addAction(shell_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("视图与模式")
        mode_action = QAction("切换 轻量/完整 模式", self)
        mode_action.triggered.connect(self.toggle_compact_mode)
        tools_menu.addAction(mode_action)

        theme_submenu = tools_menu.addMenu("切换主题")
        for tid, th in tok.THEMES.items():
            act = QAction(th.name, self)
            act.triggered.connect(lambda _=False, t=tid: self.switch_theme(t))
            theme_submenu.addAction(act)

        tools_menu.addSeparator()
        test_action = QAction("测试代理连通性", self)
        test_action.triggered.connect(self.test_endpoint)
        tools_menu.addAction(test_action)
        self._test_buttons.append(test_action)
        settings_action = QAction("设置…", self)
        settings_action.triggered.connect(self.open_settings)
        tools_menu.addAction(settings_action)

        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("能力边界说明", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        # 「关于」直接挂在菜单栏上（在「帮助」右边），点一下就打开关于页。
        # 用 addAction 而不是 addMenu：QMenuBar 会把裸 action 渲染成一个可点击项，
        # 不会多出一层"点开只有一项"的子菜单。能力边界说明仍留在「帮助」里。
        self.about_page_action = QAction("关于", self)
        self.about_page_action.setToolTip(f"关于 {APP_NAME}")
        self.about_page_action.triggered.connect(self.show_about_page)
        self.menuBar().addAction(self.about_page_action)

    def _build_tray(self) -> None:
        from PyQt6.QtWidgets import QSystemTrayIcon

        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = TrayIcon(self)
        self.tray.show()

    def _wire_server(self) -> None:
        if self.server is None:
            return
        self.server.newConnection.connect(self._on_ipc)

    def _on_ipc(self) -> None:
        socket = self.server.nextPendingConnection()
        if socket is None:
            return

        def handle() -> None:
            try:
                message = bytes(socket.readAll()).decode("utf-8", "replace").strip()
            except Exception:
                message = ""
            if message.startswith("launched:"):
                parts = message.split(":")
                if len(parts) >= 3:
                    self._on_external_launch(parts[1], int(parts[2]) if parts[2].isdigit() else 0)
            else:
                self.bring_to_front()
            socket.disconnectFromServer()

        socket.readyRead.connect(handle)
        socket.disconnected.connect(socket.deleteLater)

    # ------------------------------------------------------------ 数据与状态

    def reload(self, select: str | None = None) -> None:
        profiles = service.list_profiles(self.cfg)
        self.list_widget.set_profiles(profiles, select)

        # 同时也填充并同步 compact_list
        self.compact_list.blockSignals(True)
        self.compact_list.clear()
        for p in profiles:
            it = QListWidgetItem()
            it.setData(ROLE_PROFILE_ID, p.id)
            it.setData(ROLE_PROFILE_NAME, p.name)
            it.setData(ROLE_PROFILE_FAMILY, p.spec.family.label)
            it.setData(ROLE_PROFILE_TARGET, p.spec.target.rsplit("\\", 1)[-1])
            it.setData(ROLE_PROFILE_ICON, profile_icon(p))
            self.compact_list.addItem(it)
        self.compact_list.blockSignals(False)

        self.drop_island.setVisible(not profiles)
        if self.tray is not None:
            self.tray.set_recent(profiles)
        if not profiles:
            self.detail.set_profile(None)
            self._update_compact_card(None)
        else:
            cur_id = select or (profiles[0].id if profiles else None)
            if cur_id:
                self.select_by_id(cur_id)

    def select_by_id(self, profile_id: str) -> None:
        self.list_widget.select_by_id(profile_id)
        for row in range(self.compact_list.count()):
            item = self.compact_list.item(row)
            if item.data(ROLE_PROFILE_ID) == profile_id:
                self.compact_list.setCurrentRow(row)
                break

    def current_profile(self) -> Profile | None:
        profile_id = self.list_widget.current_profile_id()
        if not profile_id:
            return None
        return service.get_profile(self.cfg, profile_id)

    def _on_selection_changed(self, *_args) -> None:
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            p = self.current_profile()
            self.detail.set_profile(p)
            self._update_compact_card(p)
            if p:
                for row in range(self.compact_list.count()):
                    if self.compact_list.item(row).data(ROLE_PROFILE_ID) == p.id:
                        self.compact_list.setCurrentRow(row)
                        break
        finally:
            self._syncing_selection = False

    def _on_compact_selection_changed(self, *_args) -> None:
        if self._syncing_selection:
            return
        self._syncing_selection = True
        try:
            it = self.compact_list.currentItem()
            pid = it.data(ROLE_PROFILE_ID) if it else None
            if pid:
                self.list_widget.select_by_id(pid)
                p = service.get_profile(self.cfg, pid)
                self.detail.set_profile(p)
                self._update_compact_card(p)
        finally:
            self._syncing_selection = False

    # ------------------------------------------------------------ 拖拽反馈

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        # 只对真正能加的文件亮起"放手即可添加" —— 之前拖个 .txt 进来也会这么承诺，
        # 松手后却被静默忽略。
        if not event.mimeData().hasUrls():
            return
        supported = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile() and is_supported_drop(url.toLocalFile())
        ]
        if not supported:
            return
        event.acceptProposedAction()
        self.drop_island.set_active(True)
        self.compact_drop_text.setText("✨ 放手即可立即添加！")

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.drop_island.set_active(False)
        self.compact_drop_text.setText("📥 拖入快捷方式或程序")

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.drop_island.set_active(False)
        self.compact_drop_text.setText("📥 拖入快捷方式或程序")
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile()
        ]
        if paths:
            self.handle_paths(paths)
            event.acceptProposedAction()

    @guarded
    def handle_paths(self, paths: list[str]) -> None:
        supported = [p for p in paths if is_supported_drop(p)]
        skipped = [p for p in paths if p not in supported]
        added: list[Profile] = []
        errors: list[str] = []

        for path in supported:
            try:
                added.append(service.add_profile(self.cfg, path))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{os.path.basename(path)}：{exc}")

        if added:
            self.reload(select=added[-1].id)
            summary = "、".join(f"{p.name}（{p.spec.family.label}）" for p in added)
            self.status(f"已添加：{summary}")
            if self.tray is not None:
                self.tray.notify("已添加应用", summary)
        if skipped:
            self.status(f"已忽略 {len(skipped)} 个不支持的文件（只支持 .lnk/.url/.exe/.bat/.cmd）")
        if errors:
            QMessageBox.warning(self, "部分添加失败", "\n".join(errors))

    def pick_files(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择快捷方式或可执行文件",
            os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
            "快捷方式与程序 (*.lnk *.url *.exe *.bat *.cmd);;所有文件 (*)",
        )
        if files:
            self.handle_paths(files)

    # ------------------------------------------------------------ 核心动作

    @guarded
    def launch_profile(self, profile_id: str) -> None:
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        try:
            plan, record = service.run_profile(self.cfg, profile_id)
        except (OSError, KeyError, proc.SelfLaunchRefused) as exc:
            QMessageBox.critical(self, "启动失败", str(exc))
            return

        self.reload(select=profile_id)
        self.status(f"已启动 {profile.name}（PID {record.pid}）")
        if plan.notes:
            self.status("；".join(plan.notes))
            QMessageBox.information(self, "启动提示", "\n".join(f"· {n}" for n in plan.notes))
        self.diag.watch(record.pid, service.current_endpoint(self.cfg), self.clash)

    def _on_external_launch(self, profile_id: str, pid: int) -> None:
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        self.reload(select=profile_id)
        self.status(f"检测到外部启动：{profile.name}（PID {pid}）")
        if pid:
            self.diag.watch(pid, service.current_endpoint(self.cfg), self.clash)

    @guarded
    def save_profile(self, profile: Profile) -> None:
        service.save_profile(self.cfg, profile)
        if not self.list_widget.update_profile(profile):
            self.list_widget.set_profiles(service.list_profiles(self.cfg), profile.id)
        self.status(f"已保存 {profile.name}")
        self._update_compact_card(profile)

    @guarded
    def delete_profile(self, profile_id: str) -> None:
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "删除配置",
            f"确定删除「{profile.name}」？\n（只删本程序里的配置，不会动应用本身）",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        service.delete_profile(self.cfg, profile_id)
        self.reload()
        self.status(f"已删除 {profile.name}")

    @guarded
    def create_shortcut(self, profile_id: str) -> None:
        """菜单里的「创建桌面快捷方式」。

        0.1.8 起这条就是"生成的那个位置"：自动生成的独立快捷方式也落在桌面，
        所以这个动作同时也是"刷新/补上"（比如手动删掉了桌面那份）。
        """
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        path = shortcuts.generated_path(profile)
        existed = path.is_file()
        try:
            created = shortcuts.create_shortcut(profile)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "创建失败", str(exc))
            return
        if not created.is_file():
            QMessageBox.warning(
                self, "创建失败", f"没有写成功：\n{created}\n\n桌面目录可能不可写。"
            )
            return
        # 顺带把旧版本留在开始菜单里的那份清掉了（只删确认是本程序生成的）
        retired = shortcuts.start_menu_path(profile)
        extra = ""
        if not retired.is_file() and not existed:
            extra = "\n\n（旧版本在开始菜单里的那一份已顺带清理）"
        self.status(f"桌面快捷方式{'已刷新' if existed else '已创建'}：{created.name}")
        QMessageBox.information(
            self,
            "已刷新桌面快捷方式" if existed else "已创建桌面快捷方式",
            f"位置：\n{created}{extra}",
        )

    @guarded
    def toggle_adopt(self, profile_id: str, adopt: bool) -> None:
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        if adopt:
            answer = QMessageBox.question(
                self,
                "接管原快捷方式",
                f"将把\n{profile.source_path}\n替换成指向本程序的快捷方式，"
                "这样从开始菜单/任务栏点它也会走代理。\n\n原文件会先备份，可随时还原。是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.detail.set_profile(profile)
                return
            if not shortcuts.adopt_shortcut(profile):
                QMessageBox.warning(self, "接管失败", "只能接管 .lnk 快捷方式。")
                self.detail.set_profile(profile)
                return
            service.save_profile(self.cfg, profile)
            self.status("已接管快捷方式（原文件已备份）")
        else:
            shortcuts.restore_adopted(profile)
            service.save_profile(self.cfg, profile)
            self.status("已还原快捷方式")
        self.reload(select=profile_id)
        self.detail.set_profile(service.get_profile(self.cfg, profile_id))

    @guarded
    def restore_adopted(self, profile_id: str) -> None:
        profile = service.get_profile(self.cfg, profile_id)
        if profile is None:
            return
        if shortcuts.restore_adopted(profile):
            service.save_profile(self.cfg, profile)
            self.status("已还原快捷方式")
        else:
            self.status("没有可还原的备份")
        self.reload(select=profile_id)
        self.detail.set_profile(service.get_profile(self.cfg, profile_id))

    @guarded
    def refresh_selected(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        refreshed = service.refresh_profile(profile)
        service.extract_icon(refreshed)
        service.save_profile(self.cfg, refreshed)
        self.reload(select=refreshed.id)
        self.status(f"已重新解析 {refreshed.name}")

    def diagnose_profile(self, profile_id: str) -> None:
        history = [
            item for item in proc.recent_launches(200) if item.get("profileId") == profile_id
        ]
        if not history:
            self.status("这个应用还没有启动记录，先点「⚡ 启动应用代理」")
            return
        pid = int(history[0]["pid"])
        self.detail.tabs.setCurrentIndex(2)
        self.diag.watch(pid, service.current_endpoint(self.cfg), self.clash)
        self.status(f"正在诊断 PID {pid}")

    @guarded
    def open_proxy_shell(self) -> None:
        try:
            record = service.proxy_shell(self.cfg)
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))
            return
        self.status(f"已打开代理终端（PID {record.pid}）")

    def test_endpoint(self) -> None:
        if self._endpoint_worker is not None and self._endpoint_worker.isRunning():
            self.status("上一次测试还没结束…")
            return

        endpoint = service.current_endpoint(self.cfg)
        self.status(f"正在测试 {endpoint.host}:{endpoint.mixed_port} …")
        self._test_buttons_enabled(False)

        worker = EndpointTestWorker(endpoint, self)
        worker.tested.connect(lambda result: self._on_endpoint_tested(endpoint, result))
        worker.finished.connect(self._on_endpoint_worker_done)
        self._endpoint_worker = worker
        worker.start()

    def _on_endpoint_worker_done(self) -> None:
        self._test_buttons_enabled(True)
        self._endpoint_worker = None

    def _test_buttons_enabled(self, enabled: bool) -> None:
        for button in self._test_buttons:
            button.setEnabled(enabled)

    def _on_endpoint_tested(self, endpoint, result: dict) -> None:
        from ..detect import endpoint as endpoint_mod

        text = endpoint_mod.verdict_text(result)
        self.status(f"{endpoint.host}:{endpoint.mixed_port} —— {text}")

        def region(country, ip) -> str:
            if country and ip:
                return f"{country}（{ip}）"
            return country or ip or "未取到"

        detail = (
            f"端点：{endpoint.host}:{endpoint.mixed_port}（来源：{endpoint.source}）\n"
            f"端口探活：{'通' if result.get('tcp_alive') else '不通'}\n"
            f"经代理出网：{'成功' if result.get('proxy_ok') else '失败'}"
            f"{'  ' + region(result.get('proxy_country'), result.get('proxy_ip')) if result.get('proxy_ok') else ''}\n"
            f"直连出网：{'成功' if result.get('direct_ok') else '失败'}"
            f"{'  ' + region(result.get('direct_country'), result.get('direct_ip')) if result.get('direct_ok') else ''}\n\n"
            f"结论：{text}"
        )
        if result.get("error"):
            detail += f"\n\n错误：{result['error']}"
        QMessageBox.information(self, "代理连通性", detail)

    @guarded
    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.cfg,
            service.current_endpoint(self.cfg),
            self,
        )
        # 对话框必须能回收：它 parent 是主窗口，不回收的话"关掉"只是隐藏，
        # C++ 对象会一直挂在主窗口下（连开几次就多几份整棵控件树）。
        #
        # 这里刻意用「读完值再 deleteLater」而不是 WA_DeleteOnClose：后者会在
        # 嵌套 exec() 返回时就把对话框删掉，而我们要在返回后读它的控件值
        # （apply_to_config 会摸 compact_box 等），等于读一个已析构对象。
        result = dialog.exec()
        if result == SettingsDialog.DialogCode.Accepted:
            dialog.apply_to_config()
            self._announce_endpoint()
            settings = config.settings(self.cfg)
            self.switch_theme(settings.get("theme", DEFAULT_THEME))
            # 「轻量便携模式」勾上/取消后要立刻生效，否则眼前状态和刚保存的配置相反
            wanted_compact = bool(settings.get("compactMode", False))
            if wanted_compact != self._compact_mode:
                self.set_compact_mode(wanted_compact)
            self.status("设置已保存")
        dialog.deleteLater()

    @guarded
    def show_about_page(self) -> None:
        """菜单栏「关于」：作者/版本/许可那一页。

        与「帮助 → 能力边界说明」分工不同：那边讲"这工具能做什么、不能做什么"，
        这边只回答"这是什么、谁写的、什么许可"。
        """
        from .about_dialog import AboutDialog

        dialog = AboutDialog(self)
        dialog.exec()
        # 和设置对话框一样的取舍：exec() 返回后自己回收，不用 WA_DeleteOnClose
        dialog.deleteLater()

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "能力边界",
            "本程序不装 TUN 驱动、不向目标进程注入代码，"
            "而是靠「启动时施加、只作用于该进程树」的手段生效：\n\n"
            "  L1 环境变量      —— Go/Rust/Python/Node/.NET Core/curl/git/npm/pip/cargo\n"
            "  L2 命令行参数    —— Electron/Chromium/WebView2（--proxy-server）\n"
            "  L3 配置文件指针  —— git/npm/pip/curl/wget/docker/ssh，不改你的真实配置\n"
            "  L4 快捷方式      —— 让「点原图标」也走代理\n"
            "  L5 机器级开关    —— WinHTTP 原生应用（全机生效，需管理员）\n\n"
            "明确不支持：\n"
            "  · 只走 WinHTTP 的原生应用（按应用无法覆盖，只能用 L5）\n"
            "  · UWP / 商店应用\n"
            "  · 已经在运行的进程、Windows 服务\n"
            "  · 游戏与反作弊\n"
            "  · UDP / QUIC 流量（Chromium 系可用 --disable-quic 规避）\n\n"
            "诊断面板会如实告诉你哪些连接走了代理、哪些在直连。",
        )

    # ------------------------------------------------------------ 辅助

    def _announce_endpoint(self) -> None:
        endpoint = service.current_endpoint(self.cfg)
        text = f"{endpoint.host}:{endpoint.mixed_port}"
        # 之前这里是 `"通" if endpoint else "?"` —— ProxyEndpoint 永远是真值，
        # 所以胶囊恒为绿色"通"，哪怕代理根本没开。这里做一次真实探活。
        alive = endpoint_mod.tcp_alive(endpoint.host, endpoint.mixed_port, timeout=0.4)
        tone = "success" if alive else "warn"
        suffix = "" if alive else "（不通）"
        self.endpoint_pill.set_status(f"代理端点: {text}{suffix}", tone)
        self.compact_endpoint_pill.set_status(f"{endpoint.mixed_port}{suffix}", tone)

    def status(self, message: str) -> None:
        """状态提示。

        轻量模式把状态栏和菜单栏一起藏了，而这两个是唯一的文字反馈通道 ——
        切主题、启动应用、忽略不支持的文件都会"什么都不显示"。所以那里退化成
        底部那行提示文字，8 秒后再换回拖拽提示。
        """
        self._last_status = message
        self.statusBar().showMessage(message, 8000)
        if self._compact_mode and hasattr(self, "compact_drop_text"):
            self.compact_drop_text.setText(message)
            QTimer.singleShot(8000, self._restore_compact_hint)

    def _restore_compact_hint(self) -> None:
        """只在提示文字还是上一条状态时才换回拖拽提示（别踩掉拖拽中的提示语）。"""
        if (
            self._compact_mode
            and hasattr(self, "compact_drop_text")
            and self.compact_drop_text.text() == self._last_status
        ):
            self.compact_drop_text.setText("📥 拖入快捷方式或程序")

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        from PyQt6.QtWidgets import QApplication

        adopted = [p for p in service.list_profiles(self.cfg) if p.adopted_shortcut]
        if adopted:
            answer = QMessageBox.question(
                self,
                "退出",
                f"有 {len(adopted)} 个快捷方式处于「已接管」状态。\n"
                "退出不会自动还原（下次启动仍可还原）。现在还原吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                for profile in adopted:
                    if shortcuts.restore_adopted(profile):
                        service.save_profile(self.cfg, profile)
        if self._endpoint_worker is not None and self._endpoint_worker.isRunning():
            self._endpoint_worker.wait(3000)
        if self.tray is not None:
            self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.tray is None:
            # 没有托盘图标（explorer 崩了 / Server Core / 某些会话）时，"关窗=隐藏"
            # 等于程序失联：窗口没了、托盘也没有、菜单栏也随窗口一起没了，
            # 只能去任务管理器杀。这种情况直接退出。
            event.accept()
            self.quit_app()
            return
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self.tray.notify("TunlessProxy 仍在后台", "双击托盘图标可以重新打开窗口。")
