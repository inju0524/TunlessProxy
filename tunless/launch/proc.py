"""启动执行：把 LaunchPlan 变成一次真实进程创建。

刻意用 `subprocess.Popen(命令行字符串)`：字符串形式在 Windows 上会被原样作为
lpCommandLine 传给 CreateProcess，不做任何重新解析，因此用户原有的引号、
反斜杠、`%VAR%` 都不会被破坏。
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..model import Family, LaunchPlan, Lever, Profile, ProxyEndpoint
from . import cmdline as cmdline_mod
from . import configfiles, envbuild, shortcuts

CREATE_NEW_CONSOLE = cmdline_mod.CREATE_NEW_CONSOLE


class SelfLaunchRefused(RuntimeError):
    """目标指向本程序自己 —— 启动它等于无限自我拉起，必须拒绝。"""


@dataclass
class LaunchedProcess:
    profile_id: str
    name: str
    pid: int
    command_line: str
    cwd: str
    started_at: float
    levers: list[str] = field(default_factory=list)
    log_file: str = ""
    env_delta: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    returncode: int | None = None

    def to_dict(self) -> dict:
        return {
            "profileId": self.profile_id,
            "name": self.name,
            "pid": self.pid,
            "commandLine": self.command_line,
            "cwd": self.cwd,
            "startedAt": self.started_at,
            "levers": self.levers,
            "logFile": self.log_file,
            "notes": self.notes,
            "returncode": self.returncode,
        }


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------- 计划

def build_plan(
    profile: Profile, endpoint: ProxyEndpoint, base_env: dict[str, str] | None = None
) -> LaunchPlan:
    """组装一次启动要施加的全部内容（不产生任何副作用，除生成 L3 配置文件）。"""
    notes: list[str] = []

    if not profile.spec.target:
        notes.append("未解析出可执行目标，无法启动")
    elif not os.path.isfile(profile.spec.target):
        notes.append(f"目标文件不存在：{profile.spec.target}")
    elif shortcuts.is_self_launcher(profile.spec.target):
        notes.append(
            "目标是本程序自己的启动器：这多半是被接管的快捷方式被当成了应用本身，"
            "启动它会再次拉起本程序（无限链路），已拒绝启动。请用「重新添加」修复该配置。"
        )

    if profile.spec.family == Family.UWP:
        notes.append("UWP / 商店应用无法施加环境变量，本方案不支持按应用代理")
    elif not profile.spec.family.per_app_supported:
        notes.append(
            "该应用类型（原生 WinHTTP / 裸 WinSock）无法在「零注入」前提下按应用代理；"
            "可考虑设置里的「机器级 WinHTTP 代理」开关"
        )

    if profile.spec.requires_elevation and not is_elevated():
        notes.append(
            "该程序要求管理员权限：请以管理员身份运行本程序，否则代理设置不会传递给它"
        )

    from ..detect import endpoint as endpoint_mod

    if not endpoint_mod.tcp_alive(endpoint.host, endpoint.mixed_port, timeout=0.5):
        notes.append(
            f"代理端口 {endpoint.host}:{endpoint.mixed_port} 当前不通，应用可能无法联网"
        )

    # ssh 只能经 Git 自带的 connect.exe 走 HTTP CONNECT，装不到就静默失效 —— 说清楚
    if profile.lever_enabled(Lever.CONFIG_FILES):
        basename = os.path.basename(profile.spec.target or "").lower()
        if basename in ("ssh.exe", "scp.exe", "sftp.exe") and not configfiles.ssh_config_path(
            profile
        ):
            notes.append(
                "没找到 Git 自带的 connect.exe，ssh 无法经 HTTP CONNECT 走代理"
                "（安装 Git for Windows 后可用）"
            )

    config_env, config_files = configfiles.write_all(profile, endpoint)

    extra_env: dict[str, str] = dict(config_env)
    switches = cmdline_mod.chromium_switches(profile, endpoint)
    if switches and profile.spec.family == Family.WEBVIEW2:
        # WebView2 的 Chromium 开关只能通过这个环境变量传
        extra_env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join(switches)

    env, delta = envbuild.build_env(profile, endpoint, base_env=base_env, extra=extra_env)

    command_line, extra_args = cmdline_mod.build_command_line(
        profile,
        endpoint,
        ssh_config=configfiles.ssh_config_path(profile),
        env=env,
    )

    # 用户参数里引号没闭合时（典型：`--foo "C:\dir\` 这种以反斜杠+引号结尾的路径），
    # 我们追加在最后的开关会被并进前一个参数里 —— Chromium 收不到 --proxy-server，
    # 而界面上一切正常，等于代理静默失效。这里反查一次，发现吞掉就明说。
    if extra_args:
        tokens = cmdline_mod.split_windows_args(command_line)
        if tokens[-len(extra_args):] != extra_args:
            notes.append(
                "启动参数里的引号似乎没有闭合，追加的代理开关可能被当成上一个参数的值"
                "（代理会失效）。请检查该应用的启动参数。"
            )

    levers = [lever.value for lever in Lever if profile.lever_enabled(lever)]

    cwd = profile.spec.workdir
    if not cwd or not os.path.isdir(cwd):
        if profile.spec.family in (Family.CLI, Family.NODE):
            # 命令行工具在 exe 目录里跑没有任何意义（git/npm 要看当前仓库）
            cwd = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        elif profile.spec.target:
            cwd = os.path.dirname(profile.spec.target)
        else:
            cwd = os.getcwd()

    return LaunchPlan(
        profile_id=profile.id,
        name=profile.name,
        executable=profile.spec.target,
        command_line=command_line,
        argv=[profile.spec.target] + cmdline_mod.split_windows_args(profile.spec.args or "") + extra_args,
        cwd=cwd,
        env=env,
        env_delta=delta,
        config_files=config_files,
        levers=levers,
        notes=notes,
    )

# ---------------------------------------------------------------- 执行

SECRET_KEY_HINTS = (
    "PASS", "PWD", "SECRET", "TOKEN", "KEY", "SESSION", "COOKIE",
    "CREDENTIAL", "BEARER", "AUTH",
)

#: 命令行里 `--token=xxx` / `--api-key xxx` 这类直接落在命令行上的凭据
_SECRET_ARG_RE = re.compile(
    r"(?i)\b([-\w]*(?:" + "|".join(SECRET_KEY_HINTS) + r")[-\w]*)"
    r"(\s*=\s*|\s+)(\S+)"
)


def _redact(key: str, value: str) -> str:
    """日志里不能明文记 token —— 环境变量里经常有 API key。"""
    upper = key.upper()
    if any(hint in upper for hint in SECRET_KEY_HINTS):
        return f"<已脱敏 {len(value)} 字符>" if value else "<空>"
    return value


def redact_command_line(command_line: str) -> str:
    """命令行也必须脱敏：用户会把 token 直接写在启动参数里。

    `SSH_AUTH_SOCK` 这种含 AUTH 的键名会被误判成敏感 —— 宁可多脱一点：
    日志是给排障看的，少一个 socket 路径不影响判断，多一个明文 token 才是事故。
    """
    return _SECRET_ARG_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}<已脱敏>", command_line)


def _write_launch_log(plan: LaunchPlan, record: LaunchedProcess) -> str:
    # 文件名带毫秒：同一秒内启动两次（连续点两下）不会互相覆盖
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"
    path = config.log_path(f"launch-{plan.profile_id[:8]}-{stamp}.log")
    lines = [
        f"TunlessProxy 启动记录  {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"应用      : {plan.name}",
        f"命令行    : {redact_command_line(record.command_line)}",
        f"工作目录  : {plan.cwd}",
        f"PID       : {record.pid}",
        f"启用的层  : {', '.join(plan.levers) or '（无）'}",
        "",
        "== 注入的环境变量 ==",
    ]
    for key in sorted(plan.env_delta):
        lines.append(f"  {key} = {_redact(key, plan.env_delta[key])}")
    if plan.config_files:
        lines += ["", "== 生成的配置文件 (L3) =="]
        for path_text, summary in plan.config_files.items():
            lines.append(f"  {path_text}")
            lines.append(f"      {summary}")
    if plan.notes:
        lines += ["", "== 提示 =="]
        lines += [f"  ! {note}" for note in plan.notes]
    text = "\n".join(lines) + "\n"
    try:
        path.write_text(text, encoding="utf-8")
    except OSError:
        return ""
    return str(path)


def _append_history(record: LaunchedProcess) -> None:
    try:
        path = config.log_path("launches.jsonl")
        payload = record.to_dict()
        # 历史记录同样会被人翻出来看，命令行里的凭据一样要脱敏
        payload["commandLine"] = redact_command_line(payload.get("commandLine", ""))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_launches(limit: int = 50) -> list[dict]:
    path = config.LOG_DIR / "launches.jsonl"
    if not path.is_file():
        return []
    entries: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return entries[-limit:][::-1]


def launch(plan: LaunchPlan, profile: Profile, wait: bool = False) -> LaunchedProcess:
    """真正创建进程。抛 OSError 表示启动失败。"""
    if not plan.executable or not os.path.isfile(plan.executable):
        raise FileNotFoundError(f"目标不存在：{plan.executable or '(空)'}")

    # 最后一道闸：即使配置已经被污染成"目标=本程序"，也绝不再拉起自己
    if shortcuts.is_self_launcher(plan.executable):
        raise SelfLaunchRefused(
            f"目标指向本程序自身（{plan.executable}），拒绝启动以免无限自我拉起："
            f"{plan.name}"
        )

    flags = cmdline_mod.creation_flags(profile)

    stdio: dict = {}
    if not (flags & CREATE_NEW_CONSOLE) and profile.spec.family not in (
        Family.CLI,
        Family.NODE,
    ):
        # GUI 应用不要把我们的标准句柄带进去
        stdio = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }

    popen = subprocess.Popen(
        plan.command_line,
        cwd=plan.cwd,
        env=plan.env,
        creationflags=flags,
        close_fds=True,
        **stdio,
    )

    record = LaunchedProcess(
        profile_id=plan.profile_id,
        name=plan.name,
        pid=popen.pid,
        command_line=plan.command_line,
        cwd=plan.cwd,
        started_at=time.time(),
        levers=list(plan.levers),
        env_delta=dict(plan.env_delta),
        notes=list(plan.notes),
    )
    record.log_file = _write_launch_log(plan, record)
    _append_history(record)

    if wait:
        record.returncode = popen.wait()
    return record


def launch_profile(
    profile: Profile, endpoint: ProxyEndpoint, wait: bool = False
) -> tuple[LaunchPlan, LaunchedProcess]:
    plan = build_plan(profile, endpoint)
    record = launch(plan, profile, wait=wait)
    return plan, record
