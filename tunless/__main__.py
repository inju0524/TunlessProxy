"""python -m tunless 的入口。"""

from __future__ import annotations

import sys


class _NullWriter:
    """pythonw.exe（无控制台）下 sys.stdout/stderr 是 None，print 会炸。

    快捷方式用的就是 pythonw，所以这里兜一个空写入器，保证 --run 静默可用。
    """

    encoding = "utf-8"

    def write(self, *_args) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def reconfigure(self, **_kwargs) -> None:
        return None


def _force_utf8() -> None:
    """让**我们自己的**输出不乱码 —— 注意不能污染子进程环境。

    早先这里写了 `os.environ.setdefault("PYTHONUTF8", "1")`，那是错的：
    本进程的环境会被 `CreateProcess` 原样传给用户启动的每个应用，
    等于偷偷把别人拉进 UTF-8 模式（会改变 Python 类应用的默认编码行为）。

    正确做法只动自己的流：
      * 真控制台：Python 3.6+ 已经用 WriteConsoleW 走 Unicode，保持默认即可；
      * 重定向/管道：统一改成 UTF-8，避免"控制台 CP 是 65001、Python 却按
        ANSI(936) 写字节"这种两边不一致导致的乱码。
    """
    if sys.stdout is None:
        sys.stdout = _NullWriter()
    if sys.stderr is None:
        sys.stderr = _NullWriter()

    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _force_utf8()
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
