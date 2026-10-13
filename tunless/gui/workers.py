"""后台工作线程。

GUI 线程里做网络 I/O 会让界面卡住 —— 「测试代理」最坏要串行试 4 个回显端点，
再乘上直连/代理两条路径，能卡好几秒。放到 QThread 里。
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from .. import service
from ..model import ProxyEndpoint


class EndpointTestWorker(QThread):
    """测代理连通性，完成后发信号回主线程。"""

    tested = pyqtSignal(dict)

    def __init__(self, endpoint: ProxyEndpoint, parent=None) -> None:
        super().__init__(parent)
        self.endpoint = endpoint

    def run(self) -> None:  # noqa: D102 - QThread 入口
        try:
            result = service.test_endpoint(self.endpoint)
        except Exception as exc:  # noqa: BLE001 - 线程里不能抛
            result = {
                "verdict": "unknown",
                "error": f"{type(exc).__name__}: {exc}",
                "tcp_alive": False,
                "proxy_ok": False,
                "direct_ok": False,
                "proxy_country": None,
                "direct_country": None,
            }
        self.tested.emit(result)
