"""进程树与进程名（Toolhelp32 快照，不依赖 psutil）。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str


def snapshot() -> dict[int, ProcessInfo]:
    """一次快照拿到全部进程的 pid/ppid/名字。"""
    result: dict[int, ProcessInfo] = {}
    handle = _KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if handle == INVALID_HANDLE_VALUE or not handle:
        return result

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        if not _KERNEL32.Process32FirstW(handle, ctypes.byref(entry)):
            return result
        while True:
            result[int(entry.th32ProcessID)] = ProcessInfo(
                pid=int(entry.th32ProcessID),
                ppid=int(entry.th32ParentProcessID),
                name=str(entry.szExeFile),
            )
            if not _KERNEL32.Process32NextW(handle, ctypes.byref(entry)):
                break
    finally:
        _KERNEL32.CloseHandle(handle)
    return result


def descendants(root_pid: int, processes: dict[int, ProcessInfo] | None = None) -> set[int]:
    """root_pid 及其全部后代（含自身）。"""
    procs = processes if processes is not None else snapshot()
    children: dict[int, list[int]] = {}
    for info in procs.values():
        children.setdefault(info.ppid, []).append(info.pid)

    found: set[int] = set()
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.add(pid)
        stack.extend(children.get(pid, []))
    return found


def name_of(pid: int, processes: dict[int, ProcessInfo] | None = None) -> str:
    procs = processes if processes is not None else snapshot()
    info = procs.get(pid)
    return info.name if info else ""


def describe(pids: set[int], processes: dict[int, ProcessInfo] | None = None) -> list[str]:
    procs = processes if processes is not None else snapshot()
    return sorted({procs[pid].name for pid in pids if pid in procs})


def is_alive(pid: int, processes: dict[int, ProcessInfo] | None = None) -> bool:
    procs = processes if processes is not None else snapshot()
    return pid in procs
