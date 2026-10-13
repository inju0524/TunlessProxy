"""把连接表 + 进程树 + Clash 侧证据汇总成一句人话结论。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model import ProxyEndpoint
from . import proctree, tcptable
from .clashpipe import ClashApi

ACTIVE_STATES = {"ESTABLISHED", "SYN_SENT"}


@dataclass
class Verdict:
    root_pid: int
    alive: bool = False
    process_names: list[str] = field(default_factory=list)
    via_proxy: list[dict] = field(default_factory=list)
    direct_public: list[dict] = field(default_factory=list)
    local: list[dict] = field(default_factory=list)
    clash_seen: list[str] = field(default_factory=list)
    status: str = "idle"  # ok | leak | idle | dead
    summary: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "rootPid": self.root_pid,
            "alive": self.alive,
            "processNames": self.process_names,
            "viaProxy": self.via_proxy,
            "directPublic": self.direct_public,
            "local": self.local,
            "clashSeen": self.clash_seen,
            "status": self.status,
            "summary": self.summary,
            "hint": self.hint,
        }


def diagnose(
    root_pid: int,
    endpoint: ProxyEndpoint,
    clash: ClashApi | None = None,
    include_inactive: bool = False,
) -> Verdict:
    processes = proctree.snapshot()
    verdict = Verdict(root_pid=root_pid)

    if root_pid not in processes:
        verdict.status = "dead"
        verdict.summary = f"进程 {root_pid} 已退出，无法诊断"
        return verdict

    verdict.alive = True
    pids = proctree.descendants(root_pid, processes)
    verdict.process_names = proctree.describe(pids, processes)

    for conn in tcptable.connections_for_pids(pids):
        if not include_inactive and conn.state not in ACTIVE_STATES:
            continue
        kind = tcptable.classify(conn, endpoint.host, endpoint.mixed_port)
        payload = conn.to_dict()
        payload["process"] = proctree.name_of(conn.pid, processes)
        if kind == "via_proxy":
            verdict.via_proxy.append(payload)
        elif kind == "direct_public":
            verdict.direct_public.append(payload)
        else:
            verdict.local.append(payload)

    if clash is not None and clash.available:
        try:
            counts = clash.by_process()
            verdict.clash_seen = sorted(
                name for name in counts if name in set(verdict.process_names)
            )
        except Exception:  # noqa: BLE001
            pass

    via = len(verdict.via_proxy)
    leak = len(verdict.direct_public)

    if via == 0 and leak == 0:
        verdict.status = "idle"
        verdict.summary = "当前没有活动连接，无法判断（让应用发一个网络请求再看）"
    elif leak == 0:
        verdict.status = "ok"
        verdict.summary = f"已生效：{via} 条连接经代理，没有发现直连公网"
    elif via > 0:
        verdict.status = "leak"
        verdict.summary = f"部分生效：{via} 条经代理，但有 {leak} 条直连公网"
        verdict.hint = "直连目标多为应用内置的更新/统计通道；若影响使用，可在该应用设置里启用系统代理"
    else:
        verdict.status = "leak"
        verdict.summary = f"未生效：{leak} 条连接全部直连公网"
        verdict.hint = (
            "该应用可能不认代理参数，或属于原生 WinHTTP/裸 WinSock 应用；"
            "可尝试在应用内设置代理为 127.0.0.1:7897"
        )

    return verdict


def status_color(status: str) -> str:
    return {
        "ok": "#2e9e5b",
        "leak": "#c9820a",
        "idle": "#6b7280",
        "dead": "#9ca3af",
    }.get(status, "#6b7280")
