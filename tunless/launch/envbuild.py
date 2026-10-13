"""L1 环境变量注入。

这一层覆盖：Go / Rust / Python(requests, urllib) / Node(需 NODE_USE_ENV_PROXY) /
curl / git / npm / pip / cargo / .NET Core(HttpClient) / JVM(JAVA_TOOL_OPTIONS)。

注意：Chromium 在 Windows 上**不读**代理环境变量，所以 Electron 类应用必须靠
L2 命令行参数（见 cmdline.py）；这里给它们设环境变量是为了照顾它们拉起的
Node 子进程，属额外保险。
"""

from __future__ import annotations

import os

from ..model import BUILTIN_NO_PROXY, Family, Lever, Profile, ProxyEndpoint


def no_proxy_entries(profile: Profile, base_env: dict[str, str] | None = None) -> list[str]:
    """内置内网段 + 用户既有 NO_PROXY + 该应用自定义，去重保序。"""
    entries: list[str] = []
    seen: set[str] = set()

    def add(items) -> None:
        for item in items:
            text = str(item).strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                entries.append(text)

    add(BUILTIN_NO_PROXY)

    env = base_env if base_env is not None else os.environ
    for key in ("NO_PROXY", "no_proxy"):
        raw = env.get(key)
        if raw:
            add(part for part in raw.replace(";", ",").split(","))

    add(profile.no_proxy_extra)
    return entries


def _java_options(endpoint: ProxyEndpoint) -> str:
    host, port = endpoint.host, endpoint.mixed_port
    non_proxy = "localhost|127.*|[::1]|10.*|172.16.*|192.168.*|169.254.*"
    return (
        f"-Dhttp.proxyHost={host} -Dhttp.proxyPort={port} "
        f"-Dhttps.proxyHost={host} -Dhttps.proxyPort={port} "
        f"-DsocksProxyHost={host} -DsocksProxyPort={port} "
        f"-Dhttp.nonProxyHosts={non_proxy}"
    )


def _append_options(existing: str | None, extra: str) -> str:
    existing = (existing or "").strip()
    return f"{existing} {extra}".strip() if existing else extra


def build_env(
    profile: Profile,
    endpoint: ProxyEndpoint,
    base_env: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (完整环境, 相对基线新增/修改的键值)。"""
    base = dict(base_env if base_env is not None else os.environ)
    delta: dict[str, str] = {}

    if profile.lever_enabled(Lever.ENV):
        http = endpoint.http_url
        socks = endpoint.socks_url

        delta["HTTP_PROXY"] = http
        delta["http_proxy"] = http
        delta["HTTPS_PROXY"] = http
        delta["https_proxy"] = http
        delta["ALL_PROXY"] = socks
        delta["all_proxy"] = socks

        joined = ",".join(no_proxy_entries(profile, base))
        delta["NO_PROXY"] = joined
        delta["no_proxy"] = joined

        # Node 24+ 才认识这个开关；老版本会安静忽略
        if profile.spec.family in (Family.NODE, Family.CLI):
            delta["NODE_USE_ENV_PROXY"] = "1"

        # 任何进程树里可能出现的 JVM（含 gradle/maven wrapper）都能吃到
        if profile.spec.family in (Family.JAVA, Family.CLI):
            opts = _java_options(endpoint)
            delta["JAVA_TOOL_OPTIONS"] = _append_options(base.get("JAVA_TOOL_OPTIONS"), opts)
            delta["MAVEN_OPTS"] = _append_options(base.get("MAVEN_OPTS"), opts)
            delta["GRADLE_OPTS"] = _append_options(base.get("GRADLE_OPTS"), opts)

        delta["CARGO_HTTP_PROXY"] = http

    delta.update({str(k): str(v) for k, v in (profile.env_extra or {}).items()})
    delta.update({str(k): str(v) for k, v in (extra or {}).items()})

    env = dict(base)
    env.update(delta)
    return env, delta
