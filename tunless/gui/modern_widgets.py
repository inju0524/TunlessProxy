"""现代产品级 UI 交互组件库 (全主题自适应与动态换色)。"""

from __future__ import annotations

import math
from PyQt6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize,
    Qt, pyqtProperty, pyqtSignal, QTimer
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen
)
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from . import icons, theme_tokens as tok


# =========================================================================
# 1. 呼吸脉冲状态点 (PulseDot)
# =========================================================================

class PulseDot(QWidget):
    """带微晕呼吸脉冲发光的状态指示点。"""

    def __init__(self, color: str | None = None, pulse: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        th = tok.get_current_theme()
        self._color = QColor(color or th.success)
        self._pulse = pulse
        self._phase = 0.0
        self.setFixedSize(16, 16)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._step)
        if self._pulse:
            self._timer.start()

    def _step(self) -> None:
        self._phase = (self._phase + 0.09) % (2 * math.pi)
        self.update()

    def set_color(self, color: str | QColor) -> None:
        self._color = QColor(color)
        self.update()

    def set_pulse(self, pulse: bool) -> None:
        self._pulse = pulse
        if pulse and not self._timer.isActive():
            self._timer.start()
        elif not pulse and self._timer.isActive():
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        base_r = 3.5

        if self._pulse:
            aura_scale = 0.5 + 0.5 * math.sin(self._phase)
            aura_r = base_r + aura_scale * 3.5
            aura_alpha = int(45 + aura_scale * 65)

            halo_color = QColor(self._color)
            halo_color.setAlpha(aura_alpha)
            painter.setBrush(QBrush(halo_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, aura_r, aura_r)

        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, base_r, base_r)


# =========================================================================
# 2. 状态药丸胶囊 (StatusPill)
# =========================================================================

class StatusPill(QFrame):
    """超椭圆微晶胶囊状态组件 (全主题自适应)。"""

    def __init__(self, text: str = "", tone: str = "success", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusPill")
        self._tone = tone
        self.setFixedHeight(22)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 8, 1)
        layout.setSpacing(5)

        self.dot = PulseDot(pulse=(tone in ("success", "brand")))
        layout.addWidget(self.dot)

        self.label = QLabel(text)
        layout.addWidget(self.label)

        self._apply_style()
        tok.theme_mgr.themeChanged.connect(self._apply_style)

    def set_status(self, text: str, tone: str = "success") -> None:
        self._tone = tone
        self.label.setText(text)
        self._apply_style()

    def _apply_style(self) -> None:
        th = tok.get_current_theme()
        color_map = {
            "success": th.success,
            "warn": th.warning,
            "danger": th.danger,
            "brand": th.brand_primary,
            "neutral": th.text_muted,
        }
        active_color = color_map.get(self._tone, th.success)
        self.dot.set_color(active_color)
        self.dot.set_pulse(self._tone in ("success", "brand"))

        bg_map = {
            "success": th.success_bg,
            "warn": th.warning_bg,
            "danger": th.danger_bg,
            "brand": th.brand_light_bg,
            "neutral": th.border_subtle,
        }
        border_map = {
            "success": th.success_border,
            "warn": th.warning_border,
            "danger": th.danger_border,
            "brand": th.border_focus,
            "neutral": th.border_default,
        }
        bg = bg_map.get(self._tone, th.border_subtle)
        border = border_map.get(self._tone, th.border_default)

        self.label.setStyleSheet(f"color: {th.text_primary}; font-size: 11px; font-weight: 500; background: transparent;")
        self.setStyleSheet(f"""
            QFrame#StatusPill {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 11px;
            }}
        """)


# =========================================================================
# 3. Apple 风格流体滑动开关 (ModernSwitch)
# =========================================================================

class ModernSwitch(QWidget):
    """带丝滑阻尼位移与平滑背景插值的 Apple 风格滑动开关。"""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._progress = 1.0 if checked else 0.0
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        tok.theme_mgr.themeChanged.connect(self.update)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        if self._checked == checked:
            return
        self._checked = checked
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self.toggled.emit(self._checked)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, val: float) -> None:
        self._progress = val
        self.update()

    progress = pyqtProperty(float, get_progress, set_progress)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        th = tok.get_current_theme()
        w = self.width()
        h = self.height()
        radius = h / 2.0

        # 关闭态轨道：深浅主题各自使用明确的中性色，杜绝 rgba 解析失败变成纯黑
        off_color = QColor(60, 72, 100) if th.is_dark else QColor(203, 213, 225)
        on_color = tok.parse_color(th.brand_primary)

        r = int(off_color.red() + (on_color.red() - off_color.red()) * self._progress)
        g = int(off_color.green() + (on_color.green() - off_color.green()) * self._progress)
        b = int(off_color.blue() + (on_color.blue() - off_color.blue()) * self._progress)
        bg_color = QColor(r, g, b)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        painter.fillPath(path, QBrush(bg_color))

        thumb_diameter = h - 4
        travel = w - thumb_diameter - 4
        thumb_x = 2 + travel * self._progress
        thumb_y = 2

        # 阴影与实心滑块
        painter.setBrush(QBrush(QColor(0, 0, 0, 35)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(thumb_x - 0.5, thumb_y + 1, thumb_diameter + 1, thumb_diameter))

        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(QRectF(thumb_x, thumb_y, thumb_diameter, thumb_diameter))


# =========================================================================
# 4. 流体卡片开关项 (SwitchCard)
# =========================================================================

class SwitchCard(QFrame):
    """现代卡片式开关项 (全主题自适应)。"""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, subtitle: str = "", checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SwitchCard")
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_label = QLabel(title)
        text_layout.addWidget(self.title_label)

        if subtitle:
            self.sub_label = QLabel(subtitle)
            self.sub_label.setWordWrap(True)
            text_layout.addWidget(self.sub_label)

        layout.addLayout(text_layout, 1)

        self.switch = ModernSwitch(checked=checked)
        self.switch.toggled.connect(self.toggled.emit)
        layout.addWidget(self.switch)

        self._update_style()
        tok.theme_mgr.themeChanged.connect(self._update_style)

    def isChecked(self) -> bool:  # noqa: N802
        return self.switch.isChecked()

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        self.switch.setChecked(checked)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.switch.setChecked(not self.switch.isChecked())
            event.accept()
        else:
            super().mousePressEvent(event)

    def _update_style(self) -> None:
        th = tok.get_current_theme()
        self.title_label.setStyleSheet(f"color: {th.text_primary}; font-size: 13px; font-weight: 600; background: transparent;")
        if hasattr(self, "sub_label"):
            self.sub_label.setStyleSheet(f"color: {th.text_muted}; font-size: 11px; background: transparent;")
        self.setStyleSheet(f"""
            QFrame#SwitchCard {{
                background-color: {th.bg_card};
                border: 1px solid {th.border_subtle};
                border-radius: {tok.RADIUS_MD}px;
            }}
            QFrame#SwitchCard:hover {{
                background-color: {th.bg_card_hover};
                border-color: {th.border_hover};
            }}
        """)


# =========================================================================
# 5. Apple 风格分段控制器 (SegmentedControl)
# =========================================================================

class SegmentedControl(QWidget):
    """药丸平滑滑动指示器的分段切换器 (全主题自适应)。"""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = items
        self._current_index = 0
        self._indicator_x = 2.0
        self._indicator_w = 60.0
        self.setFixedHeight(30)

        self._anim = QPropertyAnimation(self, b"indicatorX", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        tok.theme_mgr.themeChanged.connect(self.update)

    def currentIndex(self) -> int:  # noqa: N802
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self._items) and index != self._current_index:
            self._current_index = index
            self._animate_to_index(index)
            self.currentIndexChanged.emit(index)

    def get_indicator_x(self) -> float:
        return self._indicator_x

    def set_indicator_x(self, val: float) -> None:
        self._indicator_x = val
        self.update()

    indicatorX = pyqtProperty(float, get_indicator_x, set_indicator_x)

    def _item_rect(self, index: int) -> QRectF:
        if not self._items:
            return QRectF()
        pad = 2.0
        total_w = self.width() - pad * 2
        item_w = total_w / len(self._items)
        return QRectF(pad + index * item_w, pad, item_w, self.height() - pad * 2)

    def _animate_to_index(self, index: int) -> None:
        target_rect = self._item_rect(index)
        self._anim.stop()
        self._anim.setStartValue(self._indicator_x)
        self._anim.setEndValue(target_rect.x())
        self._indicator_w = target_rect.width()
        self._anim.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        rect = self._item_rect(self._current_index)
        self._indicator_x = rect.x()
        self._indicator_w = rect.width()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pad = 2.0
            total_w = self.width() - pad * 2
            if total_w > 0 and self._items:
                item_w = total_w / len(self._items)
                clicked_idx = int((event.position().x() - pad) / item_w)
                if 0 <= clicked_idx < len(self._items):
                    self.setCurrentIndex(clicked_idx)
            event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        th = tok.get_current_theme()
        bg_radius = 7.0
        bg_rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)

        # 槽体沉降：极低视觉重量，与背景自然融合，无粗厚大框
        slot_bg = QColor(0, 0, 0, 24) if th.is_dark else QColor(15, 23, 42, 14)
        painter.setBrush(QBrush(slot_bg))
        painter.setPen(QPen(tok.parse_color(th.border_subtle), 1))
        painter.drawRoundedRect(bg_rect, bg_radius, bg_radius)

        # 滑动指示器药丸 (轻量悬浮，激活感明确)
        if self._items:
            rect = self._item_rect(self._current_index)
            pill_h = self.height() - 4
            pill_rect = QRectF(self._indicator_x, 2, rect.width(), pill_h)
            pill_radius = 6.0

            if not th.is_dark:
                painter.setBrush(QBrush(QColor("#ffffff")))
                painter.setPen(QPen(QColor(15, 23, 42, 22), 1))
            else:
                pill_bg = tok.parse_color(th.bg_card)
                painter.setBrush(QBrush(pill_bg))
                painter.setPen(QPen(QColor(255, 255, 255, 20), 1))

            painter.drawRoundedRect(pill_rect, pill_radius, pill_radius)

        # 文本：激活项加粗高亮，非激活项弱化呈现
        font = painter.font()
        font.setFamily("Segoe UI, Microsoft YaHei UI, sans-serif")
        font.setPointSize(9)

        for i, text in enumerate(self._items):
            item_rect = self._item_rect(i)
            is_active = (i == self._current_index)
            font.setWeight(QFont.Weight.DemiBold if is_active else QFont.Weight.Normal)
            painter.setFont(font)
            text_color = tok.parse_color(th.text_primary) if is_active else tok.parse_color(th.text_muted)
            painter.setPen(text_color)
            painter.drawText(item_rect, Qt.AlignmentFlag.AlignCenter, text)


# =========================================================================
# 6. 流体触感按钮 (FluidButton)
# =========================================================================

class FluidButton(QPushButton):
    """带微按压弹性与晶莹渐变的现代按钮 (全主题自适应)。"""

    def __init__(self, text: str = "", variant: str = "secondary", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._variant = variant
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        tok.theme_mgr.themeChanged.connect(self._apply_style)

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self._apply_style()

    def _apply_style(self) -> None:
        th = tok.get_current_theme()
        if self._variant == "primary":
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {th.brand_gradient_start}, stop:1 {th.brand_gradient_end});
                    color: #ffffff;
                    border: 1px solid rgba(255, 255, 255, 0.28);
                    border-radius: {tok.RADIUS_MD}px;
                    padding: 8px 18px;
                    font-size: 13px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: {th.brand_gradient_start};
                    border-color: rgba(255, 255, 255, 0.45);
                }}
                QPushButton:pressed {{
                    background: {th.brand_pressed};
                    padding-top: 9px;
                    padding-bottom: 7px;
                }}
                QPushButton:disabled {{
                    background: {th.border_subtle};
                    color: {th.text_muted};
                    border-color: transparent;
                }}
            """)
        elif self._variant == "danger":
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {th.danger_bg};
                    color: {th.danger};
                    border: 1px solid {th.danger_border};
                    border-radius: {tok.RADIUS_MD}px;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {th.danger}25;
                    border-color: {th.danger};
                }}
                QPushButton:pressed {{
                    padding-top: 9px;
                    padding-bottom: 7px;
                }}
            """)
        else:  # secondary
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {th.border_subtle};
                    color: {th.text_primary};
                    border: 1px solid {th.border_default};
                    border-radius: {tok.RADIUS_MD}px;
                    padding: 6px 14px;
                    font-size: 12px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {th.border_hover};
                    border-color: {th.border_hover};
                }}
                QPushButton:pressed {{
                    background: {th.border_subtle};
                    padding-top: 7px;
                    padding-bottom: 5px;
                }}
                QPushButton:disabled {{
                    color: {th.text_muted};
                    background: transparent;
                }}
            """)


# =========================================================================
# 7. 吸附光晕拖拽岛 (DropZoneIsland)
# =========================================================================

class DropZoneIsland(QFrame):
    """现代拖拽放置岛 (全主题自适应)。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZoneIsland")
        self._active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("拖入快捷方式或程序")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.sub_label = QLabel("支持 .lnk · .exe · .bat · .cmd")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sub_label)

        self._update_style()
        tok.theme_mgr.themeChanged.connect(self._update_style)

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self._update_style()

    def _update_style(self) -> None:
        th = tok.get_current_theme()
        icon_color = th.brand_primary if self._active else th.text_muted
        self.icon_label.setPixmap(icons.icon_drop(icon_color, 20).pixmap(20, 20))
        self.title_label.setStyleSheet(f"color: {th.text_primary}; font-size: 12.5px; font-weight: 600; background: transparent;")
        self.sub_label.setStyleSheet(f"color: {th.text_muted}; font-size: 11px; background: transparent;")

        if self._active:
            self.setStyleSheet(f"""
                QFrame#DropZoneIsland {{
                    background-color: {th.brand_light_bg};
                    border: 2px dashed {th.brand_primary};
                    border-radius: {tok.RADIUS_LG}px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#DropZoneIsland {{
                    background-color: {th.border_subtle};
                    border: 1px dashed {th.border_default};
                    border-radius: {tok.RADIUS_LG}px;
                }}
                QFrame#DropZoneIsland:hover {{
                    background-color: {th.bg_card_hover};
                    border-color: {th.border_hover};
                }}
            """)


# =========================================================================
# 8. 毛玻璃卡片基类 (GlassCard)
# =========================================================================

class GlassCard(QFrame):
    """具备亚像素微反光边框与微晶底色的容器卡片 (全主题自适应)。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self._update_style()
        tok.theme_mgr.themeChanged.connect(self._update_style)

    def _update_style(self) -> None:
        th = tok.get_current_theme()
        self.setStyleSheet(f"""
            QFrame#GlassCard {{
                background-color: {th.bg_card};
                border: 1px solid {th.border_subtle};
                border-radius: {tok.RADIUS_LG}px;
            }}
        """)


# =========================================================================
# 9. 纯图标方形按钮 (IconButton)
# =========================================================================

class IconButton(QPushButton):
    """纯图标方形按钮：零内边距 + 显式 iconSize，保证图标严格视觉居中。

    全局 QPushButton 样式带 `padding: 6px 14px`，若直接用于 30x30 的图标按钮，
    内容区会被压缩到 2px 宽，导致图标偏移甚至被裁切。这里显式覆盖 padding 与
    margin，并指定 iconSize，同时随主题切换自动重绘图标配色。
    """

    def __init__(
        self,
        icon_factory,
        tooltip: str = "",
        box: int = 30,
        icon_size: int = 15,
        variant: str = "solid",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_factory = icon_factory
        self._icon_size = icon_size
        self._box = box
        self._variant = variant
        self.setFixedSize(box, box)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        if tooltip:
            self.setToolTip(tooltip)
        self._apply_style()
        tok.theme_mgr.themeChanged.connect(self._apply_style)

    def _apply_style(self) -> None:
        th = tok.get_current_theme()
        self.setIcon(self._icon_factory(th.text_secondary, self._icon_size))
        radius = 8 if self._box >= 28 else 6

        if self._variant == "ghost":
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: {radius}px;
                    padding: 0px;
                    margin: 0px;
                }}
                QPushButton:hover {{
                    background: {th.border_hover};
                }}
                QPushButton:pressed {{
                    background: {th.border_subtle};
                }}
                QPushButton::menu-indicator {{
                    image: none;
                    width: 0px;
                }}
            """)
            return

        self.setStyleSheet(f"""
            QPushButton {{
                background: {th.border_subtle};
                border: 1px solid {th.border_default};
                border-radius: {radius}px;
                padding: 0px;
                margin: 0px;
            }}
            QPushButton:hover {{
                background: {th.border_hover};
                border-color: {th.border_hover};
            }}
            QPushButton:pressed {{
                background: {th.border_subtle};
            }}
            QPushButton::menu-indicator {{
                image: none;
                width: 0px;
            }}
        """)
