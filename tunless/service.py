"""服务层：CLI 和 GUI 共用同一套动作，避免两处逻辑漂移。"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import config
from .detect import endpoint as endpoint_mod
from .detect import family as family_mod
from .detect import icon as icon_mod
from .detect import lnk, peinfo
from .launch import configfiles, proc, shortcuts
from .model import Family, LaunchPlan, Profile, ProxyEndpoint


# ---------------------------------------------------------------- 端点

# 探测端点要读文件 + 逐个端口探活，一次动作里往往被调好几遍（启动、诊断、
# 状态栏刷新）。给一个很短的缓存，既省时间又避免状态栏显示与实际不一致。
_ENDPOINT_CACHE: tuple[float, str, ProxyEndpoint] | None = None
_ENDPOINT_TTL = 2.0


def _endpoint_key(cfg: dict[str, Any]) -> str:
    return json.dumps(config.settings(cfg).get("endpoint"), sort_keys=True, default=str)


def current_endpoint(cfg: dict[str, Any], use_cache: bool = True) -> ProxyEndpoint:
    global _ENDPOINT_CACHE

    key = _endpoint_key(cfg)
    now = time.time()
    if (
        use_cache
        and _ENDPOINT_CACHE is not None
        and _ENDPOINT_CACHE[1] == key
        and now - _ENDPOINT_CACHE[0] < _ENDPOINT_TTL
    ):
        return _ENDPOINT_CACHE[2]

    settings = config.settings(cfg)
    manual = settings.get("endpoint", {}).get("manual")
    auto = settings.get("endpoint", {}).get("autoDetect", True)
    if not auto and manual:
        endpoint = ProxyEndpoint.from_dict({**manual, "source": "manual"})
    else:
        endpoint = endpoint_mod.detect(
            clash_config_path=settings.get("clashConfigPath"),
            manual=manual if not auto else None,
        )

    _ENDPOINT_CACHE = (now, key, endpoint)
    return endpoint


def test_endpoint(endpoint: ProxyEndpoint) -> dict[str, Any]:
    return endpoint_mod.test_connectivity(endpoint)


# ---------------------------------------------------------------- 配置

def load_config() -> dict[str, Any]:
    return config.load()


def save_config(cfg: dict[str, Any]) -> None:
    config.save(cfg)


def list_profiles(cfg: dict[str, Any]) -> list[Profile]:
    return [Profile.from_dict(item) for item in (cfg.get("profiles") or [])]


def get_profile(cfg: dict[str, Any], profile_id: str) -> Profile | None:
    raw = config.find_profile(cfg, profile_id)
    return Profile.from_dict(raw) if raw else None


def save_profile(cfg: dict[str, Any], profile: Profile) -> None:
    config.upsert_profile(cfg, profile.to_dict())
    config.save(cfg)


def prune_profile_dirs(cfg: dict[str, Any], force: bool = False) -> int:
    """删掉没有对应配置的 `profiles/<id>/` 目录和孤儿图标。

    这些目录是 `build_plan` 顺手建的（L3 配置要落盘），一旦某个 profile 没被
    保存下来（测试、添加失败、临时 profile），目录就永远留在那儿。

    **配置读失败时必须直接返回**：`config.load()` 遇到损坏文件会返回一份
    profiles 为空的默认配置，此时 keep 集合只剩 `proxy-shell`，照删就会把用户
    所有应用配置的目录和图标一次性清空 —— 那不是"清理无主数据"，是销毁数据。

    **配置里一个应用都没有时也不删**（除非显式 force）：正常用户不会"一个应用
    都没有、磁盘上却堆着一堆目录和图标"，这种组合更像配置被写坏了。真的要清，
    走 `--repair`（force=True）——那是用户明确要求的动作。
    """
    if cfg.get("_loadError"):
        return 0

    known = {profile.id for profile in list_profiles(cfg)}
    if not known and not force:
        return 0

    keep = known | {SHELL_PROFILE_ID}
    removed = 0

    if config.PROFILES_DIR.is_dir():
        for entry in config.PROFILES_DIR.iterdir():
            if entry.is_dir() and entry.name not in keep:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1

    if config.ICON_DIR.is_dir():
        for entry in config.ICON_DIR.iterdir():
            if entry.is_file() and entry.stem not in keep:
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def delete_profile(cfg: dict[str, Any], profile_id: str) -> None:
    profile = get_profile(cfg, profile_id)
    if profile is not None:
        # 被接管的那个文件要先还原成用户自己的图标；还原之后它就"还给用户"了，
        # 而它可能正好躺在生成位置上（比如桌面图标被接管）—— 所以这里记下路径，
        # 后面的清理必须绕开它，否则等于刚还原完又删掉。
        adopted = profile.adopted_shortcut
        try:
            shortcuts.restore_adopted(profile)
        except Exception:
            pass
        shortcuts.remove_shortcut(profile, keep=adopted)
    configfiles.clean_profile_dir(profile_id)
    for suffix in (".png", ".ico"):
        icon = config.icon_path(profile_id).with_suffix(suffix)
        if icon.is_file():
            try:
                icon.unlink()
            except OSError:
                pass
    config.remove_profile(cfg, profile_id)
    config.save(cfg)


# ---------------------------------------------------------------- 新建/刷新

def _display_name(spec, source_path: str) -> str:
    """优先用文件名：exe 的 FileDescription 有时是 "The curl executable" 这种废话。"""
    stem = Path(source_path).stem
    if stem:
        return stem
    if spec.target:
        stem = Path(spec.target).stem
        if stem:
            return stem
    return spec.description or "未命名"


def build_profile(path: str, name: str | None = None) -> Profile:
    """从拖入的路径造一个 Profile（解析 + 家族判定 + 默认 lever）。"""
    spec = lnk.resolve(path)
    info = peinfo.analyze(spec.target)
    spec.arch = info["arch"]
    spec.subsystem = info["subsystem"]
    spec.dotnet = bool(info["dotnet"])
    spec.requires_elevation = bool(info["requires_elevation"])
    if not spec.description and info["description"]:
        spec.description = str(info["description"])
    family_mod.classify(spec)

    profile = Profile(
        name=name or _display_name(spec, path),
        source_path=path,
        spec=spec,
        created_at=time.time(),
    )
    profile.levers = family_mod.default_levers(spec.family)
    return profile


def refresh_profile(profile: Profile) -> Profile:
    """重新解析目标（应用升级换目录、或修历史数据时用）。

    保留用户自己改过的东西：lever、额外参数、环境变量、开关……
    目标没变时连 args/workdir 也保留 —— 否则「重新解析」会把用户手填的
    启动参数悄悄冲掉。

    **被接管的快捷方式不能重新解析**：接管是把这个 .lnk 原地改成指向本程序
    （`--run <id>`），再拿它当"应用自身"解析出来的目标就是启动器自己。保存下去
    以后启动该应用 = 用同一个 id 再拉起启动器 → 子进程读同一份配置继续拉起，
    变成无限自我拉起链（每级还会写启动日志与 L3 配置）。原目标一直存在
    `profile.spec` 里，接管状态下保持不动才是对的。
    """
    if profile.adopted_shortcut:
        return profile

    if not profile.source_path or not os.path.exists(profile.source_path):
        return profile

    fresh = build_profile(profile.source_path, profile.name)
    if fresh.spec.target.lower() == (profile.spec.target or "").lower():
        fresh.spec.args = profile.spec.args
        fresh.spec.workdir = profile.spec.workdir

    fresh.id = profile.id
    fresh.created_at = profile.created_at
    fresh.levers = dict(profile.levers)
    fresh.cmdline_extra = list(profile.cmdline_extra)
    fresh.env_extra = dict(profile.env_extra)
    fresh.no_proxy_extra = list(profile.no_proxy_extra)
    fresh.disable_quic = profile.disable_quic
    fresh.force_remote_dns = profile.force_remote_dns
    fresh.console_mode = profile.console_mode
    fresh.adopt_shortcut = profile.adopt_shortcut
    fresh.adopted_shortcut = profile.adopted_shortcut
    fresh.launch_count = profile.launch_count
    fresh.last_launched_at = profile.last_launched_at
    fresh.note = profile.note
    return fresh


def repair_all(cfg: dict[str, Any]) -> dict[str, Any]:
    """把已有配置全部重解析一遍并重建图标/快捷方式。

    升级后修复历史数据用：早期版本把 .lnk 的 `IconLocation=",0"` 当成文件路径，
    导致图标缓存全空、快捷方式图标是坏的。
    """
    fixed: list[str] = []
    errors: list[str] = []
    want_shortcut = config.shortcuts_enabled(config.settings(cfg))

    for profile in list_profiles(cfg):
        try:
            refreshed = refresh_profile(profile)
            profile.spec = refreshed.spec
            extract_icon(profile)
            if want_shortcut:
                try:
                    shortcuts.create_shortcut(profile)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{profile.name}（快捷方式）：{exc}")
            save_profile(cfg, profile)
            fixed.append(profile.name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{profile.name}：{type(exc).__name__}: {exc}")

    return {
        "repaired": fixed,
        "errors": errors,
        # `--repair` 是用户明确要求的清理动作，这里才允许 force
        "pruned": prune_profile_dirs(cfg, force=True),
    }


def extract_icon(profile: Profile) -> bool:
    """取图标：PNG 给界面用，ICO 给快捷方式用（Explorer 不认 PNG 图标）。

    icon_source 不可用（空、`<路径不存在>,0` 这类）时退回目标程序自己的图标。
    """
    png = config.icon_path(profile.id)
    candidates = [profile.spec.icon_source, profile.spec.target, profile.source_path]
    for source in candidates:
        if not source:
            continue
        path_part = source.rsplit(",", 1)[0].strip().strip('"')
        if path_part and not os.path.isfile(path_part):
            continue
        if icon_mod.extract_icon(source, png, 48):
            icon_mod.png_to_ico(png, png.with_suffix(".ico"))
            return True
    return False


def add_profile(
    cfg: dict[str, Any],
    path: str,
    name: str | None = None,
    create_shortcut: bool | None = None,
) -> Profile:
    """拖入一个路径：解析、存盘、取图标，必要时建快捷方式。

    create_shortcut=None 表示跟随设置；显式 True/False 用于命令行的一次性开关
    （绝不能把它写回设置，否则 `--add --no-shortcut` 会永久改掉用户配置）。
    """
    profile = build_profile(path, name)
    extract_icon(profile)

    want_shortcut = (
        config.shortcuts_enabled(config.settings(cfg))
        if create_shortcut is None
        else create_shortcut
    )
    if want_shortcut:
        try:
            shortcuts.create_shortcut(profile)
        except Exception as exc:  # noqa: BLE001 - 建快捷方式失败不该阻断添加
            try:
                log = config.log_path("shortcut-errors.log")
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                                 f"{profile.name}: {type(exc).__name__}: {exc}\n")
            except OSError:
                pass
    save_profile(cfg, profile)
    return profile


# ---------------------------------------------------------------- 启动

def make_plan(cfg: dict[str, Any], profile: Profile) -> LaunchPlan:
    return proc.build_plan(profile, current_endpoint(cfg))


def run_profile(
    cfg: dict[str, Any], profile_id: str, wait: bool = False
) -> tuple[LaunchPlan, proc.LaunchedProcess]:
    profile = get_profile(cfg, profile_id)
    if profile is None:
        raise KeyError(f"找不到应用配置：{profile_id}")

    plan = make_plan(cfg, profile)
    record = proc.launch(plan, profile, wait=wait)

    profile.launch_count += 1
    profile.last_launched_at = time.time()
    save_profile(cfg, profile)
    return plan, record


SHELL_PROFILE_ID = "proxy-shell"


def proxy_shell(cfg: dict[str, Any], cwd: str | None = None) -> proc.LaunchedProcess:
    """开一个已经带好代理环境的终端。

    用固定的 profile id：`configfiles.write_all` 会往 profiles/<id>/ 写配置，
    每次随机 id 的话这些目录会一直堆积。
    """
    from .model import AppSpec

    endpoint = current_endpoint(cfg)
    shell = os.environ.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
    spec = AppSpec(
        target=shell,
        workdir=cwd or os.environ.get("USERPROFILE", ""),
        subsystem="cui",
        source_kind="exe",
        source_path=shell,
    )
    family_mod.classify(spec)
    profile = Profile(id=SHELL_PROFILE_ID, name="代理终端", source_path=shell, spec=spec)
    profile.levers = {"env": True, "cmdline": False, "configFiles": True}
    profile.console_mode = "new"
    plan = proc.build_plan(profile, endpoint)
    return proc.launch(plan, profile)


def active_process_for_profile(profile_id: str) -> dict | None:
    """返回该应用当前是否还在运行中（最新一次启动且 PID 存活）。"""
    from .diag import proctree

    launches = proc.recent_launches(100)
    matched = [item for item in launches if item.get("profileId") == profile_id]
    if not matched:
        return None
    latest = matched[0]
    pid = int(latest.get("pid", 0))
    if pid and proctree.is_alive(pid):
        return latest
    return None


def recent_launches_for_profile(profile_id: str, limit: int = 5) -> list[dict]:
    """返回指定应用最近启动历史记录。"""
    launches = proc.recent_launches(100)
    return [item for item in launches if item.get("profileId") == profile_id][:limit]
