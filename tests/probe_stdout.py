"""探针：报告自己被启动时 stdout 是否是可用的控制台句柄。

用来回答一个关键问题：**窗口化的父进程（打包后的 TunlessProxy.exe）
用 CREATE_NEW_CONSOLE 拉起命令行子进程时，子进程还能不能正常输出？**
如果句柄是空的，用户就会看到"新开了黑框但里面什么都没有"。

结果写到环境变量 PROBE_OUT 指向的文件（默认 ./probe_stdout.json）。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys

STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12


def main() -> int:
    kernel32 = ctypes.windll.kernel32
    out_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    err_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)

    info = {
        "sys_stdout_is_none": sys.stdout is None,
        "sys_stderr_is_none": sys.stderr is None,
        "stdout_handle": out_handle,
        "stdout_handle_valid": out_handle not in (0, None, -1),
        "stderr_handle_valid": err_handle not in (0, None, -1),
        "stdout_isatty": (sys.stdout.isatty() if sys.stdout else None),
        "getconsolewindow": kernel32.GetConsoleWindow(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }

    # 再实测一次真正写 stdout 会不会炸
    try:
        print("probe: hello from child")
        sys.stdout.flush()
        info["write_ok"] = True
    except Exception as exc:  # noqa: BLE001
        info["write_ok"] = False
        info["write_error"] = f"{type(exc).__name__}: {exc}"

    target = os.environ.get("PROBE_OUT") or "probe_stdout.json"
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(info, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
