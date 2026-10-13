"""L5 可选的机器级 WinHTTP 代理开关。

WinHTTP 的代理配置在 `HKLM\\...\\Internet Settings\\Connections\\WinHttpSettings`，
**只有机器级**，没有按进程/按用户的 API。所以对"只走 WinHTTP 的原生应用"，
在"免 TUN + 零注入"的前提下唯一能做的就是改全机设置 —— 因此这里：
  * 必须管理员；
  * 先把原值备份进配置，随时能还原；
  * UI 上必须写清楚这是全机生效，不是按应用。
"""

from __future__ import annotations

import ctypes
import re
import subprocess

CREATE_NO_WINDOW = 0x08000000

_DIRECT_MARKERS = ("直接访问", "Direct access", "直接存取")


def _candidate_encodings() -> list[str]:
    """netsh 这类系统工具的输出编码取决于当时的控制台代码页。

    * 控制台 CP 是 65001（UTF-8 终端）时，输出就是 UTF-8；
    * 默认中文系统（CP 936）时，输出是 GBK。

    打包后的 GUI 没有控制台（CP=936），所以 netsh 会吐 GBK 中文 ——
    之前一律按 UTF-8 解码，界面上就是一片「����」。
    """
    encodings = ["utf-8"]
    try:
        oem = int(ctypes.windll.kernel32.GetOEMCP())
        if oem:
            encodings.append(f"cp{oem}")
    except Exception:
        pass
    encodings.extend(["mbcs", "gbk", "latin-1"])
    return encodings


def decode_console(raw: bytes) -> str:
    """按"UTF-8 → OEM 代码页 → 本地 ANSI → latin-1"的顺序解码。

    中文 GBK 字节几乎不可能是合法 UTF-8，所以先试 UTF-8 是安全的；
    纯 ASCII 时两者结果相同。
    """
    if not raw:
        return ""
    for encoding in _candidate_encodings():
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "replace")


def _run(args: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    output = decode_console(result.stdout or b"")
    error = decode_console(result.stderr or b"")
    return result.returncode, (output + error).strip()


def show() -> str:
    code, text = _run(["netsh", "winhttp", "show", "proxy"])
    return text if code == 0 else f"(读取失败) {text}"


def is_direct(text: str) -> bool:
    return any(marker in text for marker in _DIRECT_MARKERS)


def set_proxy(host: str, port: int) -> tuple[bool, str]:
    code, text = _run(
        ["netsh", "winhttp", "set", "proxy", f"{host}:{port}", "localhost;127.*;10.*;192.168.*;<local>"]
    )
    return code == 0, text


def reset_proxy() -> tuple[bool, str]:
    code, text = _run(["netsh", "winhttp", "reset", "proxy"])
    return code == 0, text


# `netsh winhttp show proxy` 的中英文输出：
#   代理服务器: 10.0.0.5:8080        Proxy Server(s) : 10.0.0.5:8080
#   绕过列表  : <local>              Bypass List     : <local>
_SERVER_LINE = re.compile(
    r"^\s*(?:代理服务器|Proxy Server\(s\)|Proxy Server)\s*[:：]\s*(.+?)\s*$", re.MULTILINE
)
_BYPASS_LINE = re.compile(r"^\s*(?:绕过列表|Bypass List)\s*[:：]\s*(.+?)\s*$", re.MULTILINE)


def parse_backup(text: str) -> tuple[str | None, str | None]:
    """从备份的 netsh 输出里取回 (代理服务器, 绕过列表)。"""
    servers = _SERVER_LINE.search(text or "")
    bypass = _BYPASS_LINE.search(text or "")
    return (
        servers.group(1).strip() if servers else None,
        bypass.group(1).strip() if bypass else None,
    )


def restore(original: str, host: str, port: int) -> tuple[bool, str]:
    """按备份内容还原。

    之前这里是"原来是直连就 reset，否则用**当前界面上的** host:port 重新 set" ——
    那等于把机器原本的企业代理改成本程序要设的那个地址，还对外宣称"还原"。
    现在从备份文本里解析出原来的服务器地址，原样设回去；解析不出来就明确报错，
    不去猜、也不动系统设置。
    """
    if not original or is_direct(original):
        return reset_proxy()

    servers, bypass = parse_backup(original)
    if not servers:
        return False, (
            "备份里没有识别出原来的代理服务器地址，为安全起见没有改动系统设置。"
            f"原备份内容：{original.strip()[:200]}"
        )
    args = ["netsh", "winhttp", "set", "proxy", servers]
    if bypass:
        args.append(bypass)
    code, text = _run(args)
    return code == 0, text
