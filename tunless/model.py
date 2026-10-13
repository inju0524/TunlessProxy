"""数据模型：代理端点、应用规格、启动计划。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

# 内置的直连网段：绝不把本地/内网流量塞进代理
BUILTIN_NO_PROXY = [
    "localhost",
    "127.0.0.1",
    "127.*",
    "::1",
    "<local>",
    "*.local",
    "*.lan",
    "10.*",
    "172.16.*", "172.17.*", "172.18.*", "172.19.*", "172.20.*", "172.21.*",
    "172.22.*", "172.23.*", "172.24.*", "172.25.*", "172.26.*", "172.27.*",
    "172.28.*", "172.29.*", "172.30.*", "172.31.*",
    "192.168.*",
    "169.254.*",
]


class Family(str, Enum):
    """应用家族 —— 决定施加哪些 lever。"""

    ELECTRON = "electron"
    WEBVIEW2 = "webview2"
    JAVA = "java"
    NODE = "node"
    CLI = "cli"
    NATIVE = "native"
    UWP = "uwp"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return {
            "electron": "Electron / Chromium",
            "webview2": "WebView2",
            "java": "Java",
            "node": "Node.js",
            "cli": "命令行工具",
            "native": "原生应用",
            "uwp": "UWP / 商店应用",
            "unknown": "未知",
        }[self.value]

    @property
    def per_app_supported(self) -> bool:
        """该家族是否能在"零注入"前提下按应用施加代理。"""
        return self not in (Family.NATIVE, Family.UWP, Family.UNKNOWN)


class Lever(str, Enum):
    ENV = "env"
    CMDLINE = "cmdline"
    CONFIG_FILES = "configFiles"

    @property
    def label(self) -> str:
        return {
            "env": "L1 环境变量",
            "cmdline": "L2 命令行参数",
            "configFiles": "L3 配置文件指针",
        }[self.value]


@dataclass
class ProxyEndpoint:
    """代理端点。mixed 端口在 Clash 里同时说 HTTP 与 SOCKS5。"""

    host: str = "127.0.0.1"
    mixed_port: int = 7897
    socks_port: int = 7898
    http_port: int = 7899
    source: str = "default"  # default | clash-config | registry | probe | manual

    @property
    def http_url(self) -> str:
        return f"http://{self.host}:{self.mixed_port}"

    @property
    def socks_url(self) -> str:
        """socks5h = 域名交给代理远端解析，避免 DNS 泄漏。"""
        return f"socks5h://{self.host}:{self.mixed_port}"

    @property
    def socks_plain_url(self) -> str:
        return f"socks5://{self.host}:{self.mixed_port}"

    @property
    def port(self) -> int:
        return self.mixed_port

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProxyEndpoint":
        data = data or {}
        # 注意要认 `port`：设置对话框写进去的 manual 就是 {"host":..,"port":..}，
        # 只认 mixedPort 会导致"手动指定端口"静默失效。
        mixed = data.get("mixedPort") or data.get("mixed_port") or data.get("port") or 7897
        return cls(
            host=str(data.get("host") or "127.0.0.1"),
            mixed_port=int(mixed),
            socks_port=int(data.get("socksPort") or data.get("socks_port") or mixed),
            http_port=int(data.get("httpPort") or data.get("http_port") or mixed),
            source=str(data.get("source") or "default"),
        )


@dataclass
class AppSpec:
    """解析后的应用启动规格。"""

    target: str = ""
    args: str = ""
    workdir: str = ""
    icon_source: str = ""
    arch: str = "unknown"       # x64 | x86 | arm64 | unknown
    subsystem: str = "unknown"  # gui | cui | unknown
    dotnet: bool = False
    requires_elevation: bool = False
    source_kind: str = "exe"    # lnk | exe | url | bat | unknown
    source_path: str = ""
    description: str = ""
    family: Family = Family.UNKNOWN
    family_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["family"] = self.family.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSpec":
        data = dict(data or {})
        family = data.pop("family", "unknown")
        try:
            fam = Family(family)
        except ValueError:
            fam = Family.UNKNOWN
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        spec = cls(**clean)
        spec.family = fam
        return spec


@dataclass
class Profile:
    """一个"按应用代理"配置。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    source_path: str = ""
    spec: AppSpec = field(default_factory=AppSpec)
    levers: dict[str, bool] = field(
        default_factory=lambda: {"env": True, "cmdline": True, "configFiles": True}
    )
    cmdline_extra: list[str] = field(default_factory=list)
    env_extra: dict[str, str] = field(default_factory=dict)
    no_proxy_extra: list[str] = field(default_factory=list)
    disable_quic: bool = True
    force_remote_dns: bool = False
    console_mode: str = "auto"  # auto | new | none
    adopt_shortcut: bool = False
    adopted_shortcut: str | None = None
    created_at: float = 0.0
    last_launched_at: float = 0.0
    launch_count: int = 0
    note: str = ""

    def lever_enabled(self, lever: Lever) -> bool:
        return bool(self.levers.get(lever.value, False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "sourcePath": self.source_path,
            "spec": self.spec.to_dict(),
            "levers": dict(self.levers),
            "cmdlineExtra": list(self.cmdline_extra),
            "envExtra": dict(self.env_extra),
            "noProxyExtra": list(self.no_proxy_extra),
            "disableQuic": self.disable_quic,
            "forceRemoteDns": self.force_remote_dns,
            "consoleMode": self.console_mode,
            "adoptShortcut": self.adopt_shortcut,
            "adoptedShortcut": self.adopted_shortcut,
            "createdAt": self.created_at,
            "lastLaunchedAt": self.last_launched_at,
            "launchCount": self.launch_count,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or ""),
            source_path=str(data.get("sourcePath") or ""),
            spec=AppSpec.from_dict(data.get("spec")),
            levers=dict(data.get("levers") or {"env": True, "cmdline": True, "configFiles": True}),
            cmdline_extra=list(data.get("cmdlineExtra") or []),
            env_extra=dict(data.get("envExtra") or {}),
            no_proxy_extra=list(data.get("noProxyExtra") or []),
            disable_quic=bool(data.get("disableQuic", True)),
            force_remote_dns=bool(data.get("forceRemoteDns", False)),
            console_mode=str(data.get("consoleMode") or "auto"),
            adopt_shortcut=bool(data.get("adoptShortcut", False)),
            adopted_shortcut=data.get("adoptedShortcut"),
            created_at=float(data.get("createdAt") or 0.0),
            last_launched_at=float(data.get("lastLaunchedAt") or 0.0),
            launch_count=int(data.get("launchCount") or 0),
            note=str(data.get("note") or ""),
        )


@dataclass
class LaunchPlan:
    """一次启动将要施加的全部内容，供 UI 预览与日志留痕。"""

    profile_id: str
    name: str
    executable: str
    command_line: str
    argv: list[str]
    cwd: str
    env: dict[str, str]
    env_delta: dict[str, str]
    config_files: dict[str, str]  # 路径 -> 内容摘要
    levers: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
