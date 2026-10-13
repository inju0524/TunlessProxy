"""GUI 冒烟测试：在 offscreen 平台下把全新精修的 840x540 控制中心与轻量模式渲染出来并截图。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "gui_smoke.png"

    from PyQt6.QtWidgets import QApplication

    from tunless import config, service
    from tunless.app import _apply_style
    from tunless.gui import theme_tokens as tok
    from tunless.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    _apply_style(app)
    cfg = config.load()
    # 截图会切主题/切模式，别把用户的偏好写坏（见 check_layout.py 的同类拦截）
    config.save = lambda *_args, **_kwargs: None
    window = MainWindow(cfg, None)
    window.set_compact_mode(False)
    window.switch_theme("aurora")
    window.resize(840, 540)
    window.show()

    for _ in range(10):
        app.processEvents()

    window._announce_endpoint()
    for _ in range(8):
        app.processEvents()

    profiles = len(cfg.get("profiles") or [])
    if profiles:
        window.select_by_id(cfg["profiles"][0]["id"])
        for _ in range(8):
            app.processEvents()
        detail_out = out.with_name(out.stem + "_detail.png")
        window.grab().save(str(detail_out), "PNG")
        print(f"detail screenshot -> {detail_out} ({window.width()}x{window.height()})")

        # 配置页截图（验证无横向滚动条 + 滚动条主题化样式）
        window.detail.tabs.setCurrentIndex(1)
        for _ in range(12):
            app.processEvents()
        config_out = out.with_name(out.stem + "_config.png")
        window.grab().save(str(config_out), "PNG")
        print(f"config screenshot -> {config_out}")
        window.detail.tabs.setCurrentIndex(0)
        for _ in range(6):
            app.processEvents()

        # 1. 截取极致紧凑的轻量模式 (340x385 Mini Launcher)
        window.set_compact_mode(True)
        for _ in range(12):
            app.processEvents()
        compact_out = out.with_name(out.stem + "_compact.png")
        window.grab().save(str(compact_out), "PNG")
        print(f"compact mini screenshot -> {compact_out} ({window.width()}x{window.height()})")

        # 2. 切换回完整模式 (840x540)，测试浅色超白水晶
        window.set_compact_mode(False)
        window.switch_theme("pure-crystal")
        for _ in range(10):
            app.processEvents()
        pure_out = out.with_name(out.stem + "_pure_crystal.png")
        window.grab().save(str(pure_out), "PNG")
        print(f"pure crystal screenshot -> {pure_out} ({window.width()}x{window.height()})")

        # 3. 测试极光幻彩
        window.switch_theme("aurora")
        for _ in range(8):
            app.processEvents()
        aurora_out = out.with_name(out.stem + "_aurora.png")
        window.grab().save(str(aurora_out), "PNG")
        print(f"aurora screenshot -> {aurora_out}")

        # 4. 测试微晶雾面
        window.switch_theme("frosted")
        for _ in range(8):
            app.processEvents()
        frosted_out = out.with_name(out.stem + "_frosted.png")
        window.grab().save(str(frosted_out), "PNG")
        print(f"frosted screenshot -> {frosted_out}")

        # 切回默认深空曜石
        window.switch_theme("aurora")
        for _ in range(8):
            app.processEvents()

    # 设置对话框单独截一张
    from tunless.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(cfg, service.current_endpoint(cfg), window)
    # 不强制尺寸：让对话框自己按可用屏幕决定初始大小，截出来的才是用户看到的
    dialog.show()
    for _ in range(10):
        app.processEvents()
    settings_out = out.with_name(out.stem + "_settings.png")
    dialog.grab().save(str(settings_out), "PNG")
    print(f"settings screenshot -> {settings_out} ({dialog.width()}x{dialog.height()})")
    dialog.close()

    window.tray = None
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
