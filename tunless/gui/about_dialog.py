"""「关于」页。

刻意做得很小：只回答"这是什么、谁写的、怎么联系、什么许可"四件事。
版本号、作者、链接、许可全部从 `tunless/__init__.py` 读（单一来源），所以
升级版本或改署名时不需要动这个文件，页面也不会出现"写着 0.1.9 其实是 0.1.10"。

配色跟着当前主题走（4 套主题都验过），字体层级与设置对话框一致。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout,
)

from .. import (
    APP_NAME, __author__, __copyright__, __license_label__, __tagline__, __tagline2__,
    __url__, __url_label__, __version__,
)
from . import theme_tokens as tok
from .widgets import app_icon

#: 图标边长（像素）
ICON_PX = 48


class AboutDialog(QDialog):
    """关于页：图标 + 名称版本 + 两句定位 + 作者/链接/许可。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        root.addLayout(self._build_header())
        root.addWidget(self._rule())
        root.addLayout(self._build_facts())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        root.addWidget(buttons)

    # ------------------------------------------------------------ 各段

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(ICON_PX, ICON_PX))
        icon.setFixedSize(ICON_PX, ICON_PX)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)

        self.name_label = QLabel(APP_NAME)
        self.name_label.setStyleSheet(
            f"font-size: 19px; font-weight: 600; color: {tok.TEXT_PRIMARY};"
        )
        text.addWidget(self.name_label)

        # 版本号从 tunless.__version__ 来 —— 与 --version、打包产物同一份
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setStyleSheet(
            f"font-size: 12px; color: {tok.TEXT_SECONDARY};"
        )
        text.addWidget(self.version_label)

        text.addSpacing(6)

        self.tagline_label = QLabel(__tagline__)
        self.tagline_label.setWordWrap(True)
        self.tagline_label.setStyleSheet(f"font-size: 13px; color: {tok.TEXT_PRIMARY};")
        text.addWidget(self.tagline_label)

        self.tagline2_label = QLabel(__tagline2__)
        self.tagline2_label.setWordWrap(True)
        self.tagline2_label.setStyleSheet(f"font-size: 13px; color: {tok.TEXT_SECONDARY};")
        text.addWidget(self.tagline2_label)

        row.addLayout(text, 1)
        return row

    def _rule(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {tok.BORDER_SUBTLE}; border: none;")
        return line

    def _build_facts(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.author_value = self._value(__author__)
        self.link_value = self._value(
            f'<a href="{__url__}" style="color: {tok.BRAND_PRIMARY};'
            f' text-decoration: none;">{__url_label__}</a>',
            rich=True,
        )
        self.license_value = self._value(f"{__license_label__} · {__copyright__}")

        for row, (caption, widget) in enumerate(
            (
                ("作者", self.author_value),
                ("GitHub", self.link_value),
                ("许可", self.license_value),
            )
        ):
            label = QLabel(caption)
            label.setStyleSheet(f"font-size: 12px; color: {tok.TEXT_SECONDARY};")
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
        return grid

    def _value(self, text: str, rich: bool = False) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tok.TEXT_PRIMARY};")
        label.setWordWrap(True)
        # 只对链接那一行开放富文本与外部跳转：其余文字保持纯文本，
        # 免得以后把署名里的 < > 之类字符当成标记吃掉。
        label.setTextFormat(
            Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText
        )
        if rich:
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextBrowserInteraction
            )
            label.setToolTip(__url__)
        return label
