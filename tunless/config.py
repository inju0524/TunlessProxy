"""配置与路径管理。

**所有生成物都集中放在程序同级目录下的 `data\\`**，一个文件夹装齐、可删可拷：

    <TunlessProxy.exe 所在目录>\\data\\config.json        全部配置
    ...\\data\\icons\\<id>.png|.ico                       提取出来的图标
    ...\\data\\profiles\\<id>\\                           按应用生成的私有配置文件(L3)
    ...\\data\\backup\\lnk\\                              被接管快捷方式的原始备份
    ...\\data\\logs\\                                     启动日志、launches.jsonl、crash.log

源码运行时"程序目录"就是项目根目录（`tunless/` 的上一层）。
这样用户想删干净或整体导出，只需要处理这一个文件夹。

两个例外：

* **程序装在不可写的位置**（`C:\\Program Files\\...`、只读盘）时自动退回
  `%APPDATA%\\TunlessProxy`，并在 `--doctor` 与设置里说明 —— 否则程序会因为
  写不了配置而直接起不来。
* `TUNLESS_DATA_DIR` 环境变量可以强制指定数据目录（给验收脚本与"一份程序多份
  数据"的用法留的口子，正常使用不会用到）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from . import APP_NAME

# ---------------------------------------------------------------- 路径

def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Roaming"


def _localappdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Local"


def app_dir() -> Path:
    """程序所在目录：打包后是 exe 所在目录，源码模式是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_writable(directory: Path) -> bool:
    """真去写一个探针文件，而不是看权限位（Windows 上权限位不可靠）。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-probe-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _resolve_data_dir() -> tuple[Path, str]:
    override = os.environ.get("TUNLESS_DATA_DIR")
    if override:
        return Path(override).expanduser(), "env"
    portable = app_dir() / "data"
    if is_writable(portable):
        return portable, "portable"
    return _appdata() / APP_NAME, "appdata"


_RESOLVED_DATA_DIR, _RESOLVED_SOURCE = _resolve_data_dir()

DATA_DIR: Path = _RESOLVED_DATA_DIR
#: portable = 程序同级 data\；appdata = 不可写时退回；env = 环境变量指定
DATA_DIR_SOURCE: str = _RESOLVED_SOURCE

#: 保留旧名字：这些路径现在全部落在 DATA_DIR 里。
CONFIG_DIR: Path = DATA_DIR
CONFIG_FILE: Path = DATA_DIR / "config.json"
ICON_DIR: Path = DATA_DIR / "icons"
PROFILES_DIR: Path = DATA_DIR / "profiles"
BACKUP_DIR: Path = DATA_DIR / "backup"
LNK_BACKUP_DIR: Path = BACKUP_DIR / "lnk"
LOG_DIR: Path = DATA_DIR / "logs"

#: 开始菜单目录是系统的，不随数据目录走。
#: 0.1.8 起"自动生成的独立快捷方式"改放**桌面**，这个常量只剩两个用途：
#: 认出并清理历史版本留在开始菜单里的那一份，以及"接管原快捷方式"时确认路径。
START_MENU_DIR: Path = (
    _appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
)

# ---------------------------------------------------------------- 默认配置

DEFAULT_SETTINGS: dict[str, Any] = {
    "endpoint": {
        "host": "127.0.0.1",
        "mixedPort": 7897,
        "socksPort": 7898,
        "httpPort": 7899,
        "autoDetect": True,
        "manual": None,  # {"host":..,"port":..,"scheme":"http"|"socks5"}
    },
    "noProxyExtra": [],
    "defaultLevers": {"env": True, "cmdline": True, "configFiles": True},
    # 添加新应用时自动生成一份独立快捷方式（0.1.8 起放在桌面）。
    # **默认关闭**：桌面是用户自己的地盘，默认往上面放图标是种打扰 ——
    # 想要的话在设置里勾一次（或在 `--add` 时加 `--shortcut` 临时建这一次）。
    # 旧键名 `generateStartMenuShortcuts` 仍然读得到，见 shortcuts_enabled()。
    "generateShortcuts": False,
    "disableQuic": True,
    "forceRemoteDns": False,
    "logLevel": "info",
    "clashConfigPath": None,  # 留空则自动探测 Clash Verge Rev 配置
    # 界面偏好（4 套主题 + 轻量便携模式）。默认值以 theme_tokens.DEFAULT_THEME_ID
    # 为准，这里写同一份是为了让 config.json 里能直接看到这两个键。
    "theme": "aurora",
    "compactMode": False,
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "settings": DEFAULT_SETTINGS,
    "profiles": [],
}


# ---------------------------------------------------------------- 目录

_LEGACY_DIRS_READY = False
MIGRATION_NOTES: list[str] = []


def migrate_legacy_data() -> list[str]:
    """把旧版本散在 `%APPDATA%\\TunlessProxy` 与 `%LOCALAPPDATA%\\...\\logs` 里的
    数据搬进 `data\\`（每个进程只做一次，且只在新位置还没有配置时做）。

    刻意用**复制**而不是移动：用户确认新位置没问题之后，可以自己把旧目录删掉；
    反过来（挪走了才发现新位置不合适）就没法收拾了。
    """
    global _LEGACY_DIRS_READY
    if _LEGACY_DIRS_READY:
        return MIGRATION_NOTES
    _LEGACY_DIRS_READY = True

    if DATA_DIR_SOURCE != "portable" or CONFIG_FILE.exists():
        return MIGRATION_NOTES

    legacy = _appdata() / APP_NAME
    if not (legacy / "config.json").is_file():
        return MIGRATION_NOTES

    try:
        for name in ("config.json",):
            shutil.copy2(legacy / name, DATA_DIR / name)
        for name in ("icons", "profiles", "backup"):
            source = legacy / name
            if source.is_dir():
                shutil.copytree(source, DATA_DIR / name, dirs_exist_ok=True)
        legacy_logs = _localappdata() / APP_NAME / "logs"
        if legacy_logs.is_dir():
            shutil.copytree(legacy_logs, LOG_DIR, dirs_exist_ok=True)
        MIGRATION_NOTES.append(
            f"已把旧数据从 {legacy} 复制到 {DATA_DIR}（确认无误后旧目录可自行删除）"
        )
    except OSError as exc:
        MIGRATION_NOTES.append(f"旧数据迁移失败：{type(exc).__name__}: {exc}")
    return MIGRATION_NOTES


def ensure_dirs() -> None:
    # 注意：这里**不**再预建 START_MENU_DIR —— 0.1.8 起快捷方式生成到桌面，
    # 再建那个空文件夹只会让开始菜单里一直留着一个用不到的空目录。
    for d in (CONFIG_DIR, ICON_DIR, PROFILES_DIR, LNK_BACKUP_DIR, LOG_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 单个目录失败不应阻断程序启动
            pass
    migrate_legacy_data()


def profile_dir(profile_id: str) -> Path:
    d = PROFILES_DIR / profile_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def icon_path(profile_id: str) -> Path:
    return ICON_DIR / f"{profile_id}.png"


# ---------------------------------------------------------------- 读写

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """把 override 合并进 base 的副本；dict 递归合并，其余整体替换。"""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict[str, Any]:
    """读取配置；文件缺失/损坏时返回默认值（损坏文件先备份）。"""
    ensure_dirs()
    if not CONFIG_FILE.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("配置根节点不是对象")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        broken = CONFIG_FILE.with_suffix(f".broken-{int(time.time())}.json")
        try:
            shutil.copy2(CONFIG_FILE, broken)
        except OSError:
            pass
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["_loadError"] = f"{type(exc).__name__}: {exc}"
        return cfg

    merged = _deep_merge(DEFAULT_CONFIG, data)
    merged["version"] = DEFAULT_CONFIG["version"]
    if not isinstance(merged.get("profiles"), list):
        merged["profiles"] = []
    return merged


def save(cfg: dict[str, Any]) -> None:
    """原子写入配置（先写临时文件再 os.replace）。

    临时文件名带上 pid：GUI 和快捷方式拉起的 `--run` 是两个进程，都会写这份配置，
    共用一个 `config.json.tmp` 时后写的那个 `os.replace` 会撞上前一个已经替换掉的
    临时文件（FileNotFoundError，CLI 直接 traceback）。
    命名唯一之后最坏也只是"后写的赢"，不会抛异常。
    """
    ensure_dirs()
    payload = {k: v for k, v in cfg.items() if not k.startswith("_")}
    # 兜底：payload 至少要带上版本号与 profiles 列表，免得某一处漏了键就写出
    # 一份"没有 version / 没有 profiles"的残配置（这类文件让后续判断全乱套）。
    payload.setdefault("version", DEFAULT_CONFIG["version"])
    if not isinstance(payload.get("profiles"), list):
        payload["profiles"] = []

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    tmp = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else load()
    return _deep_merge(DEFAULT_SETTINGS, cfg.get("settings") or {})


def find_profile(cfg: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    for prof in cfg.get("profiles") or []:
        if prof.get("id") == profile_id:
            return prof
    return None


def upsert_profile(cfg: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    profiles = cfg.setdefault("profiles", [])
    for idx, existing in enumerate(profiles):
        if existing.get("id") == profile.get("id"):
            profiles[idx] = profile
            return profile
    profiles.append(profile)
    return profile


def remove_profile(cfg: dict[str, Any], profile_id: str) -> bool:
    profiles = cfg.setdefault("profiles", [])
    for idx, existing in enumerate(profiles):
        if existing.get("id") == profile_id:
            del profiles[idx]
            return True
    return False


def log_path(name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / name


def shortcuts_enabled(settings: dict[str, Any] | None) -> bool:
    """添加新应用时是否自动生成独立快捷方式（**默认关闭**）。

    兼容旧键名：0.1.8 之前快捷方式生成在开始菜单里，键叫
    `generateStartMenuShortcuts`；用户配置里可能还留着它，所以读不到新键就回落到旧键
    （而不是直接当成新默认值 —— 那样会把用户"开着/关着"的选择悄悄改掉）。
    两个键都没有时才用默认值：关闭。
    """
    settings = settings or {}
    if "generateShortcuts" in settings:
        return bool(settings["generateShortcuts"])
    return bool(settings.get("generateStartMenuShortcuts", False))
