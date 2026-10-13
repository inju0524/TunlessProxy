"""现代线性矢量图标库 (Lucide / SF Symbols 风格，纯矢量绘制，零第三方依赖)。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
)


def _make_pixmap(size: int = 16) -> tuple[QPixmap, QPainter]:
    dpr = 2.0  # 视网膜双倍采样，保证抗锯齿与极高清晰度
    canvas_size = int(size * dpr)
    pix = QPixmap(canvas_size, canvas_size)
    pix.fill(Qt.GlobalColor.transparent)
    # 注意：不要调用 setDevicePixelRatio —— QIcon 会据此把图裁切而非缩放，
    # 导致图标只显示左上角一小块。保持 dpr=1，由 QIcon 平滑缩放即可。
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(dpr, dpr)
    return pix, painter


def icon_play(color: str = "#ffffff", size: int = 16) -> QIcon:
    """播放三角形 (启动代理)。"""
    pix, p = _make_pixmap(size)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    # 居中等腰三角形
    path.moveTo(4.5, 3.5)
    path.lineTo(12.5, 8.0)
    path.lineTo(4.5, 12.5)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def icon_activity(color: str = "#94a3b8", size: int = 16) -> QIcon:
    """折线脉冲图 (网络链路诊断)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(2.0, 8.5)
    path.lineTo(5.0, 8.5)
    path.lineTo(7.0, 3.5)
    path.lineTo(9.5, 12.5)
    path.lineTo(11.5, 8.5)
    path.lineTo(14.0, 8.5)
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def icon_palette(color: str = "#94a3b8", size: int = 16) -> QIcon:
    """调色盘 (外观主题)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # 调色盘轮廓
    path = QPainterPath()
    path.addEllipse(QRectF(2.0, 2.0, 12.0, 12.0))
    p.drawPath(path)
    # 内部三色孔
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(5.0, 6.0), 1.0, 1.0)
    p.drawEllipse(QPointF(8.0, 4.5), 1.0, 1.0)
    p.drawEllipse(QPointF(11.0, 6.5), 1.0, 1.0)
    p.end()
    return QIcon(pix)


def icon_edit(color: str = "#94a3b8", size: int = 14) -> QIcon:
    """细线铅笔 (重命名)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(3.0, 11.0)
    path.lineTo(1.5, 12.5)
    path.lineTo(1.5, 10.5)
    path.lineTo(8.5, 3.5)
    path.lineTo(10.5, 5.5)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def icon_plus(color: str = "#ffffff", size: int = 14) -> QIcon:
    """细线十字 (添加/导入)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(7.0, 3.0), QPointF(7.0, 11.0))
    p.drawLine(QPointF(3.0, 7.0), QPointF(11.0, 7.0))
    p.end()
    return QIcon(pix)


def icon_more(color: str = "#94a3b8", size: int = 16) -> QIcon:
    """水平三点 (更多操作)。"""
    pix, p = _make_pixmap(size)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(4.0, 8.0), 1.2, 1.2)
    p.drawEllipse(QPointF(8.0, 8.0), 1.2, 1.2)
    p.drawEllipse(QPointF(12.0, 8.0), 1.2, 1.2)
    p.end()
    return QIcon(pix)


def icon_drop(color: str = "#94a3b8", size: int = 16) -> QIcon:
    """箭头下落进托盘 (拖拽导入)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # 箭头
    p.drawLine(QPointF(8.0, 2.5), QPointF(8.0, 9.5))
    path = QPainterPath()
    path.moveTo(5.5, 7.5)
    path.lineTo(8.0, 10.0)
    path.lineTo(10.5, 7.5)
    p.drawPath(path)
    # 托盘槽
    tray = QPainterPath()
    tray.moveTo(3.0, 9.0)
    tray.lineTo(3.0, 13.0)
    tray.lineTo(13.0, 13.0)
    tray.lineTo(13.0, 9.0)
    p.drawPath(tray)
    p.end()
    return QIcon(pix)


def icon_expand(color: str = "#94a3b8", size: int = 14) -> QIcon:
    """窗口外折扩展 (展开完整模式)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # 右上箭头
    p.drawLine(QPointF(8.5, 2.5), QPointF(11.5, 2.5))
    p.drawLine(QPointF(11.5, 2.5), QPointF(11.5, 5.5))
    p.drawLine(QPointF(11.5, 2.5), QPointF(7.5, 6.5))
    # 左下箭头
    p.drawLine(QPointF(5.5, 11.5), QPointF(2.5, 11.5))
    p.drawLine(QPointF(2.5, 11.5), QPointF(2.5, 8.5))
    p.drawLine(QPointF(2.5, 11.5), QPointF(6.5, 7.5))
    p.end()
    return QIcon(pix)


def icon_refresh(color: str = "#94a3b8", size: int = 14) -> QIcon:
    """双向回环箭头 (重新解析/刷新)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.arcMoveTo(2.5, 2.5, 11.0, 11.0, 45)
    path.arcTo(2.5, 2.5, 11.0, 11.0, 45, 270)
    p.drawPath(path)
    arrow = QPainterPath()
    arrow.moveTo(10.5, 2.0)
    arrow.lineTo(13.5, 4.5)
    arrow.lineTo(10.5, 7.0)
    p.drawPath(arrow)
    p.end()
    return QIcon(pix)


def icon_collapse(color: str = "#94a3b8", size: int = 14) -> QIcon:
    """窗口折叠收起 (轻量模式)。"""
    pix, p = _make_pixmap(size)
    pen = QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    # 左上内折
    p.drawLine(QPointF(2.5, 6.5), QPointF(6.5, 6.5))
    p.drawLine(QPointF(6.5, 2.5), QPointF(6.5, 6.5))
    p.drawLine(QPointF(6.5, 6.5), QPointF(2.5, 2.5))
    # 右下内折
    p.drawLine(QPointF(11.5, 7.5), QPointF(7.5, 7.5))
    p.drawLine(QPointF(7.5, 11.5), QPointF(7.5, 7.5))
    p.drawLine(QPointF(7.5, 7.5), QPointF(11.5, 11.5))
    p.end()
    return QIcon(pix)
