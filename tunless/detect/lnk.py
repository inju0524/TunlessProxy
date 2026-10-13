"""快捷方式 / 可执行文件解析。

支持：.lnk（含链式快捷方式）、.url、.exe、.bat/.cmd，以及 UWP 的
`explorer.exe shell:AppsFolder\\...` 形态（识别出来并标记为不支持按应用代理）。
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from ..model import AppSpec

MAX_LNK_DEPTH = 5

# 这些目标其实是"壳"，真正要启动的是参数里的东西
_SHELL_HOSTS = {"explorer.exe", "rundll32.exe"}


def _expand(value: str) -> str:
    if not value:
        return ""
    return os.path.expandvars(value.strip())


_COM_READY = threading.local()


def _com_init() -> None:
    """按线程初始化 COM，且**不**反初始化。

    刻意不调用 CoUninitialize：一旦在 COM 对象仍被引用时反初始化，pywin32 会在
    释放 IUnknown 时抛 "Win32 exception occurred releasing IUnknown"。进程退出时
    由系统回收该线程套间即可。
    """
    if getattr(_COM_READY, "done", False):
        return
    try:
        import pythoncom  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("需要 pywin32 才能解析 .lnk") from exc
    try:
        pythoncom.CoInitialize()
    except Exception:
        # 已经初始化过（RPC_E_CHANGED_MODE 等）也当作可用
        pass
    _COM_READY.done = True


def read_lnk(path: str) -> dict[str, str]:
    """读 .lnk 的字段。失败抛 OSError/RuntimeError。"""
    _com_init()
    import win32com.client  # type: ignore

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(os.path.abspath(path))
    info = {
        "target": _expand(str(shortcut.TargetPath or "")),
        "args": str(shortcut.Arguments or ""),
        "workdir": _expand(str(shortcut.WorkingDirectory or "")),
        "icon": _expand(str(shortcut.IconLocation or "")),
        "description": str(getattr(shortcut, "Description", "") or ""),
    }
    del shortcut, shell
    return info


def _normalize_icon(icon: str, target: str) -> str:
    """把 .lnk 的 IconLocation 归一化成"文件路径[,索引]"。

    大量真实快捷方式的 IconLocation 就是字面量 `,0` —— Windows 的约定是
    "路径为空 = 用目标程序自己的图标"。以前把它当成文件路径，导致图标提取
    永远失败、生成的快捷方式图标也是坏的。
    """
    text = (icon or "").strip()
    if not text:
        return target
    if "," in text:
        head, _, tail = text.rpartition(",")
        if not head.strip():
            tail = tail.strip()
            return f"{target},{tail}" if tail else target
    return text


def _read_url_file(path: str) -> dict[str, str]:
    """.url 是 INI 格式，取 URL= 一行。"""
    url = ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = Path(path).read_text(encoding="mbcs", errors="replace")
    for line in text.splitlines():
        if line.strip().lower().startswith("url="):
            url = line.split("=", 1)[1].strip()
            break
    return {"target": url, "args": "", "workdir": "", "icon": "", "description": ""}


def _is_uwp(target: str, args: str) -> bool:
    if "shell:AppsFolder" in args or "shell:appsFolder" in args:
        return True
    if os.path.basename(target).lower() in _SHELL_HOSTS and "shell:" in args:
        return True
    return False


def resolve(path: str) -> AppSpec:
    """把任意拖入的路径解析成 AppSpec。

    对 .lnk 会递归展开（限深 MAX_LNK_DEPTH），返回最终的可执行目标。
    """
    original = os.path.abspath(path)
    spec = AppSpec(source_path=original)
    current = original
    chain: list[str] = []

    for _ in range(MAX_LNK_DEPTH):
        suffix = Path(current).suffix.lower()
        if suffix == ".lnk":
            info = read_lnk(current)
            chain.append(current)
            target = info["target"]
            if not target:
                raise RuntimeError(
                    f"无法解析快捷方式的目标：{current}"
                    "（可能是 MSI 广告快捷方式，请改为直接选择 exe）"
                )
            if not spec.args:
                spec.args = info["args"]
            if not spec.workdir:
                spec.workdir = info["workdir"]
            if not spec.icon_source:
                spec.icon_source = _normalize_icon(info["icon"], target)
            if not spec.description:
                spec.description = info["description"]
            spec.source_kind = "lnk"
            current = target
            continue

        if suffix == ".url":
            info = _read_url_file(current)
            spec.source_kind = "url"
            spec.target = info["target"]
            spec.icon_source = info["icon"] or current
            spec.description = spec.description or info["description"]
            spec.family = _family_from_url(spec.target)
            break

        # 普通可执行 / 批处理
        spec.target = current
        spec.source_kind = "bat" if suffix in (".bat", ".cmd") else "exe"
        if not spec.icon_source:
            spec.icon_source = current
        break

    if not spec.target:
        raise RuntimeError(f"无法从 {original} 解析出可执行目标")

    if _is_uwp(spec.target, spec.args):
        from ..model import Family

        spec.family = Family.UWP
        spec.family_evidence = ["通过 explorer.exe shell:AppsFolder 启动，无法施加环境变量"]

    # 刻意不在这里兜底 workdir：命令行工具应该跑在用户目录而不是 exe 所在目录
    # （git/npm 在 C:\Program Files\Git\cmd 下跑没有任何意义）。由启动层按家族决定。
    spec.source_path = original
    if chain:
        spec.family_evidence = list(spec.family_evidence) + [f"快捷方式链 {len(chain)} 级"]
    return spec


def _family_from_url(url: str):
    from ..model import Family

    if re.match(r"^https?://", url, re.I):
        # 交给默认浏览器；浏览器本身不在我们的进程树里，无法按应用代理
        return Family.UWP
    return Family.UNKNOWN


def looks_like_shortcut(path: str) -> bool:
    return Path(path).suffix.lower() in (".lnk", ".url")


def is_supported_drop(path: str) -> bool:
    return Path(path).suffix.lower() in (".lnk", ".url", ".exe", ".bat", ".cmd", ".com")
