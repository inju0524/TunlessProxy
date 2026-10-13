"""给 README 生成界面截图（真实字体）。

    python tests/capture_docs.py

`gui_smoke.py` 跑在 offscreen 平台上，字体渲染成方框，只适合看布局；README 首图
得用真实平台。另外品牌字标有一个入场动画（`appear` 由 0 渐显），必须让事件循环
真的跑一会儿再截，否则字标是空白的 —— 第一版截图就是这样漏掉了字标。

截出来的图放在 docs/：
  screenshot-main.png      完整模式（默认主题 极光幻彩）
  screenshot-compact.png   轻量便携模式
  screenshot-settings.png  设置对话框
  screenshot-about.png     「关于」页
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "windows"  # 必须是真实平台，offscreen 没有字体

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOCS = ROOT / "docs"


def pump(app, seconds: float) -> None:
    """让事件循环真的跑一段时间（定时器/动画才会推进）。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    from tunless import config
    from tunless.app import _apply_style
    from tunless.gui import theme_tokens as tok
    from tunless.gui.main_window import MainWindow
    from tunless.gui.settings_dialog import SettingsDialog

    config.save = lambda *_args, **_kwargs: None  # 别把用户的主题偏好写坏
    DOCS.mkdir(exist_ok=True)

    app = QApplication.instance() or QApplication([])
    cfg = config.load()
    _apply_style(app, cfg)

    window = MainWindow(cfg, None)
    window.switch_theme(tok.DEFAULT_THEME_ID)
    window.set_compact_mode(False)
    window.resize(840, 540)
    window.show()
    pump(app, 2.0)  # 等字标入场动画走完

    if cfg.get("profiles"):
        window.select_by_id(cfg["profiles"][0]["id"])
        pump(app, 0.6)

    window._announce_endpoint()
    pump(app, 0.8)
    main_shot = DOCS / "screenshot-main.png"
    window.grab().save(str(main_shot), "PNG")
    print(f"main     -> {main_shot}  ({window.width()}x{window.height()})")

    window.set_compact_mode(True)
    pump(app, 1.0)
    compact_shot = DOCS / "screenshot-compact.png"
    window.grab().save(str(compact_shot), "PNG")
    print(f"compact  -> {compact_shot}  ({window.width()}x{window.height()})")

    window.set_compact_mode(False)
    pump(app, 0.8)

    from tunless import service

    dialog = SettingsDialog(cfg, service.current_endpoint(cfg), window)
    dialog.show()
    pump(app, 1.0)
    settings_shot = DOCS / "screenshot-settings.png"
    dialog.grab().save(str(settings_shot), "PNG")
    print(f"settings -> {settings_shot}  ({dialog.width()}x{dialog.height()})")
    dialog.close()

    from tunless.gui.about_dialog import AboutDialog

    about = AboutDialog(window)
    about.show()
    pump(app, 0.8)
    about_shot = DOCS / "screenshot-about.png"
    about.grab().save(str(about_shot), "PNG")
    print(f"about    -> {about_shot}  ({about.width()}x{about.height()})")
    about.close()

    window.tray = None
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
