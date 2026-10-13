"""设计系统令牌与多主题管理器 (Design Tokens & Theme Manager)

依据 Apple、Linear、Raycast 现代专业桌面软件设计语言优化：
- 沉静纯正的冷微晶与曜石黑材质体系，大幅降低非必要的紫色噪音
- 高级克制的品牌高光点缀 (Raycast / Linear 质感)
- 清晰的字阶对比度与平整的单层空间利用率
"""

from __future__ import annotations

from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor


def parse_color(val: str | QColor) -> QColor:
    """健壮的色彩解析函数：解决 Qt QColor 无法解析 CSS 浮点数 rgba 的问题。"""
    if isinstance(val, QColor):
        return QColor(val)
    if not isinstance(val, str):
        return QColor("#ffffff")
    val_str = val.strip()
    if val_str.startswith("rgba(") and val_str.endswith(")"):
        parts = val_str[5:-1].split(",")
        if len(parts) == 4:
            try:
                r = int(parts[0].strip())
                g = int(parts[1].strip())
                b = int(parts[2].strip())
                a_float = float(parts[3].strip())
                a = int(a_float * 255) if a_float <= 1.0 else int(a_float)
                return QColor(r, g, b, max(0, min(255, a)))
            except ValueError:
                pass
    elif val_str.startswith("rgb(") and val_str.endswith(")"):
        parts = val_str[4:-1].split(",")
        if len(parts) == 3:
            try:
                return QColor(int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip()))
            except ValueError:
                pass
    c = QColor(val_str)
    return c if c.isValid() else QColor("#ffffff")


@dataclass
class ThemeColors:
    id: str
    name: str
    is_dark: bool
    bg_window: str
    bg_surface: str
    bg_card: str
    bg_card_hover: str
    bg_input: str
    border_subtle: str
    border_default: str
    border_hover: str
    border_focus: str
    scrollbar_handle: str
    scrollbar_handle_hover: str
    badge_neutral_bg: str
    badge_neutral_border: str
    brand_primary: str
    brand_gradient_start: str
    brand_gradient_end: str
    brand_pressed: str
    brand_light_bg: str
    text_primary: str
    text_secondary: str
    text_muted: str
    success: str
    success_bg: str
    success_border: str
    warning: str
    warning_bg: str
    warning_border: str
    danger: str
    danger_bg: str
    danger_border: str


THEMES: dict[str, ThemeColors] = {
    "midnight": ThemeColors(
        id="midnight",
        name="深空曜石",
        is_dark=True,
        bg_window="#090c15",          # 深邃纯粹的太空曜石底色
        bg_surface="#0e1320",         # 顶栏与基座表面
        bg_card="#111625",            # 单层微晶卡片面板
        bg_card_hover="#182035",      # 悬停轻微提亮
        bg_input="#0b0f1a",           # 沉降输入底色
        border_subtle="rgba(255, 255, 255, 0.07)",
        border_default="rgba(255, 255, 255, 0.12)",
        border_hover="rgba(255, 255, 255, 0.22)",
        border_focus="#5b73fa",
        scrollbar_handle="rgba(148, 163, 184, 0.28)",
        scrollbar_handle_hover="rgba(148, 163, 184, 0.52)",
        badge_neutral_bg="rgba(148, 163, 184, 0.16)",
        badge_neutral_border="rgba(148, 163, 184, 0.30)",
        brand_primary="#5b73fa",      # Linear / Raycast 沉静量子冷湛蓝，微带紫调
        brand_gradient_start="#5b73fa",
        brand_gradient_end="#3f51d6",
        brand_pressed="#3443b8",
        brand_light_bg="rgba(91, 115, 250, 0.15)",
        text_primary="#f8fafc",       # 纯净亮白
        text_secondary="#94a3b8",     # Slate 400 清晰冷灰
        text_muted="#64748b",         # Slate 500
        success="#10b981",
        success_bg="rgba(16, 185, 129, 0.14)",
        success_border="rgba(16, 185, 129, 0.35)",
        warning="#f59e0b",
        warning_bg="rgba(245, 158, 11, 0.14)",
        warning_border="rgba(245, 158, 11, 0.35)",
        danger="#f43f5e",
        danger_bg="rgba(244, 63, 94, 0.14)",
        danger_border="rgba(244, 63, 94, 0.35)",
    ),
    "pure-crystal": ThemeColors(
        id="pure-crystal",
        name="超白水晶",
        is_dark=False,
        bg_window="#f1f5f9",
        bg_surface="#e2e8f0",
        bg_card="#ffffff",
        bg_card_hover="#f8fafc",
        bg_input="#ffffff",
        border_subtle="rgba(15, 23, 42, 0.08)",
        border_default="rgba(15, 23, 42, 0.14)",
        border_hover="rgba(15, 23, 42, 0.28)",
        border_focus="#2563eb",
        scrollbar_handle="rgba(15, 23, 42, 0.20)",
        scrollbar_handle_hover="rgba(15, 23, 42, 0.38)",
        badge_neutral_bg="rgba(100, 116, 139, 0.11)",
        badge_neutral_border="rgba(100, 116, 139, 0.24)",
        brand_primary="#2563eb",
        brand_gradient_start="#3b82f6",
        brand_gradient_end="#1d4ed8",
        brand_pressed="#1e40af",
        brand_light_bg="rgba(37, 99, 235, 0.12)",
        text_primary="#0f172a",
        text_secondary="#334155",
        text_muted="#64748b",
        success="#059669",
        success_bg="rgba(5, 150, 105, 0.12)",
        success_border="rgba(5, 150, 105, 0.35)",
        warning="#d97706",
        warning_bg="rgba(217, 119, 6, 0.12)",
        warning_border="rgba(217, 119, 6, 0.35)",
        danger="#e11d48",
        danger_bg="rgba(225, 29, 72, 0.12)",
        danger_border="rgba(225, 29, 72, 0.35)",
    ),
    "aurora": ThemeColors(
        id="aurora",
        name="极光幻彩",
        is_dark=True,
        bg_window="#0b0814",
        bg_surface="#130e22",
        bg_card="#18112c",
        bg_card_hover="#241942",
        bg_input="#0e0a1c",
        border_subtle="rgba(216, 180, 254, 0.12)",
        border_default="rgba(216, 180, 254, 0.18)",
        border_hover="rgba(216, 180, 254, 0.32)",
        border_focus="#a855f7",
        scrollbar_handle="rgba(216, 180, 254, 0.26)",
        scrollbar_handle_hover="rgba(216, 180, 254, 0.50)",
        badge_neutral_bg="rgba(216, 180, 254, 0.15)",
        badge_neutral_border="rgba(216, 180, 254, 0.28)",
        brand_primary="#a855f7",
        brand_gradient_start="#c084fc",
        brand_gradient_end="#9333ea",
        brand_pressed="#7e22ce",
        brand_light_bg="rgba(168, 85, 247, 0.18)",
        text_primary="#faf5ff",
        text_secondary="#d8b4fe",
        text_muted="#a855f7",
        success="#10b981",
        success_bg="rgba(16, 185, 129, 0.16)",
        success_border="rgba(16, 185, 129, 0.40)",
        warning="#fbbf24",
        warning_bg="rgba(251, 191, 36, 0.16)",
        warning_border="rgba(251, 191, 36, 0.40)",
        danger="#f43f5e",
        danger_bg="rgba(244, 63, 94, 0.16)",
        danger_border="rgba(244, 63, 94, 0.40)",
    ),
    "frosted": ThemeColors(
        id="frosted",
        name="微晶雾面",
        is_dark=True,
        bg_window="#10141b",
        bg_surface="#161b24",
        bg_card="#1b222f",
        bg_card_hover="#242e40",
        bg_input="#121720",
        border_subtle="rgba(255, 255, 255, 0.08)",
        border_default="rgba(255, 255, 255, 0.15)",
        border_hover="rgba(255, 255, 255, 0.28)",
        border_focus="#38bdf8",
        scrollbar_handle="rgba(148, 163, 184, 0.30)",
        scrollbar_handle_hover="rgba(56, 189, 248, 0.52)",
        badge_neutral_bg="rgba(148, 163, 184, 0.16)",
        badge_neutral_border="rgba(148, 163, 184, 0.30)",
        brand_primary="#38bdf8",
        brand_gradient_start="#38bdf8",
        brand_gradient_end="#0284c7",
        brand_pressed="#0369a1",
        brand_light_bg="rgba(56, 189, 248, 0.16)",
        text_primary="#f8fafc",
        text_secondary="#94a3b8",
        text_muted="#64748b",
        success="#10b981",
        success_bg="rgba(16, 185, 129, 0.15)",
        success_border="rgba(16, 185, 129, 0.40)",
        warning="#f59e0b",
        warning_bg="rgba(245, 158, 11, 0.15)",
        warning_border="rgba(245, 158, 11, 0.40)",
        danger="#f43f5e",
        danger_bg="rgba(244, 63, 94, 0.15)",
        danger_border="rgba(244, 63, 94, 0.40)",
    ),
}

#: 默认主题。这个字符串以前散落在 app/main_window/settings_dialog 里各写一份，
#: 改一处就会漂移，现在只有这里一份。
DEFAULT_THEME_ID = "aurora"

_CURRENT_THEME_ID = DEFAULT_THEME_ID


class ThemeManager(QObject):
    themeChanged = pyqtSignal(object)


theme_mgr = ThemeManager()


def get_current_theme() -> ThemeColors:
    return THEMES.get(_CURRENT_THEME_ID, THEMES[DEFAULT_THEME_ID])


def set_current_theme(theme_id: str) -> ThemeColors:
    global _CURRENT_THEME_ID
    if theme_id in THEMES:
        _CURRENT_THEME_ID = theme_id
    t = get_current_theme()
    _sync_globals(t)
    theme_mgr.themeChanged.emit(t)
    return t


def generate_qss(theme: ThemeColors | None = None) -> str:
    t = theme or get_current_theme()
    return f"""
QMainWindow, QDialog {{
    background-color: {t.bg_window};
    color: {t.text_primary};
}}

QWidget {{
    color: {t.text_primary};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", sans-serif;
}}

QLabel {{
    color: {t.text_primary};
    background: transparent;
}}

QLabel#Title {{
    font-size: 14.5px;
    font-weight: 700;
    color: {t.text_primary};
    letter-spacing: -0.01em;
}}

QLabel#SectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {t.text_primary};
    letter-spacing: -0.01em;
    padding-left: 6px;
}}

QLabel#CardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {t.text_primary};
}}

QLabel#CardSubtitle {{
    font-size: 11.5px;
    font-weight: 500;
    color: {t.text_secondary};
}}

QLabel#AppNameLabel {{
    font-size: 18px;
    font-weight: 700;
    color: {t.text_primary};
    letter-spacing: -0.01em;
}}

QLabel#MetricValue {{
    font-size: 16px;
    font-weight: 700;
    color: {t.text_primary};
}}

QLabel#MetricLabel {{
    font-size: 11px;
    font-weight: 500;
    color: {t.text_muted};
}}

QLabel#Subtitle {{
    color: {t.text_secondary};
    font-size: 12px;
}}

QLabel#Hint {{
    color: {t.text_muted};
    font-size: 11px;
    line-height: 1.4;
}}

QFrame#Header {{
    background: {t.bg_surface};
    border-bottom: 1px solid {t.border_subtle};
}}

QFrame#Card, QFrame#GlassCard {{
    background: {t.bg_card};
    border: 1px solid {t.border_subtle};
    border-radius: 12px;
}}

QFrame#StatCard {{
    background: {t.bg_input};
    border: 1px solid {t.border_subtle};
    border-radius: 10px;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QListWidget#ProfileList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}

QListWidget#ProfileList::item {{
    background: {t.border_subtle};
    border: 1px solid {t.border_subtle};
    border-radius: 10px;
    padding: 6px 8px;
    margin-bottom: 4px;
    color: {t.text_primary};
}}

QListWidget#ProfileList::item:hover {{
    background: {t.bg_card_hover};
    border-color: {t.border_hover};
}}

QListWidget#ProfileList::item:selected {{
    background: {t.brand_light_bg};
    border: 1.5px solid {t.brand_primary};
    color: {t.text_primary};
}}

QPushButton {{
    background: {t.border_subtle};
    border: 1px solid {t.border_default};
    border-radius: 8px;
    padding: 6px 14px;
    color: {t.text_primary};
    font-size: 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    background: {t.border_hover};
    border-color: {t.border_hover};
}}

QPushButton:pressed {{
    background: {t.border_subtle};
}}

QPushButton:disabled {{
    color: {t.text_muted};
    background: transparent;
    border-color: {t.border_subtle};
}}

QPushButton::menu-indicator {{
    image: none;
    width: 0px;
}}

QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.brand_gradient_start}, stop:1 {t.brand_gradient_end});
    border: 1px solid rgba(255, 255, 255, 0.25);
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#Primary:hover {{
    background: {t.brand_gradient_start};
    border-color: rgba(255, 255, 255, 0.45);
}}

QPushButton#Primary:pressed {{
    background: {t.brand_pressed};
}}

QPushButton#Danger {{
    background: {t.danger_bg};
    border: 1px solid {t.danger_border};
    color: {t.danger};
}}

QPushButton#Danger:hover {{
    background: {t.danger}25;
    border-color: {t.danger};
}}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background: {t.bg_input};
    border: 1px solid {t.border_default};
    border-radius: 8px;
    padding: 6px 10px;
    color: {t.text_primary};
    font-size: 12px;
    selection-background-color: {t.brand_primary};
    selection-color: #ffffff;
}}

QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover {{
    border-color: {t.border_hover};
    background: {t.bg_input};
}}

QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {t.brand_primary};
    background: {t.bg_input};
}}

QLineEdit:disabled, QPlainTextEdit:disabled {{
    background: {t.border_subtle};
    color: {t.text_muted};
    border-color: {t.border_subtle};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 0px;
}}

QComboBox QAbstractItemView {{
    background: {t.bg_card};
    border: 1px solid {t.border_default};
    border-radius: 8px;
    color: {t.text_primary};
    selection-background-color: {t.brand_light_bg};
    selection-color: {t.text_primary};
    padding: 4px;
    outline: none;
}}

QSpinBox {{
    padding-right: 22px;
}}

QGroupBox {{
    border: 1px solid {t.border_subtle};
    border-radius: 12px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    background: {t.bg_card};
    font-weight: 600;
    font-size: 12px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {t.text_secondary};
    background: transparent;
}}

QCheckBox {{
    color: {t.text_primary};
    spacing: 8px;
    font-size: 12px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {t.border_default};
    background: {t.bg_input};
}}

QCheckBox::indicator:hover {{
    border-color: {t.brand_primary};
}}

QCheckBox::indicator:checked {{
    background: {t.brand_primary};
    border-color: {t.brand_primary};
}}

QTableWidget {{
    background: {t.bg_input};
    border: 1px solid {t.border_subtle};
    border-radius: 10px;
    gridline-color: transparent;
    color: {t.text_primary};
    outline: none;
}}

QHeaderView::section {{
    background: {t.bg_card};
    border: none;
    border-bottom: 1px solid {t.border_subtle};
    padding: 6px 10px;
    color: {t.text_secondary};
    font-size: 11.5px;
    font-weight: 600;
}}

QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {t.border_subtle};
}}

QTableWidget::item:selected {{
    background: {t.brand_light_bg};
    color: {t.text_primary};
}}

QLabel#BannerOk {{
    background: {t.success_bg};
    color: {t.success};
    border: 1px solid {t.success_border};
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 500;
}}

QLabel#BannerWarn {{
    background: {t.warning_bg};
    color: {t.warning};
    border: 1px solid {t.warning_border};
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 500;
}}

QLabel#BannerIdle {{
    background: {t.border_subtle};
    color: {t.text_secondary};
    border: 1px solid {t.border_default};
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 500;
}}

/* ------------------------------------------------------------------
   滚动条：纵向 + 横向 全覆盖，去除原生箭头，色彩严格贴合当前主题
   ------------------------------------------------------------------ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: {t.scrollbar_handle};
    min-height: 32px;
    border-radius: 5px;
    margin: 2px 2px 2px 3px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t.scrollbar_handle_hover};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
    border: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: {t.scrollbar_handle};
    min-width: 32px;
    border-radius: 5px;
    margin: 3px 2px 2px 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {t.scrollbar_handle_hover};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    background: none;
    border: none;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

QAbstractScrollArea::corner {{
    background: transparent;
    border: none;
}}

QStatusBar {{
    background: {t.bg_surface};
    color: {t.text_muted};
    border-top: 1px solid {t.border_subtle};
    font-size: 11px;
}}

QSplitter::handle {{
    background: transparent;
    width: 8px;
}}

QMenuBar {{
    background: {t.bg_surface};
    color: {t.text_secondary};
    border-bottom: 1px solid {t.border_subtle};
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background: {t.border_subtle};
    color: {t.text_primary};
}}

QMenu {{
    background: {t.bg_card};
    color: {t.text_primary};
    border: 1px solid {t.border_default};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 18px 6px 24px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background: {t.brand_light_bg};
    color: {t.text_primary};
}}

QMenu::separator {{
    height: 1px;
    background: {t.border_subtle};
    margin: 4px 6px;
}}
"""


def _sync_globals(t: ThemeColors) -> None:
    global BG_WINDOW, BG_SURFACE, BG_CARD, BG_CARD_HOVER, BG_INPUT
    global BORDER_SUBTLE, BORDER_DEFAULT, BORDER_HOVER
    global BRAND_PRIMARY, BRAND_GRADIENT_START, BRAND_GRADIENT_END, BRAND_PRESSED
    global TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
    global SUCCESS, WARNING, DANGER
    global SUCCESS_BG, SUCCESS_BORDER, WARNING_BG, WARNING_BORDER, DANGER_BG, DANGER_BORDER
    global BRAND_LIGHT_BG, BORDER_PRIMARY_GLOW

    BG_WINDOW = t.bg_window
    BG_SURFACE = t.bg_surface
    BG_CARD = t.bg_card
    BG_CARD_HOVER = t.bg_card_hover
    BG_INPUT = t.bg_input
    BORDER_SUBTLE = t.border_subtle
    BORDER_DEFAULT = t.border_default
    BORDER_HOVER = t.border_hover
    BRAND_PRIMARY = t.brand_primary
    BRAND_GRADIENT_START = t.brand_gradient_start
    BRAND_GRADIENT_END = t.brand_gradient_end
    BRAND_PRESSED = t.brand_pressed
    TEXT_PRIMARY = t.text_primary
    TEXT_SECONDARY = t.text_secondary
    TEXT_MUTED = t.text_muted
    SUCCESS = t.success
    WARNING = t.warning
    DANGER = t.danger
    SUCCESS_BG = t.success_bg
    SUCCESS_BORDER = t.success_border
    WARNING_BG = t.warning_bg
    WARNING_BORDER = t.warning_border
    DANGER_BG = t.danger_bg
    DANGER_BORDER = t.danger_border
    BRAND_LIGHT_BG = t.brand_light_bg
    BORDER_PRIMARY_GLOW = t.border_focus

_sync_globals(THEMES["aurora"])

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 18
RADIUS_FULL = 999
FONT_FAMILY = '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", sans-serif'
FONT_MONO = '"SF Mono", Consolas, "Cascadia Code", monospace'
