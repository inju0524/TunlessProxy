"""测试入口（不依赖 pytest，只用标准库 unittest）。

    python tests/run_all.py

测试跑在**临时数据目录**里（`TUNLESS_DATA_DIR`）：否则用例会往程序同级的
`data\\` 里塞测试 profile 目录，跑完还得靠清理；真实数据完全不受影响。
启动时创建的临时目录在进程退出后由系统回收，需要留证时可以自己设这个变量。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 必须在本 package 导入 tunless.config 之前设好 —— 数据目录是在 import 时解析的
os.environ.setdefault(
    "TUNLESS_DATA_DIR", tempfile.mkdtemp(prefix="tunless-testdata-")
)


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / "tests"), pattern="test_*.py", top_level_dir=str(ROOT)
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
