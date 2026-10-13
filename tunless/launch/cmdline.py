"""L2 命令行参数注入 + Windows 命令行拼装/拆分。

Chromium / Electron / WebView2 在 Windows 上不读代理环境变量，只有命令行开关有效。
WebView2 的开关通过环境变量 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 传递（见 proc.py）。
"""

from __future__ import annotations

import os
import re
import subprocess

from ..model import Family, Lever, Profile, ProxyEndpoint

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000

_ENV_VAR_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def expand_env_vars(text: str, env: dict[str, str]) -> str:
    """展开参数里的 %VAR%。

    CreateProcess 本身不做环境变量展开（那是 cmd.exe 干的），但用户从快捷方式
    里拖过来的参数经常带 %TEMP% 之类，不展开就会原样传给程序。只处理 %VAR%
    形式，不碰 $VAR，避免误伤。
    """
    if not text or "%" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        for key, value in env.items():
            if key.lower() == name.lower():
                return value
        return match.group(0)

    return _ENV_VAR_RE.sub(replace, text)


def split_windows_args(text: str) -> list[str]:
    """按 MSVC/CommandLineToArgvW 规则拆分命令行。

    不能直接用 shlex.split(posix=True)：那会把 `C:\\Program Files\\x` 里的反斜杠
    当成转义符吃掉。这里的规则是——反斜杠只在紧邻引号时才有特殊含义。
    """
    if not text:
        return []
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    pending_backslashes = 0
    started = False

    for ch in text:
        if ch == "\\":
            pending_backslashes += 1
            continue

        if ch == '"':
            # 反斜杠后跟引号：每两个反斜杠产出一个字面反斜杠
            current.append("\\" * (pending_backslashes // 2))
            if pending_backslashes % 2 == 0:
                in_quotes = not in_quotes
            else:
                current.append('"')
            pending_backslashes = 0
            started = True
            continue

        if pending_backslashes:
            current.append("\\" * pending_backslashes)
            pending_backslashes = 0

        if ch in " \t" and not in_quotes:
            if started or current:
                args.append("".join(current))
                current = []
                started = False
            continue

        current.append(ch)
        started = True

    if pending_backslashes:
        current.append("\\" * pending_backslashes)
    if started or current:
        args.append("".join(current))
    return args


def quote_arg(arg: str) -> str:
    """用 Windows 规则给单个参数加引号（交给 subprocess.list2cmdline）。"""
    return subprocess.list2cmdline([arg])


def chromium_switches(profile: Profile, endpoint: ProxyEndpoint) -> list[str]:
    """Chromium 系（Electron / WebView2 / CEF）的代理开关。"""
    if not profile.lever_enabled(Lever.CMDLINE):
        return []
    if profile.spec.family not in (Family.ELECTRON, Family.WEBVIEW2):
        return []

    switches = [
        # 用 HTTP 代理而不是 socks5：Chromium 会把主机名交给代理，天然远端解析、无 DNS 泄漏
        f"--proxy-server={endpoint.http_url}",
        f"--proxy-bypass-list=localhost;127.0.0.1;<local>",
    ]
    if profile.disable_quic:
        # UDP/443 走不了 TCP 代理，直接关掉 QUIC 免得漏流量
        switches.append("--disable-quic")
    if profile.force_remote_dns:
        switches.append("--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1")
    return switches


def build_command_line(
    profile: Profile,
    endpoint: ProxyEndpoint,
    ssh_config: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """返回 (完整命令行字符串, 追加的参数列表)。

    原始参数串原样保留（不做拆分再拼装，避免破坏引号/反斜杠），只做 %VAR% 展开，
    然后在其后追加我们的开关 —— Chromium 取最后一个同名开关，所以放最后是对的。
    """
    extra: list[str] = []

    if profile.spec.family == Family.WEBVIEW2:
        # 通过环境变量 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS 传，见 proc.py
        pass
    else:
        extra.extend(chromium_switches(profile, endpoint))

    if ssh_config and profile.spec.family == Family.CLI:
        basename = profile.spec.target.rsplit("\\", 1)[-1].lower()
        if basename in ("ssh.exe", "scp.exe", "sftp.exe"):
            extra.extend(["-F", ssh_config])

    extra.extend(profile.cmdline_extra or [])

    exe = profile.spec.target
    user_args = expand_env_vars((profile.spec.args or "").strip(), env or dict(os.environ))
    parts = [quote_arg(exe)]
    if user_args:
        parts.append(user_args)
    parts.extend(quote_arg(a) for a in extra)
    return " ".join(parts), extra


def creation_flags(profile: Profile) -> int:
    """GUI 应用不要额外控制台；命令行应用给一个新控制台，否则用户看不到输出。"""
    mode = (profile.console_mode or "auto").lower()
    if mode == "new":
        return CREATE_NEW_CONSOLE
    if mode == "none":
        return 0
    if profile.spec.family in (Family.CLI, Family.NODE):
        return CREATE_NEW_CONSOLE
    return 0
