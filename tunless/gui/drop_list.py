"""现代化流体应用列表 (运行态感知与高信息密度)。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon, QPainter,
    QPainterPath, QPen
)
from PyQt6.QtWidgets import (
    QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate
)

from .. import service
from ..detect.lnk import is_supported_drop
from ..model import Family, Profile
from . import theme_tokens as tok
from .widgets import family_badge, profile_icon, profile_tooltip

ROLE_PROFILE_ID = Qt.ItemDataRole.UserRole + 1
ROLE_PROFILE_NAME = Qt.ItemDataRole.UserRole + 2
ROLE_PROFILE_FAMILY = Qt.ItemDataRole.UserRole + 3
ROLE_PROFILE_TARGET = Qt.ItemDataRole.UserRole + 4
ROLE_PROFILE_ICON = Qt.ItemDataRole.UserRole + 5
ROLE_PROFILE_IS_ACTIVE = Qt.ItemDataRole.UserRole + 6
ROLE_PROFILE_PID = Qt.ItemDataRole.UserRole + 7
ROLE_PROFILE_LAUNCH_COUNT = Qt.ItemDataRole.UserRole + 8


class ProfileItemDelegate(QStyledItemDelegate):
    """现代化控制中心列表委托：高清图标、实时运行状态呼吸徽标、家族小胶囊。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 58)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        th = tok.get_current_theme()
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # 1. 绘制单层微晶卡片底色
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)

        if is_selected:
            bg_color = tok.parse_color(th.brand_primary)
            bg_color.setAlpha(36 if th.is_dark else 28)
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
        painter.drawRoundedRect(rect, 10, 10)

        # 2. 绘制高清图标 (34x34)
        icon: QIcon = index.data(ROLE_PROFILE_ICON)
        icon_rect = QRectF(rect.x() + 10, rect.y() + (rect.height() - 34) / 2.0, 34, 34)
        if icon and not icon.isNull():
            pixmap = icon.pixmap(34, 34)
            painter.drawPixmap(int(icon_rect.x()), int(icon_rect.y()), pixmap)

        # 3. 提取数据
        text_x = rect.x() + 52
        name = index.data(ROLE_PROFILE_NAME) or ""
        family_str = index.data(ROLE_PROFILE_FAMILY) or ""
        is_active = bool(index.data(ROLE_PROFILE_IS_ACTIVE))
        pid = index.data(ROLE_PROFILE_PID) or 0
        launch_count = index.data(ROLE_PROFILE_LAUNCH_COUNT) or 0

        # 4. 绘制右上角状态微胶囊 (运行中 / 未运行，固定靠右布局)
        if is_active:
            status_text = "● 运行中"
            badge_bg = QColor(16, 185, 129, 42 if th.is_dark else 30)
            badge_fg = QColor(52, 211, 153) if th.is_dark else QColor(5, 150, 105)
            badge_border = QColor(16, 185, 129, 90 if th.is_dark else 70)
        else:
            # 中性未运行胶囊：与运行中胶囊同构（半透底 + 细描边），风格完全统一
            status_text = "未运行"
            badge_bg = tok.parse_color(th.badge_neutral_bg)
            badge_fg = tok.parse_color(th.text_secondary)
            badge_border = tok.parse_color(th.badge_neutral_border)

        st_font = QFont(painter.font())
        st_font.setPointSize(8)
        st_font.setWeight(QFont.Weight.Medium)
        painter.setFont(st_font)
        st_metrics = painter.fontMetrics()
        st_w = st_metrics.horizontalAdvance(status_text) + 10
        st_rect = QRectF(rect.right() - st_w - 6, rect.y() + 8, st_w, 16)

        painter.setBrush(QBrush(badge_bg))
        painter.setPen(QPen(badge_border, 1))
        painter.drawRoundedRect(st_rect, 8, 8)
        painter.setPen(badge_fg)
        painter.drawText(st_rect, Qt.AlignmentFlag.AlignCenter, status_text)

        # 5. 绘制主标题 (按可用空间严格截断，超长自动变为 DeepSeek...)
        avail_title_w = max(30, int(st_rect.left() - text_x - 6))
        name_font = QFont(painter.font())
        name_font.setPointSize(10)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(tok.parse_color(th.text_primary))
        elided_title = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, avail_title_w)
        painter.drawText(
            QRectF(text_x, rect.y() + 6, avail_title_w, 20),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided_title
        )

        # 6. 绘制次级信息行 (家族小药丸 + 简洁启动次数)
        sub_y = rect.y() + 30
        badge_w = len(family_str) * 9 + 12
        badge_rect = QRectF(text_x, sub_y, badge_w, 16)

        if "Electron" in family_str:
            b_bg = QColor(99, 102, 241, 35 if th.is_dark else 25)
            b_fg = QColor(165, 180, 252) if th.is_dark else QColor(79, 70, 229)
        elif "WebView" in family_str:
            b_bg = QColor(14, 165, 233, 35 if th.is_dark else 25)
            b_fg = QColor(125, 211, 252) if th.is_dark else QColor(2, 132, 199)
        elif "命令" in family_str:
            b_bg = QColor(16, 185, 129, 35 if th.is_dark else 25)
            b_fg = QColor(110, 231, 183) if th.is_dark else QColor(5, 150, 105)
        else:
            b_bg = tok.parse_color(th.badge_neutral_bg)
            b_fg = tok.parse_color(th.text_secondary)

        painter.setBrush(QBrush(b_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 8, 8)

        f_font = QFont(painter.font())
        f_font.setPointSize(8)
        f_font.setWeight(QFont.Weight.Medium)
        painter.setFont(f_font)
        painter.setPen(b_fg)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, family_str)

        # 统计文本 (同样自适应防重叠)
        stat_text = f"启动 {launch_count} 次" if launch_count else "未启动"
        cnt_font = QFont(painter.font())
        cnt_font.setPointSize(8)
        painter.setFont(cnt_font)
        painter.setPen(tok.parse_color(th.text_muted))
        avail_stat_w = max(20, int(rect.right() - (text_x + badge_w + 6) - 6))
        elided_stat = painter.fontMetrics().elidedText(stat_text, Qt.TextElideMode.ElideRight, avail_stat_w)
        stat_rect = QRectF(text_x + badge_w + 6, sub_y, avail_stat_w, 16)
        painter.drawText(stat_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_stat)

        painter.restore()


class ProfileListWidget(QListWidget):
    """支持拖拽、运行态感知与微晶卡片渲染的应用列表。"""

    pathsDropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ProfileList")
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setSpacing(2)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.delegate = ProfileItemDelegate(self)
        self.setItemDelegate(self.delegate)

        tok.theme_mgr.themeChanged.connect(self.viewport().update)

    # ------------------------------------------------------------ 拖拽

    @staticmethod
    def _paths_from_event(event) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
        return paths

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        paths = self._paths_from_event(event)
        if any(is_supported_drop(path) for path in paths):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [p for p in self._paths_from_event(event) if is_supported_drop(p)]
        if paths:
            self.pathsDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ------------------------------------------------------------ 内容

    def set_profiles(self, profiles: list[Profile], selected_id: str | None = None) -> None:
        self.blockSignals(True)
        self.clear()
        for profile in profiles:
            family_str = family_badge(profile.spec.family)
            icon = profile_icon(profile)
            active_info = service.active_process_for_profile(profile.id)

            item = QListWidgetItem()
            item.setData(ROLE_PROFILE_ID, profile.id)
            item.setData(ROLE_PROFILE_NAME, profile.name)
            item.setData(ROLE_PROFILE_FAMILY, family_str)
            item.setData(ROLE_PROFILE_TARGET, profile.spec.target.rsplit("\\", 1)[-1])
            item.setData(ROLE_PROFILE_ICON, icon)
            item.setData(ROLE_PROFILE_IS_ACTIVE, active_info is not None)
            item.setData(ROLE_PROFILE_PID, active_info["pid"] if active_info else 0)
            item.setData(ROLE_PROFILE_LAUNCH_COUNT, profile.launch_count)
            item.setToolTip(profile_tooltip(profile))
            self.addItem(item)
        self.blockSignals(False)

        if selected_id:
            self.select_by_id(selected_id)
        elif self.count():
            self.setCurrentRow(0)

    def select_by_id(self, profile_id: str) -> None:
        for row in range(self.count()):
            item = self.item(row)
            if item.data(ROLE_PROFILE_ID) == profile_id:
                self.setCurrentRow(row)
                return

    def update_profile(self, profile: Profile) -> bool:
        """就地刷新一个条目。"""
        for row in range(self.count()):
            item = self.item(row)
            if item.data(ROLE_PROFILE_ID) != profile.id:
                continue
            family_str = family_badge(profile.spec.family)
            icon = profile_icon(profile)
            active_info = service.active_process_for_profile(profile.id)

            item.setData(ROLE_PROFILE_NAME, profile.name)
            item.setData(ROLE_PROFILE_FAMILY, family_str)
            item.setData(ROLE_PROFILE_TARGET, profile.spec.target.rsplit("\\", 1)[-1])
            item.setData(ROLE_PROFILE_ICON, icon)
            item.setData(ROLE_PROFILE_IS_ACTIVE, active_info is not None)
            item.setData(ROLE_PROFILE_PID, active_info["pid"] if active_info else 0)
            item.setData(ROLE_PROFILE_LAUNCH_COUNT, profile.launch_count)
            item.setToolTip(profile_tooltip(profile))
            return True
        return False

    def current_profile_id(self) -> str | None:
        item = self.currentItem()
        return item.data(ROLE_PROFILE_ID) if item else None
