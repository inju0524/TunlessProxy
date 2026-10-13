"""L3 配置文件指针注入。

思路：不碰用户的真实配置，而是在数据目录的 `profiles\\<id>\\` 下
生成一份**包含用户原配置内容**的私有配置，再用"配置路径类"环境变量把工具指过来：

    GIT_CONFIG_GLOBAL / NPM_CONFIG_USERCONFIG / PIP_CONFIG_FILE
    CURL_HOME / WGETRC / DOCKER_CONFIG / GIT_SSH_COMMAND

这样既保住了用户的 token、registry、alias，又只在这一次启动里生效。
"""

from __future__ import annotations

import configparser
import io
import json
import os
import shutil
from pathlib import Path

from .. import config
from ..model import Lever, Profile, ProxyEndpoint

GIT_USER_CONFIGS = [
    Path(os.environ.get("USERPROFILE", "")) / ".gitconfig",
    Path(os.environ.get("XDG_CONFIG_HOME", "")) / "git" / "config"
    if os.environ.get("XDG_CONFIG_HOME")
    else Path(os.environ.get("USERPROFILE", "")) / ".config" / "git" / "config",
]
NPM_USER_CONFIG = Path(os.environ.get("USERPROFILE", "")) / ".npmrc"
CURL_USER_CONFIG = Path(os.environ.get("USERPROFILE", "")) / ".curlrc"
WGET_USER_CONFIG = Path(os.environ.get("USERPROFILE", "")) / ".wgetrc"
DOCKER_USER_CONFIG = Path(os.environ.get("USERPROFILE", "")) / ".docker" / "config.json"

PIP_USER_CONFIGS = [
    Path(os.environ.get("APPDATA", "")) / "pip" / "pip.ini",
    Path(os.environ.get("USERPROFILE", "")) / "pip" / "pip.ini",
    Path(os.environ.get("PROGRAMDATA", "")) / "pip" / "pip.ini",
]

CONNECT_EXE_CANDIDATES = [
    Path(r"C:\Program Files\Git\mingw64\bin\connect.exe"),
    Path(r"C:\Program Files\Git\mingw32\bin\connect.exe"),
    Path(r"C:\Program Files (x86)\Git\mingw32\bin\connect.exe"),
]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _find_connect_exe() -> Path | None:
    for candidate in CONNECT_EXE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------- 各工具

def _gitconfig(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    # 顺序很重要：git 后读到的值覆盖先前的，所以 include 必须在前面，
    # 我们的 proxy 放最后，才能压过用户自己可能设过的 http.proxy。
    lines = [
        "# 由 TunlessProxy 生成：代理只在本次启动生效，你的全局配置被 include 进来了",
    ]
    for user_config in GIT_USER_CONFIGS:
        if user_config.is_file():
            lines += ["[include]", f"\tpath = {_posix(user_config)}"]
    lines += [
        "[http]",
        f"\tproxy = {endpoint.http_url}",
        "[https]",
        f"\tproxy = {endpoint.http_url}",
    ]
    return "\n".join(lines) + "\n"


def _npmrc(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    head = _read_text(NPM_USER_CONFIG).rstrip()
    lines = []
    if head:
        lines.append("# ---- 以下是你的 ~/.npmrc 原样内容 ----")
        lines.append(head)
        lines.append("# ---- 以上为原内容，以下由 TunlessProxy 追加 ----")
    lines += [
        f"proxy={endpoint.http_url}",
        f"https-proxy={endpoint.http_url}",
        "strict-ssl=true",
    ]
    return "\n".join(lines) + "\n"


def _pip_ini(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    """合并用户的 pip 配置再写入 proxy。

    不能简单追加：pip 用严格模式的 configparser 读 ini，出现两个 [global]
    会直接报 DuplicateSectionError。
    """
    parser = configparser.RawConfigParser(strict=False)
    for candidate in PIP_USER_CONFIGS:
        if candidate.is_file():
            try:
                parser.read_string(_read_text(candidate), source=str(candidate))
            except configparser.Error:
                pass
            break
    if not parser.has_section("global"):
        parser.add_section("global")
    parser.set("global", "proxy", endpoint.http_url)
    buffer = io.StringIO()
    parser.write(buffer)
    return (
        "# 由 TunlessProxy 生成：已合并你原有的 pip 配置，仅追加 proxy\n"
        + buffer.getvalue()
    )


def _curlrc(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    head = _read_text(CURL_USER_CONFIG).rstrip()
    noproxy = " ".join(["localhost", "127.0.0.1", "10.0.0.0/8", "192.168.0.0/16"])
    lines = [head] if head else []
    lines += [
        f'proxy = "{endpoint.http_url}"',
        f'noproxy = "{noproxy}"',
    ]
    return "\n".join(lines) + "\n"


def _wgetrc(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    head = _read_text(WGET_USER_CONFIG).rstrip()
    lines = [head] if head else []
    lines += [
        "use_proxy = yes",
        f"http_proxy = {endpoint.http_url}",
        f"https_proxy = {endpoint.http_url}",
    ]
    return "\n".join(lines) + "\n"


def _ssh_config(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str | None:
    connect = _find_connect_exe()
    if connect is None:
        return None
    lines = ["# 由 TunlessProxy 生成：ssh 经 HTTP CONNECT 走代理"]
    # 必须先把用户自己的 ssh 配置 include 进来，否则 -F 会把它整个顶掉
    user_ssh = Path(os.environ.get("USERPROFILE", "")) / ".ssh" / "config"
    if user_ssh.is_file():
        lines.append(f"Include {_posix(user_ssh)}")
    lines += [
        f'ProxyCommand "{connect}" -H {endpoint.host}:{endpoint.mixed_port} %h %p',
        "ProxyUseFdpass no",
        "ServerAliveInterval 30",
    ]
    return "\n".join(lines) + "\n"


def _docker_config(profile: Profile, endpoint: ProxyEndpoint, directory: Path) -> str:
    data: dict = {}
    if DOCKER_USER_CONFIG.is_file():
        try:
            data = json.loads(_read_text(DOCKER_USER_CONFIG) or "{}")
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
    proxies = data.setdefault("proxies", {})
    proxies["default"] = {
        "httpProxy": endpoint.http_url,
        "httpsProxy": endpoint.http_url,
        "noProxy": "localhost,127.0.0.1,10.0.0.0/8,192.168.0.0/16",
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- 入口

def write_all(
    profile: Profile, endpoint: ProxyEndpoint
) -> tuple[dict[str, str], dict[str, str]]:
    """生成私有配置文件。返回 (环境变量, {文件路径: 摘要})。"""
    if not profile.lever_enabled(Lever.CONFIG_FILES):
        return {}, {}

    directory = config.profile_dir(profile.id)
    env: dict[str, str] = {}
    summaries: dict[str, str] = {}

    gitconfig = directory / "gitconfig"
    _write(gitconfig, _gitconfig(profile, endpoint, directory))
    env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    summaries[str(gitconfig)] = f"[http]/[https] proxy = {endpoint.http_url}"

    npmrc = directory / "npmrc"
    _write(npmrc, _npmrc(profile, endpoint, directory))
    env["NPM_CONFIG_USERCONFIG"] = str(npmrc)
    summaries[str(npmrc)] = f"proxy/https-proxy = {endpoint.http_url}"

    pip_ini = directory / "pip.ini"
    _write(pip_ini, _pip_ini(profile, endpoint, directory))
    env["PIP_CONFIG_FILE"] = str(pip_ini)
    summaries[str(pip_ini)] = f"[global] proxy = {endpoint.http_url}"

    curlrc = directory / ".curlrc"
    _write(curlrc, _curlrc(profile, endpoint, directory))
    env["CURL_HOME"] = str(directory)
    summaries[str(curlrc)] = f"proxy = {endpoint.http_url}"

    wgetrc = directory / "wgetrc"
    _write(wgetrc, _wgetrc(profile, endpoint, directory))
    env["WGETRC"] = str(wgetrc)
    summaries[str(wgetrc)] = f"use_proxy=yes http_proxy={endpoint.http_url}"

    docker_dir = directory / "docker"
    docker_cfg = docker_dir / "config.json"
    _write(docker_cfg, _docker_config(profile, endpoint, directory))
    env["DOCKER_CONFIG"] = str(docker_dir)
    summaries[str(docker_cfg)] = f"proxies.default = {endpoint.http_url}"

    ssh_config = _ssh_config(profile, endpoint, directory)
    if ssh_config:
        ssh_path = directory / "ssh_config"
        _write(ssh_path, ssh_config)
        env["GIT_SSH_COMMAND"] = f'ssh -F "{ssh_path}"'
        summaries[str(ssh_path)] = f"ProxyCommand connect.exe -H {endpoint.host}:{endpoint.mixed_port}"

    return env, summaries


def ssh_config_path(profile: Profile) -> str | None:
    """给 ssh 追加 `-F <私有配置>` 用的路径。

    必须同时看 L3 开关：`ssh_config` 是上次开着 L3 时留在磁盘上的，只判断
    `is_file()` 的话，用户关掉 L3 之后 ssh 仍然会被追加 `-F`（陈旧产物继续生效）。
    """
    if not profile.lever_enabled(Lever.CONFIG_FILES):
        return None
    path = config.profile_dir(profile.id) / "ssh_config"
    return str(path) if path.is_file() else None


def clean_profile_dir(profile_id: str) -> None:
    directory = config.PROFILES_DIR / profile_id
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
