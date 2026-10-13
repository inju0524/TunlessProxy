"""GUI 引导：QApplication、单实例、托盘、异常兜底。"""

from __future__ import annotations

import os
import sys
import traceback

from . import APP_NAME, config

SINGLE_INSTANCE_KEY = "TunlessProxy.SingleInstance.v1"


def _make_app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    return app


def _apply_style(app, cfg: dict | None = None) -> None:
    from PyQt6.QtGui import QFont
    from .gui import theme_tokens

    app.setFont(QFont("Microsoft YaHei UI", 9))
    theme_id = theme_tokens.DEFAULT_THEME_ID
    if cfg is not None:
        theme_id = cfg.get("settings", {}).get("theme", theme_tokens.DEFAULT_THEME_ID)
    theme_tokens.set_current_theme(theme_id)
    app.setStyleSheet(theme_tokens.generate_qss())


def notify_running_instance(message: str) -> bool:
    """尽力而为地通知已在运行的 GUI（没运行就静默失败）。"""
    try:
        from PyQt6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if not socket.waitForConnected(300):
        return False
    try:
        socket.write(message.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(300)
    finally:
        socket.disconnectFromServer()
    return True


def _take_single_instance():
    """返回 (是否拿到, server)。拿不到说明已有实例在跑。"""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket

    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(200):
        probe.disconnectFromServer()
        return False, None

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    if not server.listen(SINGLE_INSTANCE_KEY):
        return False, None
    return True, server


def run_gui(cfg: dict | None = None) -> int:
    try:
        app = _make_app()
    except ImportError as exc:
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        print("请先安装 PyQt6：pip install PyQt6", file=sys.stderr)
        return 1

    active_cfg = cfg if cfg is not None else config.load()
    _apply_style(app, active_cfg)

    acquired, server = _take_single_instance()
    if not acquired:
        notify_running_instance("show")
        print("TunlessProxy 已经在运行，已唤出已有窗口。")
        return 0

    from .gui.main_window import MainWindow

    removed = run_startup_maintenance(active_cfg)
    window = MainWindow(active_cfg, server)
    window.show()
    if removed:
        window.status(f"已清理 {removed} 项无主数据")
    return app.exec()


def run_startup_maintenance(cfg: dict) -> int:
    """启动时清一次孤儿数据（profiles/<id>/ 与图标）。

    这些是 build_plan 顺手创建的，profile 没被保存时就会永远留着。
    """
    try:
        from . import service

        return service.prune_profile_dirs(cfg)
    except Exception:  # noqa: BLE001 - 清理失败绝不能影响启动
        return 0


def excepthook(exc_type, exc_value, exc_tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        path = config.log_path("crash.log")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = excepthook
