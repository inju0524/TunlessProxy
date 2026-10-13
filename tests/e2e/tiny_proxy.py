"""一个极小的 HTTP 代理，用来做"请求到底有没有到代理"的确定性断言。

比拿 ip-api/ipwho 对比出口国家码可靠得多：
  * 不依赖外网、不受限流影响；
  * 不受 Clash 系统代理（Chromium 会读 WinINET）干扰 —— 目标指向这个假代理，
    只有真的把请求发给它才会被记录；
  * 同时支持绝对 URI 形式的普通请求和 CONNECT 隧道。
"""

from __future__ import annotations

import socket
import threading
import time

CANNED_BODY = b'{"ok": true, "via": "tinyproxy", "note": "request reached the proxy"}'
CANNED_RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: application/json\r\n"
    b"Content-Length: " + str(len(CANNED_BODY)).encode() + b"\r\n"
    b"Connection: close\r\n\r\n" + CANNED_BODY
)


class TinyProxy(threading.Thread):
    """在 127.0.0.1 的随机端口上跑一个可记录的 HTTP 代理。"""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(16)
        self.port: int = self._server.getsockname()[1]
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ------------------------------------------------------------ 生命周期

    def run(self) -> None:
        self._server.settimeout(0.3)
        while not self._stop.is_set():
            try:
                client, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass

    def __enter__(self) -> "TinyProxy":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    # ------------------------------------------------------------ 处理

    def _serve(self, client: socket.socket) -> None:
        try:
            client.settimeout(5.0)
            data = b""
            while b"\r\n\r\n" not in data and len(data) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
            if not data:
                return

            head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace")
            lines = head.split("\r\n")
            request_line = lines[0] if lines else ""
            parts = request_line.split(" ")
            method = parts[0] if parts else ""
            target = parts[1] if len(parts) > 1 else ""
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            with self._lock:
                self.requests.append({
                    "method": method,
                    "target": target,
                    "host": headers.get("host", ""),
                    "raw": request_line,
                    "at": time.time(),
                })

            if method.upper() == "CONNECT":
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                return
            client.sendall(CANNED_RESPONSE)
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    # ------------------------------------------------------------ 断言辅助

    def targets(self) -> list[str]:
        with self._lock:
            return [item["target"] for item in self.requests]

    def saw(self, needle: str) -> bool:
        return any(needle in target for target in self.targets())

    def wait_for(self, needle: str, timeout: float = 20.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.saw(needle):
                return True
            time.sleep(0.15)
        return False

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
