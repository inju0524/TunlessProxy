"""配置页布局回归测试：确保右侧面板在任意合法宽度与主题下都不出现横向滚动条。

    python tests/check_layout.py

覆盖：
  * 默认窗口尺寸 (840x540)
  * 窗口最小尺寸 (840x480)
  * 左右分栏拖到两个极端
  * 全部 4 套主题下的复检
  * 设置对话框的尺寸与可滚动性
  * 顶部软件名（三段式字标）的三段构成、字重节奏、配色与顶栏适配
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QFontMetrics  # noqa: E402
from PyQt6.QtWidgets import QDialogButtonBox, QScrollArea  # noqa: E402

from tunless.gui.main_window import HEADER_HEIGHT  # noqa: E402
from tunless.gui.title_mark import DOT_CENTER_RATIO, DOT_SIZE  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)
    return ok


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    from tunless import config
    from tunless.app import _apply_style
    from tunless.gui.main_window import MainWindow

    # 这个脚本会切主题、切模式，而它们都会 config.save —— 不拦的话，跑一次自检
    # 就把用户真实的主题偏好改成循环里最后一个（实测会把默认的 aurora 留成 frosted）。
    config.save = lambda *_args, **_kwargs: None

    app = QApplication.instance() or QApplication([])
    _apply_style(app)
    cfg = config.load()
    win = MainWindow(cfg, None)
    win.set_compact_mode(False)
    win.show()
    for _ in range(8):
        app.processEvents()

    # 切到「配置」页
    win.detail.tabs.setCurrentIndex(1)
    for _ in range(8):
        app.processEvents()

    scroll = win.detail.config_scroll

    def probe(label: str) -> None:
        for _ in range(8):
            app.processEvents()
        viewport = scroll.viewport().width()
        need = scroll.widget().minimumSizeHint().width()
        hbar = scroll.horizontalScrollBar().isVisible()
        check(not hbar, f"{label}：无横向滚动条", f"viewport={viewport} need={need}")
        check(need <= viewport, f"{label}：内容宽度未超出视口", f"need={need} <= {viewport}")

    # 1. 默认尺寸
    win.resize(840, 540)
    probe("默认 840x540")

    # 2. 窗口最小尺寸
    win.resize(840, 480)
    probe("最小 840x480")

    # 3. 分栏拖到最左（右侧面板最宽）
    win.splitter.setSizes([220, 10000])
    probe("分栏最左")

    # 4. 分栏拖到最右（右侧面板收到最小宽度 550）
    win.splitter.setSizes([10000, 550])
    probe("分栏最右")

    # 5. 全主题复检
    for tid in ("aurora", "midnight", "pure-crystal", "frosted"):
        win.switch_theme(tid)
        win.splitter.setSizes([10000, 550])
        probe(f"主题 {tid}")

    # 6. 设置对话框：品牌动效卡片不能把按钮挤出屏幕
    #    卡片总高约 785px，768p 笔记本可用高度只有 700 出头 —— 必须靠滚动区兜底。
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QScrollArea

    from tunless import service
    from tunless.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(cfg, service.current_endpoint(cfg), win)
    dialog.show()
    for _ in range(10):
        app.processEvents()

    available = QGuiApplication.primaryScreen().availableGeometry().height()
    check(
        dialog.height() <= available,
        "设置对话框初始高度不超出屏幕（底部按钮可见）",
        f"dialog={dialog.height()} <= screen={available}",
    )
    check(dialog.width() >= 580, "设置对话框宽度足够", f"{dialog.width()}px")

    area = dialog.findChild(QScrollArea)
    check(area is not None, "设置对话框内容可滚动（卡片变高时不会顶掉按钮）")

    dialog.reject()
    for _ in range(4):
        app.processEvents()

    # ---------------------------------------------------------- 顶部软件名
    # 三段式静态字标：Tunless（细体）/ 4px 绿点 / Proxy（粗体冰蓝）。
    mark = win.title_mark
    check(
        mark.label_left.text() == "Tunless" and mark.label_right.text() == "Proxy",
        "字标是三段式（Tunless + 微点 + Proxy）",
        f"{mark.label_left.text()} / {mark.label_right.text()}",
    )
    check(
        mark.dot.width() == DOT_SIZE,
        f"微点宽度是 {DOT_SIZE}px（照参考图比例：点/大写高 ≈ 0.25）",
        f"{mark.dot.width()}x{mark.dot.height()}，间距 {mark.layout().spacing()}px",
    )
    # 点的竖直位置：参考图实测"点中心 = 大写顶 + 0.57 × 大写高"。
    # 直接丢进布局垂直居中会落在 0.46 左右（居中的是行框不是大写高），看着偏上。
    metrics = QFontMetrics(mark.label_left.font())
    cap = metrics.capHeight()
    ratio = (mark.dot.center_y - (metrics.ascent() - cap)) / cap
    check(
        abs(ratio - DOT_CENTER_RATIO) < 0.02,
        f"微点落在大写高的 {DOT_CENTER_RATIO:.0%} 处（参考图实测 0.570）",
        f"实际 {ratio:.3f}（点中心 y={mark.dot.center_y:.1f}，大写高 {cap}）",
    )
    check(
        "transparent" in mark.label_left.styleSheet()
        and "transparent" in mark.label_right.styleSheet(),
        "字标背景完全透明（旧样式的描边/底色已移除）",
        mark.label_left.styleSheet().split(";")[-2].strip(),
    )
    check(
        "border" not in mark.label_left.styleSheet().replace("border: none", "")
        or "glow" not in mark.label_left.styleSheet().lower(),
        "字标不带发光边框样式",
    )
    check(
        mark.height() <= HEADER_HEIGHT - 8,
        "字标高度适配顶栏",
        f"{mark.width()}x{mark.height()} ≤ 顶栏 {HEADER_HEIGHT}",
    )

    # 字重节奏：细体 vs 粗体必须是两个不同的字重
    light_weight = int(mark.label_left.font().weight())
    bold_weight = int(mark.label_right.font().weight())
    check(
        300 <= light_weight < 400 <= bold_weight,
        "字重节奏正确（Tunless 细体 / Proxy 粗体）",
        f"{light_weight} vs {bold_weight}",
    )

    # 颜色随主题：深色一套、浅色一套（浅色主题用同设计的深色版，
    # 否则 #E2E8F0 那种亮灰白在浅底上几乎看不见）
    win.switch_theme("aurora")
    for _ in range(4):
        app.processEvents()
    dark_colors = mark.colors()
    win.switch_theme("pure-crystal")
    for _ in range(4):
        app.processEvents()
    light_colors = mark.colors()
    check(
        dark_colors == ("#E2E8F0", "#10B981", "#7DD3FC"),
        "深色主题用指定配色（#E2E8F0 / #10B981 / #7DD3FC）",
        str(dark_colors),
    )
    check(
        light_colors[0] != dark_colors[0] and light_colors[1] == dark_colors[1],
        "浅色主题换成深色版（微点绿保持一致）",
        f"{light_colors}",
    )
    # Proxy 那一段是横向渐变（照参考图量的：左端近白 → 右端冰蓝）
    win.switch_theme("aurora")
    for _ in range(4):
        app.processEvents()
    dark_gradient = mark.proxy_gradient()
    check(
        dark_gradient == ("#FFFFFF", "#7DD3FC"),
        "深色主题下 Proxy 是白→冰蓝的横向渐变",
        str(dark_gradient),
    )
    win.switch_theme("pure-crystal")
    for _ in range(4):
        app.processEvents()
    light_gradient = mark.proxy_gradient()
    check(
        light_gradient != dark_gradient and light_gradient[0].startswith("#0")
        and light_gradient[1] == "#0284C7",
        "浅色主题下 Proxy 用深色版渐变",
        str(light_gradient),
    )
    check(
        mark.label_right.colors() == light_gradient,
        "渐变端点真的传到了控件上（不是只存在常量里）",
        str(mark.label_right.colors()),
    )
    win.switch_theme("aurora")
    for _ in range(4):
        app.processEvents()

    # ---------------------------------------------------------- 「关于」页
    titles = [action.text() for action in win.menuBar().actions()]
    check(
        "帮助" in titles and "关于" in titles
        and titles.index("帮助") < titles.index("关于")
        and titles.index("关于") == len(titles) - 1,
        "菜单栏里「关于」在「帮助」右边",
        " / ".join(titles),
    )

    from tunless import (
        __author__, __copyright__, __license_label__, __url__, __url_label__, __version__,
    )
    from tunless.gui.about_dialog import AboutDialog

    about = AboutDialog(win)
    check(
        about.version_label.text() == f"v{__version__}" and about.name_label.text() == "TunlessProxy",
        "关于页显示的名称与版本号（版本读的是单一来源）",
        f"{about.name_label.text()} {about.version_label.text()}",
    )
    check(
        about.author_value.text() == __author__,
        "关于页作者署名正确",
        about.author_value.text(),
    )
    check(
        __url__ in about.link_value.text()
        and about.link_value.openExternalLinks()
        and __url_label__ in about.link_value.text(),
        "GitHub 行可点击（且显示的是短地址）",
        about.link_value.text(),
    )
    check(
        about.license_value.text().startswith(__license_label__)
        and __copyright__ in about.license_value.text(),
        "关于页许可与版权行正确",
        about.license_value.text(),
    )
    check(
        about.tagline_label.text() and about.tagline2_label.text(),
        "关于页两句定位都在",
        f"{about.tagline_label.text()} / {about.tagline2_label.text()}",
    )
    check(
        about.findChild(QDialogButtonBox) is not None,
        "关于页有关闭按钮",
        str(len(about.findChildren(QDialogButtonBox))),
    )

    # 点菜单项真的会打开它（把 exec 换掉，免得模态对话框把测试挂住）
    import tunless.gui.about_dialog as about_mod

    opened: list[int] = []

    class _Spy(AboutDialog):
        def exec(self) -> int:  # noqa: A003 - 与 Qt 同名
            opened.append(id(self))
            return 0

    original_dialog = about_mod.AboutDialog
    about_mod.AboutDialog = _Spy
    try:
        win.about_page_action.trigger()
    finally:
        about_mod.AboutDialog = original_dialog
    check(len(opened) == 1, "点菜单栏「关于」会打开关于页", f"打开 {len(opened)} 次")

    win.tray = None
    app.quit()

    print("\n" + "=" * 58)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：")
        for name in FAILURES:
            print("  FAIL ", name)
        return 1
    print("配置页布局回归测试全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
