"""Clash 控制接口客户端。

Clash Verge Rev 的 mihomo 侧车默认**不监听 TCP 控制器**，而是把 external-controller
开在命名管道上：

    external-controller: ''
    external-controller-pipe: \\\\.\\pipe\\verge-mihomo-sidecar-release-<hash>

所以这里直接对着管道手写 HTTP/1.1，并自己解 chunked（实测响应就是 chunked）。
拿不到就静默降级 —— 这个功能只是锦上添花，不能影响主流程。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..detect import endpoint as endpoint_mod

PIPE_RE = re.compile(r"^external-controller-pipe:\s*(.+?)\s*$", re.MULTILINE)
SECRET_RE = re.compile(r"^secret:\s*(.+?)\s*$", re.MULTILINE)
TCP_RE = re.compile(r"^external-controller:\s*['\"]?([\d.]+:\d+)['\"]?\s*$", re.MULTILINE)


class ClashApi:
    """能读就用，读不到 available 就是 False。"""

    def __init__(self, config_path: str | None = None) -> None:
        self.available = False
        self.pipe_name = ""
        self.tcp_address = ""
        self.secret = ""
        self.error = ""

        path = endpoint_mod.clash_verge_config_file(config_path)
        if path is None:
            self.error = "未找到 Clash 配置文件"
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.error = f"读取失败：{exc}"
            return

        match = PIPE_RE.search(text)
        if match:
            self.pipe_name = match.group(1).strip().strip("'\"")
        tcp = TCP_RE.search(text)
        if tcp:
            self.tcp_address = tcp.group(1).strip()
        secret = SECRET_RE.search(text)
        if secret:
            self.secret = secret.group(1).strip().strip("'\"")

        self.available = bool(self.pipe_name or self.tcp_address)
        if not self.available:
            self.error = "配置里没有可用的 external-controller"

    # ------------------------------------------------------------ 传输

    def _http_get_pipe(self, path: str, timeout_ms: int = 1500) -> str:
        import pywintypes
        import win32file

        handle = win32file.CreateFile(
            self.pipe_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
        try:
            request = (
                f"GET {path} HTTP/1.1\r\n"
                "Host: localhost\r\n"
                f"Authorization: Bearer {self.secret}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            win32file.WriteFile(handle, request)
            chunks: list[bytes] = []
            while True:
                try:
                    _rc, data = win32file.ReadFile(handle, 65536)
                except pywintypes.error:
                    break
                if not data:
                    break
                chunks.append(data)
                if len(chunks) > 512:
                    break
        finally:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
        return _decode_http(b"".join(chunks))

    def _http_get_tcp(self, path: str, timeout: float = 2.0) -> str:
        import urllib.request

        url = f"http://{self.tcp_address}{path}"
        request = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.secret}"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def get(self, path: str) -> dict | list | None:
        if not self.available:
            return None
        text = ""
        if self.pipe_name:
            try:
                text = self._http_get_pipe(path)
            except Exception as exc:  # noqa: BLE001 - 任何失败都降级
                self.error = f"管道读取失败：{type(exc).__name__}: {exc}"
        if not text and self.tcp_address:
            try:
                text = self._http_get_tcp(path)
            except Exception as exc:  # noqa: BLE001
                self.error = f"TCP 控制器读取失败：{type(exc).__name__}: {exc}"
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            self.error = "响应不是合法 JSON"
            return None

    # ------------------------------------------------------------ 业务

    def connections(self) -> list[dict]:
        data = self.get("/connections")
        if isinstance(data, dict):
            items = data.get("connections")
            if isinstance(items, list):
                return items
        return []

    def by_process(self) -> dict[str, int]:
        """进程名 -> 连接数，用来做"这个应用有没有走 Clash"的旁证。"""
        counts: dict[str, int] = {}
        for item in self.connections():
            meta = item.get("metadata") or {}
            name = str(meta.get("process") or meta.get("processPath") or "?")
            counts[name] = counts.get(name, 0) + 1
        return counts


def _decode_http(raw: bytes) -> str:
    if not raw:
        return ""
    marker = raw.find(b"\r\n\r\n")
    if marker < 0:
        return raw.decode("utf-8", "replace")
    header = raw[:marker].decode("latin-1", "replace")
    body = raw[marker + 4:]

    if "transfer-encoding: chunked" in header.lower():
        out = bytearray()
        index = 0
        while index < len(body):
            end = body.find(b"\r\n", index)
            if end < 0:
                break
            try:
                size = int(body[index:end].split(b";")[0], 16)
            except ValueError:
                break
            if size == 0:
                break
            start = end + 2
            out += body[start:start + size]
            index = start + size + 2
        body = bytes(out)

    return body.decode("utf-8", "replace")
