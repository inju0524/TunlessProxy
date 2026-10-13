"""GUI 健壮性回归。

    python tests/check_gui_robustness.py

覆盖几条"出事就没法看"的问题：
  * 槽里抛未捕获异常 —— PyQt6 会直接 qFatal，进程以 0xC0000409 中止；
  * 设置对话框关掉后没有回收（连开几次就累积几份控件树）；
  * 没有托盘图标时"关窗 = 隐藏"，程序彻底失联；
  * 设置里点一次「确定」就把用户手改过的品牌动效参数清空；
  * 在设置里改「轻量便携模式」后必须立刻生效。

判据必须在**子进程**里跑：要复现的失败模式会把进程直接带走，同进程里测会连
测试自己一起杀掉。子进程统一把 `config.save` 换成桩，绝不碰用户真实配置。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)
    return ok


# ---------------------------------------------------------------- 子进程侧

def _prepare():
    """子进程公共准备：QApplication + 主窗口 + 不写真实配置。"""
    from PyQt6.QtWidgets import QApplication

    from tunless import config
    from tunless.app import _apply_style
    from tunless.gui import main_window as mw
    from tunless.gui.main_window import MainWindow

    config.save = lambda *_args, **_kwargs: None
    # 出错时弹的模态框会把无人值守的子进程挂住 —— 换成记录
    mw.QMessageBox.warning = staticmethod(lambda *a, **k: print("[dialog-warning]", a[2] if len(a) > 2 else ""))
    mw.QMessageBox.information = staticmethod(lambda *a, **k: None)
    mw.QMessageBox.critical = staticmethod(lambda *a, **k: None)
    mw.QMessageBox.question = staticmethod(lambda *a, **k: mw.QMessageBox.StandardButton.No)

    app = QApplication.instance() or QApplication([])
    _apply_style(app)
    cfg = config.load()
    win = MainWindow(cfg, None)
    win.show()
    for _ in range(6):
        app.processEvents()
    return app, cfg, win, mw


def _theme_action(win, index: int = 1):
    for act in win.menuBar().actions():
        menu = act.menu()
        if menu is None or menu.title() != "视图与模式":
            continue
        for sub in menu.actions():
            if sub.menu() is not None and sub.menu().title() == "切换主题":
                return sub.menu().actions()[index]
    raise AssertionError("没有找到「切换主题」菜单")


def _flush(app) -> None:
    """把事件处理干净。

    注意 `deleteLater()` 的 DeferredDelete 事件**不会**被 `processEvents()` 处理
    （Qt 只在事件循环回到最外层时才删），必须显式 sendPostedEvents ——
    否则会误判成"对象没被回收"。
    """
    from PyQt6.QtCore import QEvent

    for _ in range(4):
        app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(4):
        app.processEvents()


def case_slot_exception() -> int:
    """槽里抛异常时，程序必须活着（而不是 abort）。"""
    app, cfg, win, mw = _prepare()

    from tunless import config

    def boom(*_args, **_kwargs):
        raise PermissionError("模拟磁盘/权限故障")

    config.save = boom  # switch_theme 里的 config.save 会抛
    action = _theme_action(win, index=1)
    action.trigger()  # 走 Qt 的 C++ 触发路径：未捕获异常在这里会 abort
    for _ in range(6):
        app.processEvents()
    print("alive")
    return 0


def case_dialog_lifetime() -> int:
    """设置对话框关掉后必须被回收，不能一次一份地累积。"""
    from PyQt6.QtCore import QTimer

    app, cfg, win, mw = _prepare()
    from tunless.gui.settings_dialog import SettingsDialog

    for round_index in range(2):
        QTimer.singleShot(200, lambda: [d.close() for d in win.findChildren(SettingsDialog)])
        win.open_settings()
        _flush(app)
        alive = len(win.findChildren(SettingsDialog))
        print(f"round {round_index}: dialogs={alive}")
    total_dialogs = len(win.findChildren(SettingsDialog))
    total_cards = len(win.findChildren(mw.GlassCard))
    print(f"final dialogs={total_dialogs} glasscards={total_cards}")
    return 0 if total_dialogs == 0 else 1


def case_no_tray_close() -> int:
    """没有托盘时关窗要真的退出，不能变成"消失了但进程还在"。"""
    app, cfg, win, mw = _prepare()
    win.tray = None
    quit_called = {"value": False}
    win.quit_app = lambda: quit_called.__setitem__("value", True)
    win.close()
    for _ in range(4):
        app.processEvents()
    print(f"quit_called={quit_called['value']}")
    return 0 if quit_called["value"] else 1


def case_settings_preserves_unknown_keys() -> int:
    """「确定」不能把配置里别人写的键整段丢掉。

    原来这条是用 `brandMotion` 里界面没暴露的项来验的（动效字标已删除）；
    现在换个更中性的哨兵：直接往 settings 里塞一个界面完全不认识的键，
    保存后它必须还在 —— 这条挡的是"设置对话框整份重写配置"这类回归。
    """
    from tunless.gui.settings_dialog import SettingsDialog
    from tunless.model import ProxyEndpoint

    app, cfg, win, mw = _prepare()
    settings = dict(cfg.get("settings") or {})
    settings["futureKnob"] = {"level": 7}
    settings["futureScalar"] = 42
    cfg["settings"] = settings

    written: dict = {}

    from tunless import config

    config.save = lambda payload: written.update(payload)

    endpoint = ProxyEndpoint(host="127.0.0.1", mixed_port=7897, source="test")
    dialog = SettingsDialog(cfg, endpoint, win)
    dialog.apply_to_config()
    saved = (written.get("settings") or {})
    kept = (saved.get("futureKnob"), saved.get("futureScalar"))
    print(f"kept={kept}")
    return 0 if kept == ({"level": 7}, 42) else 1


def case_compact_applies_immediately() -> int:
    """设置里勾上「轻量便携模式」点确定后，主窗口要立刻切过去。"""
    from PyQt6.QtCore import QTimer

    app, cfg, win, mw = _prepare()
    from tunless.gui.settings_dialog import SettingsDialog

    win.set_compact_mode(False)
    for _ in range(4):
        app.processEvents()
    before = win._compact_mode

    def tweak() -> None:
        for dialog in win.findChildren(SettingsDialog):
            if isinstance(dialog, SettingsDialog):
                dialog.compact_box.setChecked(True)
                dialog.accept()

    QTimer.singleShot(200, tweak)
    win.open_settings()
    _flush(app)
    print(f"before={before} after={win._compact_mode}")
    return 0 if (not before and win._compact_mode) else 1


def case_buttons_no_error_dialog() -> int:
    """按钮/菜单项点下去不许弹"操作未完成"。

    回归点：PyQt 的 `clicked(bool)` / `triggered(bool)` 会带一个 bool 进来，
    而 `open_settings()` 这类槽不收参数 —— 包装器若原样转发就会 TypeError
    （用户看到的就是点「设置」「重新解析」弹一个错误框）。
    """
    from PyQt6.QtCore import QTimer

    app, cfg, win, mw = _prepare()
    from tunless.gui.settings_dialog import SettingsDialog

    warnings: list[str] = []
    mw.QMessageBox.warning = staticmethod(
        lambda *a, **k: warnings.append(str(a[2]) if len(a) > 2 else "")
    )

    # 顶栏「设置」按钮（clicked(bool)）
    QTimer.singleShot(200, lambda: [d.close() for d in win.findChildren(SettingsDialog)])
    win.settings_btn.click()
    _flush(app)

    # 顶栏刷新按钮 → refresh_selected
    win.refresh_btn.click()
    _flush(app)

    # 菜单里的「设置…」（triggered(bool)，和按钮是两条不同的信号路径）
    QTimer.singleShot(200, lambda: [d.close() for d in win.findChildren(SettingsDialog)])
    for act in win.menuBar().actions():
        menu = act.menu()
        if menu is None:
            continue
        for item in menu.actions():
            if item.text().startswith("设置"):
                item.trigger()
    _flush(app)

    print(f"warnings={warnings}")
    return 0 if not warnings else 1


def case_guarded_arity() -> int:
    """包装器必须按原槽签名裁掉信号多带的参数（单元级判据）。"""
    from tunless.gui.main_window import guarded

    class Probe:
        @guarded
        def no_args(self):
            return "no_args"

        @guarded
        def one_arg(self, value):
            return value

        @guarded
        def two_args(self, first, second):
            return (first, second)

    probe = Probe()
    results = {
        "no_args()": probe.no_args(),
        "no_args(False)": probe.no_args(False),
        "no_args(False, 'x')": probe.no_args(False, "x"),
        "one_arg(7)": probe.one_arg(7),
        "one_arg(7, False)": probe.one_arg(7, False),
        "two_args(1, 2)": probe.two_args(1, 2),
    }
    print(f"results={results}")
    ok = (
        results["no_args()"] == "no_args"
        and results["no_args(False)"] == "no_args"
        and results["no_args(False, 'x')"] == "no_args"
        and results["one_arg(7)"] == 7
        and results["one_arg(7, False)"] == 7
        and results["two_args(1, 2)"] == (1, 2)
    )
    return 0 if ok else 1


def case_desktop_shortcut_path() -> int:
    """菜单里的「创建桌面快捷方式」必须走桌面目录（整条 GUI 路径）。

    回归点：菜单文案是"桌面"，代码第一版却写进开始菜单 —— 用户点完在桌面上
    什么也看不到。这里把桌面目录换成临时目录替身，验证的是真实调用链，
    同时不往用户桌面上丢文件。
    """
    import tempfile

    from tunless import service
    from tunless.launch import shortcuts

    app, cfg, win, mw = _prepare()
    target = r"C:\Windows\System32\notepad.exe"
    profile = service.build_profile(target, "桌面快捷方式回归")
    service.save_profile(cfg, profile)  # config.save 已被替换成桩，不落盘

    with tempfile.TemporaryDirectory(prefix="tunless-desk-") as directory:
        shortcuts.desktop_dir = lambda: Path(directory)  # 只替换目录来源
        win.create_shortcut(profile.id)
        created = Path(directory) / shortcuts.shortcut_name(profile)
        print(f"created={created.is_file()} name={created.name} desktop=notepad 目标={target}")
        ok = created.is_file()
    # 开始菜单那份不在这条路径上创建，避免污染真实开始菜单
    return 0 if ok else 1


CASES = {
    "slot-exception": case_slot_exception,
    "dialog-lifetime": case_dialog_lifetime,
    "no-tray-close": case_no_tray_close,
    "brand-motion-preserved": case_settings_preserves_unknown_keys,
    "compact-applies-immediately": case_compact_applies_immediately,
    "buttons-no-error-dialog": case_buttons_no_error_dialog,
    "guarded-arity": case_guarded_arity,
    "desktop-shortcut-path": case_desktop_shortcut_path,
}


# ---------------------------------------------------------------- 父进程侧

def run_case(name: str) -> tuple[int, str]:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--case", name],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def marker(output: str, prefix: str) -> str:
    """从子进程输出里挑出判据那一行（Qt 会往 stderr 打一堆字体/插件噪声）。"""
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.strip()
    return output.strip().splitlines()[-1] if output.strip() else ""


def main() -> int:
    if "--case" in sys.argv:
        name = sys.argv[sys.argv.index("--case") + 1]
        return CASES[name]()

    # 1. 槽异常：子进程必须以 0 退出（未修时会以 0xC0000409 中止）
    code, output = run_case("slot-exception")
    check(
        code == 0 and "alive" in output,
        "槽里抛异常不会带走进程（子进程存活）",
        f"exit={code}" + ("（0xC0000409 = 被 Qt abort）" if code not in (0, 1) else ""),
    )

    code, output = run_case("dialog-lifetime")
    check(code == 0, "设置对话框关闭后被回收（不累积）", marker(output, "final"))

    code, output = run_case("no-tray-close")
    check(code == 0, "没有托盘时关窗会真正退出（不失联）", marker(output, "quit_called"))

    code, output = run_case("brand-motion-preserved")
    check(code == 0, "「确定」不会丢掉配置里界面不认识的键", marker(output, "kept="))

    code, output = run_case("compact-applies-immediately")
    check(code == 0, "设置里的「轻量便携模式」点确定后立刻生效", marker(output, "before="))

    code, output = run_case("guarded-arity")
    check(code == 0, "包装器按槽签名裁掉信号多带的参数（单元级）", marker(output, "results="))

    code, output = run_case("desktop-shortcut-path")
    check(
        code == 0 and "created=True" in output,
        "「创建桌面快捷方式」整条 GUI 路径落在桌面目录",
        marker(output, "created="),
    )

    code, output = run_case("buttons-no-error-dialog")
    check(
        code == 0 and "warnings=[]" in output,
        "点「设置」「重新解析」等按钮不弹错误框（信号路径端到端）",
        marker(output, "warnings="),
    )

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"GUI 健壮性回归：{len(FAILURES)} 项未通过")
        for name in FAILURES:
            print(f"  FAIL  {name}")
        return 1
    print("GUI 健壮性回归：全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
