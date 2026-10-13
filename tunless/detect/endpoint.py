"""代理端点探测与连通性测试。

优先级：
  1. 手动指定（设置里 manual）
  2. Clash Verge Rev 的 config.yaml（mixed-port / socks-port / port）
  3. 注册表里的系统代理（HKCU\\...\\Internet Settings\\ProxyServer）
  4. 候选端口探活（7897, 7898, 7899, 1080, 10808, 7890）

不依赖 PyYAML：只从 Clash 配置里抓几个顶层标量键。
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..model import ProxyEndpoint

CLASH_VERGE_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev",
    Path(os.environ.get("LOCALAPPDATA", "")) / "io.github.clash-verge-rev.clash-verge-rev",
    Path(os.environ.get("APPDATA", "")) / "top.gydi.clashverge",
]

CANDIDATE_PORTS = [7897, 7898, 7899, 1080, 10808, 7890, 2080]

# 回显端点。按"可靠、不限流"排序：
#   ipify 不返回地区但从不限流，适合判断"通不通 / 出口变没变"；
#   ip-api / ipwho 能给出国家码，但免费额度很紧（实测会被限流）。
IP_ECHO_URLS = [
    "https://api.ipify.org?format=json",
    "http://ip-api.com/json",
    "https://ipwho.is/",
    "https://ipinfo.io/json",
]

PROBE_TIMEOUT = 5.0


# ---------------------------------------------------------------- Clash 配置

def clash_verge_config_file(explicit: str | None = None) -> Path | None:
    """返回 Clash Verge 的配置文件。

    优先 `clash-verge.yaml`：那是 mihomo **实际在跑**的合并后配置，
    端口、控制器、管道名都以它为准；`config.yaml` 只是用户编辑的模板，
    改了 UI 里的端口后不一定同步。模板作为兜底。
    """
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    for base in CLASH_VERGE_DIRS:
        for name in ("clash-verge.yaml", "config.yaml"):
            p = base / name
            if p.is_file():
                return p
    return None


def clash_verge_config_files() -> list[Path]:
    """两个候选文件都返回（运行时配置在前），用于合并取值。"""
    found: list[Path] = []
    for base in CLASH_VERGE_DIRS:
        for name in ("clash-verge.yaml", "config.yaml"):
            path = base / name
            if path.is_file() and path not in found:
                found.append(path)
    return found


def _scalar(text: str, key: str) -> str | None:
    """抓取顶层 `key: value`（忽略缩进过的同名子键）。"""
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*(?:#.*)?$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip().strip("'\"")
    return value or None


def read_clash_verge_ports(explicit: str | None = None) -> dict[str, Any]:
    """读取 Clash 的端口配置，运行时配置优先、模板兜底。"""
    if explicit:
        candidates = [Path(explicit)] if Path(explicit).is_file() else []
    else:
        candidates = clash_verge_config_files()
    if not candidates:
        return {}

    out: dict[str, Any] = {"config_path": str(candidates[0])}
    keys = (("mixed-port", "mixed"), ("socks-port", "socks"), ("port", "http"))

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, name in keys:
            if name in out:
                continue
            raw = _scalar(text, key)
            if raw is None:
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value:
                out[name] = value
        if "bind" not in out:
            bind = _scalar(text, "bind-address")
            if bind:
                out["bind"] = bind
    return out


def read_system_proxy() -> dict[str, Any]:
    """读 HKCU 的 WinINET 代理设置（Clash Verge 的"系统代理"开关就写这里）。"""
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return {}
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            server = winreg.QueryValueEx(key, "ProxyServer")[0]
    except OSError:
        return {}
    if not enable or not server:
        return {}
    text = str(server)
    # 形如 "127.0.0.1:7897" 或 "http=127.0.0.1:7899;https=...;socks=127.0.0.1:7898"
    host, port = None, None
    match = re.search(r"(?:^|;)(?:https?=)?([\d.]+):(\d+)", text)
    if match:
        host, port = match.group(1), int(match.group(2))
    return {"host": host, "port": port, "raw": text}


# ---------------------------------------------------------------- 探活

def tcp_alive(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# bind-address 常见取值里，这些表示"监听所有网卡"，不是能用来连接的主机名
_WILDCARD_BINDS = {"*", "0.0.0.0", "::", "[::]", "any", ""}


def normalize_bind(value: str | None) -> str:
    """把 bind-address 归一化成可连接的主机名。

    Clash 开了 allow-lan 时 bind-address 常是 `*`，直接拿去连会变成
    `*:7897` 这种根本连不上的东西 —— 这种情况一律回落到 127.0.0.1。
    """
    if not value:
        return ""
    text = str(value).strip().strip("'\"")
    return "" if text.lower() in _WILDCARD_BINDS else text


def detect(clash_config_path: str | None = None, manual: dict[str, Any] | None = None) -> ProxyEndpoint:
    """按优先级推断代理端点。"""
    if manual and manual.get("port"):
        return ProxyEndpoint(
            host=str(manual.get("host") or "127.0.0.1"),
            mixed_port=int(manual["port"]),
            socks_port=int(manual.get("socksPort") or manual["port"]),
            http_port=int(manual.get("httpPort") or manual["port"]),
            source="manual",
        )

    ports = read_clash_verge_ports(clash_config_path)
    if ports.get("mixed"):
        ep = ProxyEndpoint(
            host=normalize_bind(ports.get("bind")) or "127.0.0.1",
            mixed_port=int(ports["mixed"]),
            socks_port=int(ports.get("socks") or ports["mixed"]),
            http_port=int(ports.get("http") or ports["mixed"]),
            source="clash-config",
        )
        if tcp_alive(ep.host, ep.mixed_port):
            return ep
        # 配置里有但没监听：继续往下找活的
        fallback = _probe_candidates(ep.host)
        return fallback or ep

    sysproxy = read_system_proxy()
    if sysproxy.get("port"):
        ep = ProxyEndpoint(
            host=str(sysproxy.get("host") or "127.0.0.1"),
            mixed_port=int(sysproxy["port"]),
            socks_port=int(sysproxy["port"]),
            http_port=int(sysproxy["port"]),
            source="registry",
        )
        if tcp_alive(ep.host, ep.mixed_port):
            return ep

    return _probe_candidates("127.0.0.1") or ProxyEndpoint(source="default")


def _probe_candidates(host: str) -> ProxyEndpoint | None:
    for port in CANDIDATE_PORTS:
        if tcp_alive(host, port):
            return ProxyEndpoint(
                host=host, mixed_port=port, socks_port=port, http_port=port, source="probe"
            )
    return None


# ---------------------------------------------------------------- 连通性测试

def _http_get(url: str, proxy_url: str | None, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str]:
    """用 urllib 发一个请求；proxy_url=None 表示直连。返回 (成功, 响应文本或错误)。"""
    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": "TunlessProxy/0.1"})
    try:
        with opener.open(request, timeout=timeout) as resp:
            return True, resp.read(4096).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _identity(payload: str) -> tuple[str | None, str | None, bool]:
    """从回显里取出 (国家码, IP, 是否解析成功)。

    免费端点会限流，限流响应往往也是合法 JSON（`success:false` /
    `status:fail`），必须识别出来并换下一个端点，否则会把限流误判成
    "代理不通"。
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None, None, False
    if not isinstance(data, dict):
        return None, None, False
    if data.get("success") is False or data.get("status") == "fail":
        return None, None, False

    country = None
    for key in ("country_code", "countryCode", "country"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            country = value.strip()
            break

    ip = None
    for key in ("ip", "query", "yourFacingIp"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            ip = value.strip()
            break

    return country, ip, True


def _probe(urls: list[str], proxy_url: str | None) -> dict[str, Any]:
    """依次尝试回显端点，返回第一个解析成功的结果。"""
    last_error = ""
    for url in urls:
        ok, payload = _http_get(url, proxy_url)
        if not ok:
            last_error = payload
            continue
        country, ip, parsed = _identity(payload)
        if not parsed:
            last_error = "回显响应无法解析（多半是被限流了）"
            continue
        return {
            "ok": True, "country": country, "ip": ip,
            "payload": payload[:400], "url": url, "error": "",
        }
    return {
        "ok": False, "country": None, "ip": None,
        "payload": "", "url": "", "error": last_error,
    }


def test_connectivity(endpoint: ProxyEndpoint) -> dict[str, Any]:
    """返回结构化结论，供 UI 直接显示。

    verdict:
      ok             代理通，且出口与直连不同（或直连压根不通）
      same_egress    代理通但出口与直连一致（Clash 规则可能把该请求走了 DIRECT）
      unverified     代理通，但拿不到可比对的出口标识
      proxy_down     代理端口不通
      unknown        无法判定
    """
    alive = tcp_alive(endpoint.host, endpoint.mixed_port, timeout=0.6)
    proxy = _probe(IP_ECHO_URLS, endpoint.http_url)
    direct = _probe(IP_ECHO_URLS, None)

    result: dict[str, Any] = {
        "host": endpoint.host,
        "port": endpoint.mixed_port,
        "tcp_alive": alive,
        "proxy_ok": proxy["ok"],
        "direct_ok": direct["ok"],
        "proxy_country": proxy["country"],
        "direct_country": direct["country"],
        "proxy_ip": proxy["ip"],
        "direct_ip": direct["ip"],
        "proxy_payload": proxy["payload"],
        "direct_payload": direct["payload"],
        "proxy_error": proxy["error"],
        "direct_error": direct["error"],
        "verdict": "unknown",
    }

    if not alive and not proxy["ok"]:
        result["verdict"] = "proxy_down"
    elif proxy["ok"] and not direct["ok"]:
        # 直连不通、代理通 —— 恰恰是代理在起作用的典型情形
        result["verdict"] = "ok"
    elif proxy["ok"] and direct["ok"]:
        # 必须比"同一类"标识：一个给 IP、另一个只给国家码时直接判不等，
        # 会永远得出 ok —— 那是个假阳性。
        same: bool | None = None
        if proxy["ip"] and direct["ip"]:
            same = proxy["ip"] == direct["ip"]
        elif proxy["country"] and direct["country"]:
            same = proxy["country"].upper() == direct["country"].upper()

        if same is None:
            result["verdict"] = "unverified"
        else:
            result["verdict"] = "same_egress" if same else "ok"
    return result


def verdict_text(result: dict[str, Any]) -> str:
    mapping = {
        "ok": "代理正常：经代理可出网，出口与直连不同",
        "same_egress": "代理可连，但出口与直连相同（Clash 规则可能把该请求走了 DIRECT）",
        "unverified": "代理可连，但回显端点都拿不到出口标识，无法确认出口是否改变",
        "proxy_down": "代理端口不通：请先启动 Clash 或检查端口设置",
        "unknown": "无法判定：直连与代理都没能取到回显",
    }
    return mapping.get(result.get("verdict", "unknown"), "未知状态")
