"""顶部软件名：`Tunless ● Proxy`（三段式极简字标）。

设计（方案 A「极简字重节奏」，比例照参考图量出来的）：

    Tunless    细体、中性灰白 —— 用字重和颜色压住节奏
    ●          3px 绿色圆点   —— 与右侧「运行状态」胶囊同一个绿，做视觉呼应
    Proxy      粗体、**横向渐变**：左端近纯白 → 右端冰蓝

`Proxy` 的渐变是照着参考图量出来的：同一笔的上下颜色一致（不是纵向渐变），
整词从左到右由 `#FFFFFF` 过渡到 `#7DD3FC`（最右端实测峰值 ≈ `#A1C7FA`，
偏暗是缩放模糊吃掉的）。QSS 没有"把渐变剪进文字"的能力（`background-clip: text`
是 Web 的东西），所以这一段自己 `paintEvent` 用 `QPen(QBrush(渐变))` 画。

刻意做成**静态**：不发光、不描边、不加背景、不动画。以前那套多层渐变 + 流光 +
外发光的动效字标（`brand.py`）已经整体删掉，所以这里也不需要画布、字形路径与
定时器 —— 一个 `QHBoxLayout` 加三个控件就够，尺寸完全由字体度量决定，
因此天然与左侧全局图标、右侧端点胶囊保持基线居中。

颜色随主题走（同一套设计语言，浅色主题换成深色版）：

    深色主题   Tunless #E2E8F0   点 #10B981   Proxy #FFFFFF → #7DD3FC
    浅色主题   Tunless #334155   点 #10B981   Proxy #0F172A → #0284C7

`#E2E8F0` 那种亮灰白放在浅色底上几乎看不见（对比度不到 1.1:1），所以浅色主题
不是"照抄颜色"，而是照抄**节奏**：细体深灰 + 同一个绿点 + 深色→深天蓝的渐变。
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
)
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import theme_tokens as tok

#: 微点直径与两侧间距。**这两个数字是照着参考图量出来的**，不是拍脑袋：
#: 参考图里 点直径/大写高 ≈ 0.25、间距/大写高 ≈ 0.31（而且点与两侧间距基本相等）。
#: 按 14px 字号（Segoe UI Variable 的大写高约 10px）换算就是 2.5px 与 3px，
#: 圆点取 3px（再小在高 DPI 下就糊成一个点了），间距取 4px（保持"点宽的 1.2~1.3 倍"
#: 这个手感的比例）。想回到一开始字面写的 4/6，改这两个数即可。
DOT_SIZE = 3
DEFAULT_SPACING = 4

#: 点的**竖直位置**：点中心落在大写高从上往下 57% 处。
#: 参考图实测 0.570（点 y 92..126 中心 109，大写顶 32、基线 167 → 大写高 135）。
#: 直接放进布局里垂直居中会落在 0.46 左右（居中于行框，不是居中的大写高），
#: 看着就是"点偏高了一点" —— 用户反馈的正是这个。所以位置按字体度量自己算。
DOT_CENTER_RATIO = 0.57

#: (细体字, 微点, Proxy 渐变左端, Proxy 渐变右端)。
DARK_COLORS: tuple[str, str] = ("#E2E8F0", "#10B981")
DARK_GRADIENT: tuple[str, str] = ("#FFFFFF", "#7DD3FC")
LIGHT_COLORS: tuple[str, str] = ("#334155", "#10B981")
LIGHT_GRADIENT: tuple[str, str] = ("#0F172A", "#0284C7")


class GradientLabel(QLabel):
    """把文字填充成横向渐变的标签。

    QLabel 自身只会用单色画字，所以这里接管 `paintEvent`：把画笔换成
    `QLinearGradient` 的刷子直接 `drawText`（Qt 用画笔的**刷子**填充字形，
    笔宽 0 表示不描边）。排版参数与 QLabel 保持一致，因此 sizeHint 与
    垂直居中都不受影响。
    """

    def __init__(self, text: str, left: str, right: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._colors = (left, right)

    def colors(self) -> tuple[str, str]:
        return self._colors

    def set_colors(self, left: str, right: str) -> None:
        self._colors = (left, right)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = self.font()
        painter.setFont(font)
        # 渐变跨度按文字实际宽度取，而不是控件宽度：控件在布局里可能被拉宽，
        # 那样右端颜色就永远到不了（渐变的终点会落在文字外面）。
        width = max(1, self.fontMetrics().horizontalAdvance(self.text()))
        gradient = QLinearGradient(0, 0, width, 0)
        gradient.setColorAt(0.0, QColor(self._colors[0]))
        gradient.setColorAt(1.0, QColor(self._colors[1]))
        painter.setPen(QPen(QBrush(gradient), 0))
        painter.drawText(self.rect(), int(self.alignment()), self.text())


class Dot(QWidget):
    """3px 上下的绿色圆点。

    自己画而不是用 QSS `border-radius`：3px 见方配 1px 圆角出来是"圆角方块"，
    看着像个小十字；`drawEllipse` 是抗锯齿的真圆，而且直径与竖直位置都能精确控制。

    竖直位置由 `align_to(font)` 按字体度量算（见 DOT_CENTER_RATIO）：控件高度取
    行框高度，圆点画在"大写顶 + 57% 大写高"处。这样它和两侧文字一样被布局居中，
    但视觉上落在参考图那个略低于字面中心的位置。
    """

    def __init__(self, diameter: int, color: str, parent=None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._color = QColor(color)
        self.center_y = diameter / 2
        self.setFixedSize(diameter, diameter)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def align_to(self, font: QFont) -> None:
        """把自己摆到参考图那个高度：点中心 = 大写顶 + DOT_CENTER_RATIO × 大写高。"""
        metrics = QFontMetrics(font)
        cap = metrics.capHeight()
        cap_top = metrics.ascent() - cap  # 相对行框顶部
        self.center_y = cap_top + cap * DOT_CENTER_RATIO
        # 高度取行框高度：与两侧 QLabel 同高，布局居中后基准一致
        self.setFixedSize(self._diameter, metrics.height())
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        radius = self._diameter / 2
        painter.drawEllipse(
            QRectF(0.0, self.center_y - radius, float(self._diameter), float(self._diameter))
        )


class TitleMark(QWidget):
    """三段式软件名字标。"""

    def __init__(
        self,
        parent=None,
        pixel_size: int = 14,
        spacing: int = DEFAULT_SPACING,
    ) -> None:
        super().__init__(parent)
        self._pixel_size = pixel_size
        self._spacing = spacing

        self.label_left = QLabel("Tunless", self)
        self.dot = Dot(DOT_SIZE, DARK_COLORS[1], self)
        self.label_right = GradientLabel("Proxy", *DARK_GRADIENT, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label_left, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.label_right, 0, Qt.AlignmentFlag.AlignVCenter)

        # 绑定方法连接：控件销毁时 PyQt 会自动断开（lambda 会把控件"永生"持有）
        tok.theme_mgr.themeChanged.connect(self._apply_colors)
        self._apply_colors()

    # ------------------------------------------------------------ 外观

    def colors(self) -> tuple[str, str, str]:
        """当前主题实际用的颜色：(Tunless, 微点, Proxy 渐变终点)。"""
        left, dot = DARK_COLORS if tok.get_current_theme().is_dark else LIGHT_COLORS
        gradient = self.proxy_gradient()
        return (left, dot, gradient[1])

    def proxy_gradient(self) -> tuple[str, str]:
        """`Proxy` 那一段的横向渐变端点（左 → 右）。"""
        return DARK_GRADIENT if tok.get_current_theme().is_dark else LIGHT_GRADIENT

    def _apply_colors(self, *_args) -> None:
        left, dot = DARK_COLORS if tok.get_current_theme().is_dark else LIGHT_COLORS
        size = self._pixel_size
        # background 必须显式声明 transparent：主题 QSS 里给卡片/窗口设过背景，
        # 不写就会在字标后面压出一块色块（用户要求"背景完全透明"）。
        self.label_left.setStyleSheet(
            f"color: {left}; font-size: {size}px; font-weight: 300;"
            " background: transparent; border: none; padding: 0;"
        )
        self.label_right.setStyleSheet(
            f"font-size: {size}px; font-weight: bold;"
            " background: transparent; border: none; padding: 0;"
        )
        self.label_right.set_colors(*self.proxy_gradient())
        self.dot.set_color(dot)
        self.label_left.setFont(_weighted(self.label_left.font(), size, 300))
        self.label_right.setFont(_weighted(self.label_right.font(), size, 700))
        # 点的竖直位置跟着左侧文字（同字号、同字重场景）算
        self.dot.align_to(self.label_left.font())


def _weighted(font: QFont, pixel_size: int, weight: int) -> QFont:
    """把字号/字重也落到 QFont 上。

    Qt 的 QSS 解析器对 `font-weight: 300` 这种数值并不是所有版本都认（有的会
    直接忽略、退回正常字重），而"细体 vs 粗体"正是这枚字标的全部节奏来源 ——
    所以两边都设一遍：QSS 负责颜色，QFont 负责字号与字重。
    """
    out = QFont(font)
    out.setPixelSize(pixel_size)
    out.setWeight(QFont.Weight(weight))
    return out
