"""现代化应用代理控制中心 (Overview 概览主控 + Config 参数流 + Diagnostics 诊断大盘)。

桌面软件级别 UI 精修：
- 彻底去卡片化 (De-Cardification)：消除多层嵌套大框，以规整排印层级与呼吸留白组织内容
- 紧凑首屏聚焦：一体化主控条 + 纯净单行元信息排印，消灭多余 Dashboard 碎块
- 弹性紧凑时间线：自适应高度，无粗糙 PID，仅呈现 时间 / 应用名 / 启动结果
- 全量纯矢量线性 SVG 图标：告别廉价 Emoji
- 统一状态语言：消灭“就绪”，规范为“运行中”与“未运行”
"""

from __future__ import annotations

import datetime
import os
import time

from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import service
from ..detect import family as family_mod
from ..model import Family, Profile
from . import icons, theme_tokens as tok
from .diag_panel import DiagPanel
from .modern_widgets import (
    FluidButton, GlassCard, IconButton, ModernSwitch, SegmentedControl, StatusPill,
    SwitchCard
)
from .widgets import elide_path, profile_icon

LEVER_LABELS = {
    "env": ("L1 环境变量", "施加 HTTP_PROXY / ALL_PROXY 等，覆盖 Go/Rust/Python/Node/curl/git/npm/pip/cargo"),
    "cmdline": ("L2 命令行参数", "自动注入 --proxy-server 与 --disable-quic，覆盖 Electron/Chromium/WebView2"),
    "configFiles": ("L3 配置文件指针", "将 git/npm/pip/docker/ssh 指向私有隔离配置，绝不动你的真实系统配置"),
}

FAMILY_ORDER = [
    Family.ELECTRON, Family.WEBVIEW2, Family.JAVA, Family.NODE,
    Family.CLI, Family.NATIVE, Family.UWP,
]


class DetailPanel(QWidget):
    """右侧主控制中心：概览 (Overview) / 配置 (Config) / 诊断大盘 (Diagnostics)。"""

    launchRequested = pyqtSignal(str)
    saveRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(str)
    shortcutRequested = pyqtSignal(str)
    adoptToggled = pyqtSignal(str, bool)
    restoreRequested = pyqtSignal(str)
    diagnoseRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profile: Profile | None = None
        self._loading = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(14)

        # ------------------------------------------------------------
        # 1. 顶栏导航与更多操作
        # ------------------------------------------------------------
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(0, 0, 0, 0)
        nav_bar.setSpacing(10)

        self.tabs = SegmentedControl(["概览", "配置", "诊断中心"])
        self.tabs.setFixedHeight(30)
        self.tabs.currentIndexChanged.connect(self._on_tab_changed)
        nav_bar.addWidget(self.tabs, 1)

        self.more_btn = IconButton(
            icons.icon_more,
            tooltip="更多操作",
            box=30,
            icon_size=16,
        )
        self.more_btn.clicked.connect(self._show_more_menu)
        nav_bar.addWidget(self.more_btn)

        root_layout.addLayout(nav_bar)

        # ------------------------------------------------------------
        # 2. 核心视窗堆叠容器
        # ------------------------------------------------------------
        self.stack = QStackedWidget()

        # 视图 0: 概览控制主屏 (Overview)
        self.overview_page = self._build_overview_page()
        self.stack.addWidget(self.overview_page)

        # 视图 1: 参数配置流 (Configuration)
        self.config_page = self._build_config_page()
        self.stack.addWidget(self.config_page)

        # 视图 2: 网络雷达诊断中心 (Diagnostics)
        self.diag = DiagPanel()
        self.stack.addWidget(self.diag)

        root_layout.addWidget(self.stack, 1)

        # ------------------------------------------------------------
        # 3. 空状态引导遮罩 (Empty State)
        # ------------------------------------------------------------
        self.empty_card = QFrame()
        self.empty_card.setObjectName("StatCard")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setContentsMargins(20, 40, 20, 40)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel("选择应用以开启代理控制中心")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 14px; font-weight: 600;")
        empty_layout.addWidget(self.empty_title)

        self.empty_hint = QLabel("支持从桌面直接拖入快捷方式、可执行文件或批处理脚本")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setObjectName("Hint")
        empty_layout.addWidget(self.empty_hint)

        root_layout.addWidget(self.empty_card, 1)

        self._refresh_theme_styles()
        tok.theme_mgr.themeChanged.connect(self._refresh_theme_styles)
        self.set_profile(None)

    def _on_tab_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 2 and self._profile is not None:
            active = service.active_process_for_profile(self._profile.id)
            if active:
                self.diagnoseRequested.emit(self._profile.id)

    # ------------------------------------------------------------
    # 模块 1：概览控制中心构建 (Overview Page)
    # ------------------------------------------------------------

    def _build_overview_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        # A. 一体化主控栏 (去除多层笨重卡片，自然排印)
        master_box = QFrame()
        master_box.setObjectName("GlassCard")
        m_layout = QVBoxLayout(master_box)
        m_layout.setContentsMargins(14, 12, 14, 12)
        m_layout.setSpacing(10)

        # 上半部分：图标 + 标题 + 运行态 + 按钮组
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(42, 42)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.icon_label)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self.name_label = QLabel("应用名称")
        self.name_label.setObjectName("AppNameLabel")
        name_row.addWidget(self.name_label)

        self.rename_btn = IconButton(
            icons.icon_edit,
            tooltip="重命名此应用",
            box=24,
            icon_size=13,
            variant="ghost",
        )
        self.rename_btn.clicked.connect(self._prompt_rename)
        name_row.addWidget(self.rename_btn)
        name_row.addStretch(1)
        info_col.addLayout(name_row)

        state_row = QHBoxLayout()
        state_row.setSpacing(8)

        # 运行状态 (运行中 / 未运行，彻底消灭“就绪”)
        self.run_status_pill = StatusPill("未运行", "neutral")
        state_row.addWidget(self.run_status_pill)

        self.family_pill = StatusPill("家族", "brand")
        state_row.addWidget(self.family_pill)

        self.source_label = QLabel()
        self.source_label.setObjectName("Subtitle")
        # 同样允许自由压缩：超长源路径不会把状态行顶宽
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        state_row.addWidget(self.source_label)
        state_row.addStretch(1)
        info_col.addLayout(state_row)

        top_row.addLayout(info_col, 1)

        # 桌面级精致操作按钮 (克制尺寸 32px，主要操作突出但决不营销化大膨胀)
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)

        self.launch_button = FluidButton("启动代理", variant="primary")
        self.launch_button.setIcon(icons.icon_play("#ffffff", 14))
        self.launch_button.setFixedHeight(32)
        self.launch_button.clicked.connect(lambda: self._emit(self.launchRequested))
        btn_box.addWidget(self.launch_button)

        self.diagnose_nav_btn = FluidButton("诊断链路", variant="secondary")
        self.diagnose_nav_btn.setIcon(icons.icon_activity("#94a3b8", 14))
        self.diagnose_nav_btn.setFixedHeight(32)
        self.diagnose_nav_btn.clicked.connect(self._nav_to_diagnostics)
        btn_box.addWidget(self.diagnose_nav_btn)

        top_row.addLayout(btn_box)
        m_layout.addLayout(top_row)

        # 下半部分：一体化元信息状态排印 (无多余背景框与Dashboard碎块)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(2, 4, 2, 0)
        meta_row.setSpacing(8)

        self.ep_display_label = QLabel("代理出口: 127.0.0.1:7897")
        self.ep_display_label.setObjectName("CardSubtitle")
        meta_row.addWidget(self.ep_display_label)

        dot1 = QLabel("·")
        dot1.setObjectName("Hint")
        meta_row.addWidget(dot1)

        self.levers_summary_label = QLabel("L1 · L2 · L3 全量生效")
        self.levers_summary_label.setObjectName("CardSubtitle")
        meta_row.addWidget(self.levers_summary_label)

        self.quic_dns_label = QLabel("阻断QUIC")
        self.quic_dns_label.setObjectName("Hint")
        meta_row.addWidget(self.quic_dns_label)

        dot2 = QLabel("·")
        dot2.setObjectName("Hint")
        meta_row.addWidget(dot2)

        self.launch_count_label = QLabel("已启动 0 次")
        self.launch_count_label.setObjectName("CardSubtitle")
        meta_row.addWidget(self.launch_count_label)

        meta_row.addStretch(1)
        m_layout.addLayout(meta_row)

        layout.addWidget(master_box)

        # B. 紧凑型活动时间线 (弹性自适应高度，无多余PID与空白)
        act_box = QFrame()
        act_box.setObjectName("GlassCard")
        a_layout = QVBoxLayout(act_box)
        a_layout.setContentsMargins(14, 10, 14, 10)
        a_layout.setSpacing(6)

        act_head = QLabel("最近活动")
        act_head.setObjectName("SectionTitle")
        a_layout.addWidget(act_head)

        self.activity_box = QVBoxLayout()
        self.activity_box.setSpacing(4)
        a_layout.addLayout(self.activity_box)

        layout.addWidget(act_box)

        # 底部弹性留白：内容紧凑聚焦在首屏黄金区，下方自然呼吸
        layout.addStretch(1)
        return container

    # ------------------------------------------------------------
    # 模块 2：参数配置流构建 (Configuration Page)
    # ------------------------------------------------------------

    def _build_config_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # 严禁横向滚动条：内容宽度由右侧面板最小宽度保证，永不出现左右拖动条
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)

        sec1 = QLabel("代理注入手段")
        sec1.setObjectName("SectionTitle")
        sec1.setStyleSheet("padding-left: 8px;")
        layout.addWidget(sec1)

        self.lever_cards: dict[str, SwitchCard] = {}
        for key, (title, detail) in LEVER_LABELS.items():
            card = SwitchCard(title, detail)
            card.toggled.connect(self._collect)
            layout.addWidget(card)
            self.lever_cards[key] = card

        sec_card = GlassCard()
        sec_layout = QVBoxLayout(sec_card)
        sec_layout.setContentsMargins(14, 12, 14, 12)
        sec_layout.setSpacing(10)

        # 纵向排列：避免两个长文案复选框并排撑宽面板，杜绝横向溢出
        self.quic_box = QCheckBox("阻断 QUIC 协议（避免 UDP 漏流）")
        self.quic_box.setToolTip("自动注入 --disable-quic：UDP/443 无法走 TCP 代理，阻断可避免流量泄漏")
        self.quic_box.toggled.connect(self._collect)
        sec_layout.addWidget(self.quic_box)

        self.remote_dns_box = QCheckBox("强制远端 DNS 解析（防 DNS 污染）")
        self.remote_dns_box.setToolTip("自动注入 --host-resolver-rules=MAP * ~NOTFOUND，杜绝本地 DNS 泄漏")
        self.remote_dns_box.toggled.connect(self._collect)
        sec_layout.addWidget(self.remote_dns_box)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("控制台窗口策略："))
        self.console_combo = QComboBox()
        self.console_combo.addItem("自动策略（命令行程序新开窗口）", "auto")
        self.console_combo.addItem("总是新开窗口", "new")
        self.console_combo.addItem("静默（不新开窗口）", "none")
        self.console_combo.currentIndexChanged.connect(self._collect)
        row2.addWidget(self.console_combo)
        row2.addStretch(1)
        sec_layout.addLayout(row2)
        layout.addWidget(sec_card)

        sec2 = QLabel("运行时参数与环境")
        sec2.setObjectName("SectionTitle")
        sec2.setStyleSheet("padding-left: 8px;")
        layout.addWidget(sec2)

        param_card = GlassCard()
        form = QFormLayout(param_card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.target_label = QLabel("-")
        self.target_label.setWordWrap(True)
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Ignored 水平策略：允许布局自由压缩该标签，长路径自动换行而绝不撑宽面板
        self.target_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        form.addRow("目标程序路径：", self.target_label)

        self.family_combo = QComboBox()
        for fam in FAMILY_ORDER:
            self.family_combo.addItem(fam.label, fam.value)
        self.family_combo.currentIndexChanged.connect(self._on_family_changed)
        form.addRow("所属技术家族：", self.family_combo)

        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("原样传递的启动参数，支持 %TEMP% 环境变量")
        self.args_edit.editingFinished.connect(self._collect)
        form.addRow("启动参数 (args)：", self.args_edit)

        self.workdir_edit = QLineEdit()
        self.workdir_edit.setPlaceholderText("留空则：命令行工具用用户目录，GUI 程序用目标所在目录")
        self.workdir_edit.editingFinished.connect(self._collect)
        form.addRow("工作目录：", self.workdir_edit)

        self.cmdline_extra_edit = QLineEdit()
        self.cmdline_extra_edit.setPlaceholderText("额外追加的命令行参数，空格分隔")
        self.cmdline_extra_edit.editingFinished.connect(self._collect)
        form.addRow("追加参数：", self.cmdline_extra_edit)

        self.no_proxy_edit = QLineEdit()
        self.no_proxy_edit.setPlaceholderText("逗号分隔，如 *.corp.local, 192.168.*")
        self.no_proxy_edit.editingFinished.connect(self._collect)
        form.addRow("直连白名单：", self.no_proxy_edit)

        self.env_extra_edit = QPlainTextEdit()
        self.env_extra_edit.setPlaceholderText("自定义环境变量，每行一个 KEY=VALUE")
        self.env_extra_edit.setFixedHeight(64)
        self.env_extra_edit.installEventFilter(self)
        form.addRow("附加变量：", self.env_extra_edit)
        layout.addWidget(param_card)

        sec3 = QLabel("识别依据与判定说明")
        sec3.setObjectName("SectionTitle")
        sec3.setStyleSheet("padding-left: 8px;")
        layout.addWidget(sec3)

        info_card = GlassCard()
        ic_layout = QVBoxLayout(info_card)
        ic_layout.setContentsMargins(14, 12, 14, 12)
        ic_layout.setSpacing(6)

        self.evidence_label = QLabel("-")
        self.evidence_label.setWordWrap(True)
        self.evidence_label.setObjectName("Subtitle")
        ic_layout.addWidget(self.evidence_label)

        self.meta_label = QLabel("-")
        self.meta_label.setObjectName("Hint")
        ic_layout.addWidget(self.meta_label)
        layout.addWidget(info_card)

        layout.addStretch(1)
        scroll.setWidget(container)
        self.config_scroll = scroll
        return scroll

    def eventFilter(self, obj, event):  # noqa: N802
        editor = getattr(self, "env_extra_edit", None)
        if editor is not None and obj is editor and event.type() == QEvent.Type.FocusOut:
            self._collect()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------
    # 更多操作菜单
    # ------------------------------------------------------------

    def _show_more_menu(self) -> None:
        if self._profile is None:
            return
        menu = QMenu(self)

        sc_act = QAction("创建桌面快捷方式", self)
        sc_act.triggered.connect(lambda: self.shortcutRequested.emit(self._profile.id))
        menu.addAction(sc_act)

        menu.addSeparator()

        if self._profile.adopted_shortcut:
            restore_act = QAction("还原原快捷方式备份", self)
            restore_act.triggered.connect(lambda: self.restoreRequested.emit(self._profile.id))
            menu.addAction(restore_act)
        else:
            adopt_act = QAction("接管原快捷方式 (点原图标也走代理)", self)
            adopt_act.triggered.connect(lambda: self.adoptToggled.emit(self._profile.id, True))
            menu.addAction(adopt_act)

        menu.addSeparator()

        del_act = QAction("删除此应用配置", self)
        del_act.triggered.connect(lambda: self.deleteRequested.emit(self._profile.id))
        menu.addAction(del_act)

        pos = self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height() + 4))
        menu.exec(pos)

    def _prompt_rename(self) -> None:
        if self._profile is None:
            return
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "重命名应用", "请输入新的应用名称：", text=self._profile.name
        )
        if ok and new_name.strip():
            self._profile.name = new_name.strip()
            self.name_label.setText(self._profile.name)
            self.saveRequested.emit(self._profile)

    def _nav_to_diagnostics(self) -> None:
        self.tabs.setCurrentIndex(2)

    def _refresh_theme_styles(self) -> None:
        th = tok.get_current_theme()
        if hasattr(self, "icon_label"):
            self.icon_label.setStyleSheet(f"""
                background: {th.border_subtle};
                border: 1px solid {th.border_default};
                border-radius: {tok.RADIUS_MD}px;
            """)
        # rename_btn / more_btn 均为 IconButton，样式与图标由组件自身随主题刷新
        if hasattr(self, "diagnose_nav_btn"):
            self.diagnose_nav_btn.setIcon(icons.icon_activity(th.text_secondary, 14))
        # 活动流的时间/圆点颜色是渲染时按当时主题写死的内联样式，
        # 不重画的话切到浅色主题后它们还留着深色主题的颜色。
        if self._profile is not None:
            self._render_activity_stream(self._profile.id)

    # ------------------------------------------------------------
    # 数据加载与状态呈现
    # ------------------------------------------------------------

    def set_profile(self, profile: Profile | None) -> None:
        self._profile = profile
        enabled = profile is not None

        self.tabs.setVisible(enabled)
        self.more_btn.setVisible(enabled)
        self.stack.setVisible(enabled)
        self.empty_card.setVisible(not enabled)

        if profile is None:
            return

        self._loading = True
        try:
            th = tok.get_current_theme()
            self.name_label.setText(profile.name)
            full_source = profile.source_path or profile.spec.target
            self.source_label.setText(elide_path(full_source, 26))
            self.source_label.setToolTip(f"原始路径：\n{full_source}")
            self.target_label.setText(elide_path(profile.spec.target, 36))
            self.target_label.setToolTip(f"目标程序：\n{profile.spec.target}")
            self.family_pill.set_status(profile.spec.family.label, "brand")

            # 统一状态语言：消灭“就绪”，规范为“运行中”与“未运行”
            active = service.active_process_for_profile(profile.id)
            if active:
                self.run_status_pill.set_status(f"● 运行中 (PID {active['pid']})", "success")
            else:
                self.run_status_pill.set_status("未运行", "neutral")

            # 元信息行
            levers = profile.levers or {}
            active_levers = [k.upper() for k, v in levers.items() if v]
            self.levers_summary_label.setText(" · ".join(active_levers) if active_levers else "无生效手段")
            quic_text = "阻断QUIC" if profile.disable_quic else "允许QUIC"
            self.quic_dns_label.setText(quic_text)
            self.launch_count_label.setText(f"已启动 {profile.launch_count} 次")

            # 活动历史流刷新 (紧凑时间线)
            self._render_activity_stream(profile.id)

            # 配置表单数据绑定
            idx = self.family_combo.findData(profile.spec.family.value)
            if idx >= 0:
                self.family_combo.setCurrentIndex(idx)

            evidence = "；".join(profile.spec.family_evidence) or "系统自动推断"
            self.evidence_label.setText(f"判定依据：{evidence}")
            self.meta_label.setText(f"PE架构：{profile.spec.arch}    子系统：{profile.spec.subsystem}")

            self.args_edit.setText(profile.spec.args or "")
            self.workdir_edit.setText(profile.spec.workdir or "")

            for key, card in self.lever_cards.items():
                card.setChecked(bool(levers.get(key, True)))

            self.quic_box.setChecked(bool(profile.disable_quic))
            self.remote_dns_box.setChecked(bool(profile.force_remote_dns))

            console_idx = self.console_combo.findData(profile.console_mode or "auto")
            if console_idx >= 0:
                self.console_combo.setCurrentIndex(console_idx)

            self.cmdline_extra_edit.setText(" ".join(profile.cmdline_extra or []))
            env_lines = [f"{k}={v}" for k, v in (profile.env_extra or {}).items()]
            self.env_extra_edit.setPlainText("\n".join(env_lines))
            self.no_proxy_edit.setText(", ".join(profile.no_proxy_extra or []))

            self.icon_label.setPixmap(profile_icon(profile).pixmap(38, 38))
        finally:
            self._loading = False

    def _render_activity_stream(self, profile_id: str) -> None:
        """渲染纯净紧凑时间线：时间 + 应用名 + 启动结果，高度随内容弹性收缩。"""
        while self.activity_box.count():
            item = self.activity_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        history = service.recent_launches_for_profile(profile_id, limit=3)
        if not history:
            tip = QLabel("○ 暂无运行活动记录")
            tip.setObjectName("Hint")
            tip.setStyleSheet("padding: 2px 0;")
            self.activity_box.addWidget(tip)
            return

        for entry in history:
            row = QWidget()
            r_layout = QHBoxLayout(row)
            r_layout.setContentsMargins(0, 3, 0, 3)
            r_layout.setSpacing(10)

            t_val = entry.get("timestamp") or time.time()
            time_str = datetime.datetime.fromtimestamp(t_val).strftime("%H:%M")
            time_lbl = QLabel(time_str)
            time_lbl.setStyleSheet(f"font-size: 11px; font-weight: 600; font-family: {tok.FONT_MONO}; color: {tok.get_current_theme().text_secondary};")
            r_layout.addWidget(time_lbl)

            dot = QLabel("●")
            dot.setStyleSheet(f"font-size: 8px; color: {tok.get_current_theme().success};")
            r_layout.addWidget(dot)

            app_name = (self._profile.name if self._profile else "") or "应用"
            name_lbl = QLabel(app_name)
            name_lbl.setStyleSheet("font-size: 11.5px; font-weight: 600;")
            r_layout.addWidget(name_lbl)

            res_lbl = QLabel("代理启动成功")
            res_lbl.setObjectName("Hint")
            r_layout.addWidget(res_lbl)

            r_layout.addStretch(1)
            self.activity_box.addWidget(row)

    def _collect(self) -> None:
        if self._loading or self._profile is None:
            return

        self._profile.name = self.name_label.text().strip() or self._profile.name
        self._profile.spec.args = self.args_edit.text().strip()
        self._profile.spec.workdir = self.workdir_edit.text().strip()

        levers = dict(self._profile.levers)
        for key, card in self.lever_cards.items():
            levers[key] = card.isChecked()
        self._profile.levers = levers
        self._profile.disable_quic = self.quic_box.isChecked()
        self._profile.force_remote_dns = self.remote_dns_box.isChecked()
        self._profile.console_mode = self.console_combo.currentData() or "auto"

        self._profile.cmdline_extra = [
            a for a in self.cmdline_extra_edit.text().strip().split(" ") if a
        ]

        env_dict: dict[str, str] = {}
        for line in self.env_extra_edit.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_dict[k.strip()] = v.strip()
        self._profile.env_extra = env_dict

        self._profile.no_proxy_extra = [
            h.strip()
            for h in self.no_proxy_edit.text().replace(";", ",").split(",")
            if h.strip()
        ]

        self.saveRequested.emit(self._profile)

    def _on_family_changed(self, index: int) -> None:
        if self._loading or self._profile is None:
            return
        family_val = self.family_combo.itemData(index)
        family = Family(family_val)
        if family == self._profile.spec.family:
            return
        self._profile.spec.family = family
        self._profile.spec.family_evidence = ["用户在控制中心手动修改"]
        family_mod.apply_family_defaults(self._profile.spec, family)
        self.set_profile(self._profile)
        self.saveRequested.emit(self._profile)

    def _emit(self, signal: pyqtSignal) -> None:
        if self._profile is not None:
            signal.emit(self._profile.id)
