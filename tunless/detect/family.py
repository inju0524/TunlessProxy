"""应用家族判定 —— 决定施加哪些 lever。

判定规则全部基于"目标 exe 所在目录里有什么文件"，规则来自对真实应用的实测：
  Electron : app.asar / icudtl.dat + resources.pak / v8_context_snapshot.bin / chrome_elf.dll
  WebView2 : WebView2Loader.dll
  Java     : jvm.dll / java.exe / 参数含 -jar
  Node     : node.exe / 参数指向 .js
  CLI      : PE 子系统为 CUI，或文件名命中常见命令行工具
"""

from __future__ import annotations

import os
from pathlib import Path

from ..model import AppSpec, Family, Lever

ELECTRON_MARKERS = ("app.asar", "default_app.asar")
ELECTRON_MARKERS_ANY = (
    "v8_context_snapshot.bin",
    "chrome_elf.dll",
    "icudtl.dat",
    "libcef.dll",
    "resources.pak",
)
WEBVIEW2_MARKERS = ("WebView2Loader.dll",)

CLI_BASENAMES = {
    "git.exe", "git", "npm.cmd", "npm", "pnpm.cmd", "pnpm", "yarn.cmd", "yarn",
    "pip.exe", "pip3.exe", "python.exe", "pythonw.exe", "python3.exe",
    "curl.exe", "wget.exe", "ssh.exe", "scp.exe", "sftp.exe", "docker.exe",
    "cargo.exe", "go.exe", "kubectl.exe", "helm.exe", "gh.exe", "az.exe",
    "aws.exe", "terraform.exe", "mvn.cmd", "gradle.bat", "composer.bat",
    "nuget.exe", "dotnet.exe", "adb.exe", "ffmpeg.exe", "psql.exe", "mysql.exe",
    "node.exe", "deno.exe", "bun.exe", "ruby.exe", "gem.cmd", "php.exe",
    "pwsh.exe", "powershell.exe", "cmd.exe", "wsl.exe",
}

JAVA_BASENAMES = {"java.exe", "javaw.exe", "javac.exe"}


def _dir_markers(directory: str) -> set[str]:
    found: set[str] = set()
    if not directory or not os.path.isdir(directory):
        return found
    try:
        for entry in os.scandir(directory):
            if entry.is_file():
                found.add(entry.name.lower())
    except OSError:
        pass
    return found


def _has_webview2(directory: str, depth: int = 2) -> bool:
    """WebView2Loader.dll 有时在子目录里，浅层递归找一下。"""
    if not directory or not os.path.isdir(directory):
        return False
    base = Path(directory)
    for marker in WEBVIEW2_MARKERS:
        try:
            if (base / marker).is_file():
                return True
        except OSError:
            pass
    if depth <= 0:
        return False
    try:
        for child in base.iterdir():
            if child.is_dir() and _has_webview2(str(child), depth - 1):
                return True
    except OSError:
        pass
    return False


def classify(spec: AppSpec) -> AppSpec:
    """就地补全 spec.family 与 spec.family_evidence。"""
    if spec.family == Family.UWP:
        return spec

    target = spec.target or ""
    directory = os.path.dirname(target) if target else ""
    basename = os.path.basename(target).lower()
    args = spec.args or ""
    evidence: list[str] = []
    family = Family.UNKNOWN

    if basename in JAVA_BASENAMES or "-jar " in f" {args} " or args.strip().startswith("-jar"):
        family = Family.JAVA
        evidence.append(f"Java 特征：{basename or '-jar 参数'}")
        if os.path.isfile(os.path.join(directory, "jvm.dll")):
            evidence.append("同目录存在 jvm.dll")
    else:
        names = _dir_markers(directory)
        resources = os.path.join(directory, "resources")
        res_names = _dir_markers(resources)

        electron_hits = [m for m in ELECTRON_MARKERS if m in names or m in res_names]
        if not electron_hits:
            electron_hits = [m for m in ELECTRON_MARKERS_ANY if m in names]
        if electron_hits:
            family = Family.ELECTRON
            evidence.append("Chromium/Electron 特征文件：" + "、".join(electron_hits[:4]))

    if family == Family.UNKNOWN and _has_webview2(directory):
        family = Family.WEBVIEW2
        evidence.append("存在 WebView2Loader.dll")

    if family == Family.UNKNOWN and basename == "node.exe":
        family = Family.NODE
        evidence.append("目标为 node.exe")

    if family == Family.UNKNOWN and basename in CLI_BASENAMES:
        family = Family.CLI
        evidence.append(f"常见命令行工具：{basename}")

    if family == Family.UNKNOWN and spec.subsystem == "cui":
        family = Family.CLI
        evidence.append("PE 子系统为控制台程序")

    if family == Family.UNKNOWN and spec.subsystem == "gui":
        family = Family.NATIVE
        evidence.append("PE 子系统为 GUI，且无 Chromium/WebView2/Java 特征")

    if family == Family.UNKNOWN:
        family = Family.NATIVE if spec.subsystem != "cui" else Family.CLI
        evidence.append("无法识别家族，按原生应用处理")

    spec.family = family
    spec.family_evidence = evidence
    return spec


def default_levers(family: Family) -> dict[str, bool]:
    """按家族给出默认开启的 lever 组合。"""
    if family in (Family.ELECTRON, Family.WEBVIEW2):
        # Chromium 在 Windows 上不读代理环境变量，必须走命令行
        return {"env": True, "cmdline": True, "configFiles": False}
    if family == Family.JAVA:
        return {"env": True, "cmdline": False, "configFiles": False}
    if family in (Family.NODE, Family.CLI):
        return {"env": True, "cmdline": False, "configFiles": True}
    return {"env": False, "cmdline": False, "configFiles": False}


def lever_plan_text(family: Family, levers: dict[str, bool]) -> list[str]:
    """给 UI 用的"将使用的代理手段"清单。"""
    lines: list[str] = []
    if levers.get("env"):
        lines.append("L1 环境变量：HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY"
                     + ("（含 NODE_USE_ENV_PROXY=1）" if family == Family.NODE else ""))
        if family == Family.JAVA:
            lines.append("L1 JAVA_TOOL_OPTIONS：为 JVM 设置 http/https 代理与 nonProxyHosts")
    if levers.get("cmdline"):
        if family in (Family.ELECTRON, Family.WEBVIEW2):
            lines.append("L2 命令行：--proxy-server=http://<代理> --disable-quic")
        elif family == Family.JAVA:
            lines.append("L2 命令行：-Dhttp.proxyHost=...")
    if levers.get("configFiles"):
        lines.append("L3 配置文件指针：gitconfig / npmrc / pip.ini / .curlrc / wgetrc / docker / ssh_config"
                     "（写入本程序私有目录，不改你的真实配置）")
    if not lines:
        lines.append("不施加任何代理手段：该应用类型在「零注入」前提下无法按应用代理")
    return lines
