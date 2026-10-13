"""PyInstaller 打包入口。

不能直接把 `tunless/__main__.py` 当入口脚本 —— 它用的是相对导入
（`from .cli import main`），被当作顶层脚本执行时会直接 ImportError。
这里以绝对导入的方式把包内入口拉起来。
"""

from __future__ import annotations

import sys


def main() -> int:
    from tunless.__main__ import main as package_main

    return package_main()


if __name__ == "__main__":
    sys.exit(main())
