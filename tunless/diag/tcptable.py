"""按 PID 枚举 TCP 连接（iphlpapi.GetExtendedTcpTable）。

不需要管理员权限，也不会对目标进程做任何事 —— 纯读取系统连接表。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import socket
import struct
from dataclasses import dataclass

AF_INET = 2
AF_INET6 = 23
TCP_TABLE_OWNER_PID_ALL = 5
ERROR_INSUFFICIENT_BUFFER = 122

_IPHLPAPI = ctypes.WinDLL("iphlpapi")

# MIB_TCP_STATE
STATE_NAMES = {
    1: "CLOSED", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RCVD", 5: "ESTABLISHED",
    6: "FIN_WAIT1", 7: "FIN_WAIT2", 8: "CLOSE_WAIT", 9: "CLOSING",
    10: "LAST_ACK", 11: "TIME_WAIT", 12: "DELETE_TCB",
}


class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("state", wt.DWORD), ("localAddr", wt.DWORD), ("localPort", wt.DWORD),
        ("remoteAddr", wt.DWORD), ("remotePort", wt.DWORD), ("owningPid", wt.DWORD),
    ]


class _MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("localAddr", ctypes.c_ubyte * 16), ("localScopeId", wt.DWORD),
        ("localPort", wt.DWORD),
        ("remoteAddr", ctypes.c_ubyte * 16), ("remoteScopeId", wt.DWORD),
        ("remotePort", wt.DWORD),
        ("state", wt.DWORD), ("owningPid", wt.DWORD),
    ]


@dataclass
class Connection:
    pid: int
    family: str  # ipv4 | ipv6
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    state: str

    @property
    def remote(self) -> str:
        return f"{self.remote_ip}:{self.remote_port}"

    def to_dict(self) -> dict:
        return {
            "pid": self.pid, "family": self.family, "state": self.state,
            "local": f"{self.local_ip}:{self.local_port}", "remote": self.remote,
            "remoteIp": self.remote_ip, "remotePort": self.remote_port,
        }


def _ipv4(value: int) -> str:
    return socket.inet_ntoa(struct.pack("<I", value & 0xFFFFFFFF))


def _port(value: int) -> int:
    return socket.ntohs(value & 0xFFFF)


def _query(family: int, row_type, buffer_offset: int) -> list[Connection]:
    size = wt.DWORD(0)
    ret = _IPHLPAPI.GetExtendedTcpTable(
        None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if ret not in (0, ERROR_INSUFFICIENT_BUFFER) or size.value == 0:
        return []

    buffer = ctypes.create_string_buffer(size.value)
    ret = _IPHLPAPI.GetExtendedTcpTable(
        buffer, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if ret != 0:
        return []

    count = ctypes.cast(buffer, ctypes.POINTER(wt.DWORD)).contents.value
    rows = (row_type * count).from_buffer(buffer, buffer_offset)
    out: list[Connection] = []

    for row in rows:
        if family == AF_INET:
            out.append(Connection(
                pid=int(row.owningPid), family="ipv4",
                local_ip=_ipv4(row.localAddr), local_port=_port(row.localPort),
                remote_ip=_ipv4(row.remoteAddr), remote_port=_port(row.remotePort),
                state=STATE_NAMES.get(int(row.state), str(row.state)),
            ))
        else:
            out.append(Connection(
                pid=int(row.owningPid), family="ipv6",
                local_ip=socket.inet_ntop(socket.AF_INET6, bytes(row.localAddr)),
                local_port=_port(row.localPort),
                remote_ip=socket.inet_ntop(socket.AF_INET6, bytes(row.remoteAddr)),
                remote_port=_port(row.remotePort),
                state=STATE_NAMES.get(int(row.state), str(row.state)),
            ))
    return out


def all_connections() -> list[Connection]:
    """全部 TCP 连接（含 pid=0 的系统连接，调用方自行过滤）。"""
    return _query(AF_INET, _MIB_TCPROW_OWNER_PID, 4) + _query(
        AF_INET6, _MIB_TCP6ROW_OWNER_PID, 4
    )


def connections_for_pids(pids: set[int]) -> list[Connection]:
    if not pids:
        return []
    return [conn for conn in all_connections() if conn.pid in pids]


# ---------------------------------------------------------------- 分类

def is_loopback(ip: str) -> bool:
    return ip.startswith("127.") or ip in ("::1", "0.0.0.0", "::")


def is_private(ip: str) -> bool:
    if is_loopback(ip):
        return True
    if ":" in ip:
        lowered = ip.lower()
        return lowered.startswith("fe80") or lowered.startswith("fc") or lowered.startswith("fd")
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10 or a == 127 or a == 0:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    return False


def classify(conn: Connection, proxy_host: str, proxy_port: int) -> str:
    """via_proxy | direct_public | local"""
    if conn.remote_port == proxy_port and (
        is_loopback(conn.remote_ip) or conn.remote_ip == proxy_host
    ):
        return "via_proxy"
    if is_private(conn.remote_ip):
        return "local"
    return "direct_public"
