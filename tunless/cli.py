"""命令行入口。

GUI 之外的所有能力都在这儿，快捷方式生成的命令就是 `tunless --run <id>`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import (
    APP_NAME, __copyright__, __license_label__, __url__, __version__, config, service
)
from .diag import proctree, verdict as verdict_mod
from .diag.clashpipe import ClashApi
from .launch import proc, shortcuts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tunless",
        description="TunlessProxy —— 免 TUN、零注入的按应用代理启动器",
    )
    parser.add_argument(
        "--version",
        action="version",
        # 作者与许可跟「关于」页同源（tunless/__init__.py），命令行里也看得到
        version=f"{APP_NAME} {__version__}\n{__license_label__} · {__copyright__} · {__url__}",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--gui", action="store_true", help="打开图形界面（默认）")
    group.add_argument("--run", metavar="ID", help="用代理启动指定应用配置")
    group.add_argument("--add", action="store_true", help="把后面给的路径加入配置")
    group.add_argument("--remove", metavar="ID", help="删除一个应用配置")
    group.add_argument("--list", action="store_true", help="列出全部应用配置")
    # nargs="?" 是为了让 `--diagnose --pid 1234` 也能用（只给 PID 时不必再写 ID）
    group.add_argument(
        "--diagnose", nargs="?", const="", metavar="ID",
        help="诊断某个应用配置最近一次启动；配合 --pid 可直接诊断进程",
    )
    group.add_argument("--shell", action="store_true", help="打开已带代理环境的终端")
    group.add_argument("--test", action="store_true", help="测试代理端点连通性")
    group.add_argument("--doctor", action="store_true", help="打印环境自检信息")
    group.add_argument(
        "--repair", action="store_true",
        help="重新解析全部配置并重建图标/快捷方式（升级后修复历史数据）",
    )

    # 位置参数用于 --add；这样 `--add a.lnk b.lnk --no-shortcut` 和
    # `--add --no-shortcut a.lnk b.lnk` 两种顺序都能用。
    parser.add_argument("paths", nargs="*", metavar="PATH", help="要加入配置的快捷方式/exe")

    parser.add_argument("--wait", action="store_true", help="等待子进程结束并透传退出码")
    parser.add_argument("--pid", type=int, help="配合 --diagnose，直接诊断某个 PID")
    parser.add_argument("--shortcut", action="store_true", help="--add 时这次也建独立快捷方式（默认关闭，设置里可长期开启）")
    parser.add_argument("--no-shortcut", action="store_true", help="--add 时不创建独立快捷方式（默认就是关的，显式关一次）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本处理）")
    return parser


# ---------------------------------------------------------------- 各子命令

def cmd_list(cfg: dict, as_json: bool) -> int:
    profiles = service.list_profiles(cfg)
    if as_json:
        print(json.dumps([p.to_dict() for p in profiles], ensure_ascii=False, indent=2))
        return 0
    if not profiles:
        print("还没有任何应用配置。把快捷方式拖进 GUI，或运行：tunless --add <快捷方式路径>")
        return 0
    print(f"{'ID':10}  {'家族':<18} {'启动次数':>6}  名称")
    for profile in profiles:
        print(
            f"{profile.id[:8]:10}  {profile.spec.family.label:<18} "
            f"{profile.launch_count:>6}  {profile.name}"
        )
        print(f"{'':10}  -> {profile.spec.target}")
    return 0


def cmd_add(cfg: dict, paths: list[str], no_shortcut: bool, want_shortcut: bool = False) -> int:
    """添加应用配置。

    快捷方式：`--shortcut` 明确要，`--no-shortcut` 明确不要（两者同给时以后者为准），
    都不给就**跟随设置**（该设置默认关闭，见 `config.shortcuts_enabled`）。
    这三个分支都不写回设置 —— 命令行的一次性开关不该改用户的长期偏好。
    """
    if no_shortcut:
        create: bool | None = False
    elif want_shortcut:
        create = True
    else:
        create = None

    failures = 0
    for raw in paths:
        path = os.path.abspath(raw)
        if not os.path.exists(path):
            print(f"跳过（不存在）：{path}", file=sys.stderr)
            failures += 1
            continue
        try:
            profile = service.add_profile(cfg, path, create_shortcut=create)
        except Exception as exc:  # noqa: BLE001
            print(f"失败：{path} -> {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"已添加：{profile.name}")
        print(f"  家族    : {profile.spec.family.label}")
        print(f"  目标    : {profile.spec.target}")
        print(f"  依据    : {'；'.join(profile.spec.family_evidence) or '无'}")
        print(f"  代理手段: {', '.join(k for k, v in profile.levers.items() if v) or '无'}")
        print(f"  ID      : {profile.id}")
        if create is not False:
            shortcut = shortcuts.generated_path(profile)
            if shortcut.is_file():
                print(f"  快捷方式: {shortcut}")
    return 1 if failures else 0


def cmd_remove(cfg: dict, profile_id: str) -> int:
    profile = service.get_profile(cfg, profile_id)
    if profile is None:
        # 允许用 ID 前缀
        for candidate in service.list_profiles(cfg):
            if candidate.id.startswith(profile_id):
                profile = candidate
                break
    if profile is None:
        print(f"找不到配置：{profile_id}", file=sys.stderr)
        return 1
    service.delete_profile(cfg, profile.id)
    print(f"已删除：{profile.name}")
    return 0


def _log_error(text: str) -> None:
    """pythonw 下没有控制台，出错信息也要落到文件里。"""
    try:
        path = config.log_path("run-errors.log")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


def cmd_run(cfg: dict, profile_id: str, wait: bool) -> int:
    profile = service.get_profile(cfg, profile_id)
    if profile is None:
        for candidate in service.list_profiles(cfg):
            if candidate.id.startswith(profile_id):
                profile = candidate
                break
    if profile is None:
        message = f"找不到配置：{profile_id}"
        print(message, file=sys.stderr)
        _log_error(message)
        return 1

    plan = service.make_plan(cfg, profile)
    for note in plan.notes:
        print(f"提示：{note}", file=sys.stderr)
        _log_error(f"{profile.name}: {note}")

    try:
        record = proc.launch(plan, profile, wait=wait)
    except (OSError, proc.SelfLaunchRefused) as exc:
        message = f"启动失败：{profile.name} -> {exc}"
        print(message, file=sys.stderr)
        _log_error(message)
        return 1

    profile.launch_count += 1
    profile.last_launched_at = record.started_at
    service.save_profile(cfg, profile)

    from . import app as app_module

    app_module.notify_running_instance(f"launched:{profile.id}:{record.pid}")

    if wait:
        return int(record.returncode or 0)
    print(f"已启动 {profile.name}（PID {record.pid}）")
    if record.log_file:
        print(f"日志：{record.log_file}")
    return 0


def cmd_diagnose(cfg: dict, profile_id: str | None, pid: int | None, as_json: bool) -> int:
    endpoint = service.current_endpoint(cfg)

    if pid is None:
        if not profile_id:
            print("需要 --diagnose <ID> 或 --pid <PID>", file=sys.stderr)
            return 1
        profile = service.get_profile(cfg, profile_id)
        if profile is None:
            for candidate in service.list_profiles(cfg):
                if candidate.id.startswith(profile_id):
                    profile = candidate
                    break
        if profile is None:
            print(f"找不到配置：{profile_id}", file=sys.stderr)
            return 1
        history = [
            item for item in proc.recent_launches(200)
            if item.get("profileId") == profile.id
        ]
        if not history:
            print(f"{profile.name} 还没有启动记录", file=sys.stderr)
            return 1
        pid = int(history[0]["pid"])

    clash = ClashApi()
    result = verdict_mod.diagnose(pid, endpoint, clash)
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"PID {result.root_pid}  进程：{', '.join(result.process_names) or '(已退出)'}")
    print(f"结论：{result.summary}")
    if result.hint:
        print(f"建议：{result.hint}")
    if result.via_proxy:
        print(f"\n经代理（{len(result.via_proxy)} 条）：")
        for item in result.via_proxy[:15]:
            print(f"  {item['process']:<28} {item['remote']:<24} {item['state']}")
    if result.direct_public:
        print(f"\n直连公网（{len(result.direct_public)} 条）：")
        for item in result.direct_public[:15]:
            print(f"  {item['process']:<28} {item['remote']:<24} {item['state']}")
    return 0


def cmd_shell(cfg: dict, cwd: str | None) -> int:
    record = service.proxy_shell(cfg, cwd)
    print(f"已打开代理终端（PID {record.pid}）")
    print(f"日志：{record.log_file}")
    return 0


def cmd_test(cfg: dict, as_json: bool) -> int:
    from .detect import endpoint as endpoint_mod

    endpoint = service.current_endpoint(cfg)
    result = service.test_endpoint(endpoint)
    if as_json:
        print(json.dumps({**result, "endpoint": endpoint.to_dict()}, ensure_ascii=False, indent=2))
        return 0
    def show(label: str, ok: bool, country, ip) -> str:
        if not ok:
            return f"{label}：失败"
        detail = "、".join(str(x) for x in (country, ip) if x) or "已取到回显"
        return f"{label}：成功（{detail}）"

    print(f"代理端点：{endpoint.host}:{endpoint.mixed_port}（来源：{endpoint.source}）")
    print(f"端口探活：{'通' if result['tcp_alive'] else '不通'}")
    print(show("经代理出网", result["proxy_ok"], result.get("proxy_country"), result.get("proxy_ip")))
    print(show("直连出网", result["direct_ok"], result.get("direct_country"), result.get("direct_ip")))
    print(f"结论：{endpoint_mod.verdict_text(result)}")
    return 0 if result["verdict"] == "ok" else 2


def cmd_repair(cfg: dict, as_json: bool) -> int:
    result = service.repair_all(cfg)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    if result["repaired"]:
        print(f"已修复 {len(result['repaired'])} 个配置：{'、'.join(result['repaired'])}")
    else:
        print("没有需要修复的配置")
    if result["pruned"]:
        print(f"顺带清理了 {result['pruned']} 项无主数据")
    for error in result["errors"]:
        print(f"失败：{error}", file=sys.stderr)
    return 1 if result["errors"] else 0


def cmd_doctor(cfg: dict, as_json: bool) -> int:
    from .detect import endpoint as endpoint_mod

    endpoint = service.current_endpoint(cfg)
    clash = ClashApi()
    info = {
        "version": __version__,
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "elevated": proc.is_elevated(),
        "dataDir": str(config.DATA_DIR),
        "dataDirSource": config.DATA_DIR_SOURCE,
        "migration": list(config.MIGRATION_NOTES),
        "configFile": str(config.CONFIG_FILE),
        "logDir": str(config.LOG_DIR),
        "profileCount": len(service.list_profiles(cfg)),
        "endpoint": endpoint.to_dict(),
        "clashConfig": endpoint_mod.clash_verge_config_file(),
        "clashPipe": {"available": clash.available, "pipe": clash.pipe_name, "error": clash.error},
        "systemProxy": endpoint_mod.read_system_proxy(),
        "portAlive": endpoint_mod.tcp_alive(endpoint.host, endpoint.mixed_port, timeout=0.6),
        "processes": len(proctree.snapshot()),
        "launcher": shortcuts.launcher_command(),
    }
    if as_json:
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        return 0
    for key, value in info.items():
        print(f"{key:16}: {value}")
    return 0


# ---------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config.ensure_dirs()
    cfg = service.load_config()

    # 显式命令优先：这样 `--list 某路径` 不会因为位置参数被当成 --add
    if args.remove:
        return cmd_remove(cfg, args.remove)
    if args.list:
        return cmd_list(cfg, args.json)
    if args.run:
        return cmd_run(cfg, args.run, args.wait)
    if args.diagnose is not None or args.pid:
        return cmd_diagnose(cfg, args.diagnose or None, args.pid, args.json)
    if args.shell:
        return cmd_shell(cfg, None)
    if args.test:
        return cmd_test(cfg, args.json)
    if args.doctor:
        return cmd_doctor(cfg, args.json)
    if args.repair:
        return cmd_repair(cfg, args.json)

    if args.add or args.paths:
        paths = list(args.paths)
        if not paths:
            print("--add 后面要跟上快捷方式或 exe 的路径", file=sys.stderr)
            return 1
        return cmd_add(cfg, paths, args.no_shortcut, args.shortcut)

    from .app import run_gui

    return run_gui(cfg)
