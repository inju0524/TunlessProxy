"""L4 快捷方式：让"点原图标"也能走代理。

两种做法：
  * 生成：在**桌面**新建 `<名称>.lnk`，指向本程序 `--run <id>`；
    （0.1.8 起生成到桌面；开始菜单里由旧版本留下的那一份会被顺手清掉，
      前提是能确认它确实是本程序生成的 —— 见 `_is_our_shortcut`。）
  * 接管（默认关闭、可一键还原）：把**原快捷方式原地**换成指向本程序，
    这样开始菜单和任务栏固定项都会走代理。原文件先备份到数据目录的 `backup\\lnk\\`。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .. import config
from ..model import Profile

APP_ARGS_PREFIX = "--run"


WINDOWED_NAME = "TunlessProxy.exe"


def launcher_command() -> tuple[str, str, str]:
    """返回 (可执行文件, 参数前缀, 工作目录)。

    * 打包后：**优先用窗口化的那个 exe**（TunlessProxy.exe）。这样即使用户是从
      控制台版 `tunless.exe --add` 添加的应用，生成的快捷方式双击时也不会闪黑框。
    * 脚本模式：用 pythonw.exe 免得弹黑框。
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        windowed = exe.with_name(WINDOWED_NAME)
        if windowed.is_file():
            return str(windowed), "", str(windowed.parent)
        return str(exe), "", str(exe.parent)

    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.is_file():
        executable = pythonw
    root = Path(__file__).resolve().parents[2]
    return str(executable), "-m tunless", str(root)


def shortcut_name(profile: Profile) -> str:
    safe = "".join(ch for ch in profile.name if ch not in '<>:"/\\|?*').strip()
    return f"{safe or profile.id[:8]}.lnk"


def is_self_launcher(path: str | None) -> bool:
    """这个路径是不是本程序自己的启动器？

    用来拦住"应用配置的目标指向了我们自己"这种情况 —— 真的发生的话，
    `--run <id>` 会再拉起一个同 id 的启动器，子进程读同一份配置继续拉起，
    变成无限自我拉起链（每条都是一次真实进程 + 一份日志 + 一份 L3 配置）。
    典型来源是被接管的快捷方式被当成"应用自身"重新解析（见 service.refresh_profile）。
    """
    if not path:
        return False
    try:
        candidate = Path(path).resolve()
    except OSError:
        return False

    if getattr(sys, "frozen", False):
        launchers = {Path(sys.executable).resolve()}
        launchers.add((Path(sys.executable).parent / WINDOWED_NAME).resolve())
        return candidate in launchers

    # 脚本模式：python.exe / pythonw.exe + `-m tunless`，只能按解释器判断
    for name in ("python.exe", "pythonw.exe"):
        interpreter = Path(sys.executable).with_name(name)
        try:
            if candidate == interpreter.resolve():
                return True
        except OSError:
            continue
    return False


def start_menu_path(profile: Profile) -> Path:
    """旧版本生成快捷方式的位置（0.1.8 起只用来清理历史遗留）。"""
    return config.START_MENU_DIR / shortcut_name(profile)


def desktop_dir() -> Path:
    """桌面目录。

    必须问 Shell 要，不能拼 `%USERPROFILE%\\Desktop` —— 开了 OneDrive 的机器上
    桌面会被重定向到 `%USERPROFILE%\\OneDrive\\桌面`，拼出来的路径在资源管理器里
    根本看不见（用户点"创建桌面快捷方式"就会得到"文件没出现在桌面上"）。
    """
    try:
        from ..detect.lnk import _com_init

        _com_init()
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        folder = str(shell.SpecialFolders("Desktop") or "")
        del shell
        if folder and os.path.isdir(folder):
            return Path(folder)
    except Exception:  # noqa: BLE001 - 拿不到就退回常规路径
        pass
    return Path(os.environ.get("USERPROFILE", "")) / "Desktop"


def desktop_path(profile: Profile) -> Path:
    return desktop_dir() / shortcut_name(profile)


#: 自动生成的快捷方式放在哪 —— 桌面（0.1.8 起）。用户要的就是"删/找都方便"。
def generated_path(profile: Profile) -> Path:
    return desktop_path(profile)


class ShortcutOccupied(RuntimeError):
    """目标位置已经有一个**不是本程序生成的**同名快捷方式 —— 不覆盖。

    生成到桌面之后就有了这个新问题：开始菜单那边我们有自己的子目录，桌面是用户
    自己的地盘。用户桌面上十有八九已经有 "Visual Studio Code" 之类的图标，
    直接覆盖等于把他的东西弄没了。所以宁可拒绝并说清楚，让他自己选：
    用「接管原快捷方式」（会先备份）、或者先给那个图标改个名。
    """


def _is_our_shortcut(path: Path, profile: Profile | None = None) -> bool:
    """这个 .lnk 是不是**本程序生成的**（而不是用户自己的、只是被我们接管的）？

    只认"目标指向本程序 + 参数里有 `--run`"；解析不出来就一律当成"不是我们的"，
    宁可不删也不误删用户的快捷方式。
    """
    if not path.is_file():
        return False
    try:
        from ..detect.lnk import read_lnk

        info = read_lnk(str(path))
    except Exception:  # noqa: BLE001 - 解析失败按"不是我们的"处理
        return False
    target = (info.get("target") or "").strip().strip('"')
    arguments = info.get("args") or ""
    if APP_ARGS_PREFIX not in arguments or not is_self_launcher(target):
        return False
    if profile is not None and profile.id not in arguments:
        return False
    return True


def _retire_start_menu_copy(profile: Profile) -> Path | None:
    """清掉旧版本留在开始菜单里的那一份（确认是本程序生成的、且不是被接管的那个）。

    返回被删掉的路径（没删就是 None）。这是"快捷方式从开始菜单改到桌面"的迁移动作：
    不做的话用户会同时在两个地方看到同一个应用，删了一个另一个还在。
    """
    legacy = start_menu_path(profile)
    if not legacy.is_file():
        return None
    if profile.adopted_shortcut and Path(profile.adopted_shortcut) == legacy:
        return None  # 用户自己的快捷方式被接管到了这里，绝不能删
    if not _is_our_shortcut(legacy, profile):
        return None
    try:
        legacy.unlink()
    except OSError:
        return None
    # 目录空了就一并收拾掉（旧版本的 TunlessProxy 开始菜单文件夹）
    try:
        config.START_MENU_DIR.rmdir()
    except OSError:
        pass
    return legacy


def _icon_location(profile: Profile) -> str:
    """给 .lnk 用的图标。

    优先用目标自己的图标（`C:\\...\\App.exe,0` 或 `imageres.dll,-114`）：
    Explorer 对 exe/dll+索引 的支持最稳，直接指 PNG 有时根本不显示。
    实在没有才退回我们自己缓存的 .ico（不是 .png）。
    """
    source = (profile.spec.icon_source or profile.spec.target or "").strip()
    if source:
        file_part = source.rsplit(",", 1)[0].strip().strip('"')
        if os.path.isfile(file_part):
            return source
    cached_ico = config.icon_path(profile.id).with_suffix(".ico")
    if cached_ico.is_file():
        return f"{cached_ico},0"
    return source


def _write_lnk(
    path: Path,
    target: str,
    arguments: str,
    working_dir: str,
    icon: str,
    description: str = "",
) -> None:
    from ..detect.lnk import _com_init

    _com_init()
    import win32com.client  # type: ignore

    path.parent.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(path))
    shortcut.TargetPath = target
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = working_dir
    if icon:
        shortcut.IconLocation = icon
    if description:
        shortcut.Description = description
    shortcut.Save()
    del shortcut, shell


def _occupied_by_same_app(path: Path, profile: Profile) -> bool:
    """占着目标位置的那个快捷方式，是不是**这个应用自己的图标**？

    判据：解析出来的目标可执行文件与这个 profile 要启动的目标一致。
    是的话就不该当成"冲突"，而应按「接管」处理 —— 用户拖进程序里的往往就是桌面上
    这个图标（比如 `source_path` 直接就是 `桌面\\Visual Studio Code.lnk`），
    他要的就是"点它走代理"。不是同一个应用才拒绝覆盖。
    """
    try:
        from ..detect.lnk import read_lnk

        info = read_lnk(str(path))
    except Exception:  # noqa: BLE001 - 解析不了就按"不是同一个应用"处理
        return False
    target = (info.get("target") or "").strip().strip('"')
    if not target or not profile.spec.target:
        return False
    try:
        return Path(target).resolve() == Path(profile.spec.target).resolve()
    except OSError:
        return target.lower() == profile.spec.target.lower()


def create_shortcut(profile: Profile, path: Path | None = None) -> Path:
    """生成（或刷新）这个应用的独立快捷方式 —— 默认落在**桌面**。

    * 目标位置已有**我们自己**生成的同一条 → 当作刷新，直接重写；
    * 目标位置是**这个应用自己的图标**（别人建的，比如用户桌面原来那个）→
      按「接管」处理：先备份到 `backup\\lnk\\`，再替换成经代理启动的那份，
      界面上的「还原」能把它换回去；
    * 目标位置是**别的**同名文件 → 抛 `ShortcutOccupied`，绝不覆盖；
    * 写完顺手把旧版本留在开始菜单里的那一份清掉，避免同一个应用在两处各有一个。
    """
    destination = path or generated_path(profile)
    if destination.is_file() and not _is_our_shortcut(destination, profile):
        if not _occupied_by_same_app(destination, profile):
            raise ShortcutOccupied(
                f"{destination} 已经存在，而且不是本程序创建的快捷方式 —— 没有覆盖它。"
                "可以先用「接管原快捷方式」接手它（会先备份原文件），或者改个名字。"
            )
        # 同一个应用的图标：接管它（备份 + 记录，可一键还原）
        backup = config.LNK_BACKUP_DIR / f"{profile.id}__{destination.name}"
        if not backup.is_file():
            config.LNK_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(destination, backup)
            except OSError:
                pass  # 备份失败也别拦着（只是没法一键还原了）
        profile.adopted_shortcut = str(destination)

    executable, prefix, workdir = launcher_command()
    arguments = f"{prefix} {APP_ARGS_PREFIX} {profile.id}".strip()
    _write_lnk(
        destination,
        executable,
        arguments,
        workdir,
        _icon_location(profile),
        f"{profile.name}（经代理启动）",
    )
    _retire_start_menu_copy(profile)
    return destination


def create_desktop_shortcut(profile: Profile, directory: Path | None = None) -> Path:
    """在**桌面**上放一个快捷方式。

    `directory` 只给测试用，便于往临时目录里写、不污染真实桌面。
    """
    destination = (directory or desktop_dir()) / shortcut_name(profile)
    return create_shortcut(profile, destination)


def remove_shortcut(profile: Profile, keep: str | None = None) -> bool:
    """删掉生成出来的快捷方式（桌面那份，以及旧版本留在开始菜单里的那份）。

    `keep` 是"不能删的路径"：被接管的那个文件刚刚被还原成用户自己的图标，
    这时候它正好也躺在生成位置上，删了等于把用户的东西弄没了
    （见 `service.delete_profile`）。
    """
    protected: Path | None = None
    if keep:
        try:
            protected = Path(keep).resolve()
        except OSError:
            protected = None

    removed = False
    for path in (generated_path(profile), start_menu_path(profile)):
        if not path.is_file():
            continue
        if protected is not None:
            try:
                if path.resolve() == protected:
                    continue
            except OSError:
                pass
        try:
            path.unlink()
            removed = True
        except OSError:
            continue
    if removed:
        try:
            config.START_MENU_DIR.rmdir()
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- 接管 / 还原

def adoption_backup_path(profile: Profile) -> Path:
    original = Path(profile.adopted_shortcut or profile.source_path)
    return config.LNK_BACKUP_DIR / f"{profile.id}__{original.name}"


def adopt_shortcut(profile: Profile) -> bool:
    """把原 .lnk 原地替换成指向本程序的快捷方式（先备份）。"""
    original = Path(profile.source_path)
    if original.suffix.lower() != ".lnk" or not original.is_file():
        return False

    backup = adoption_backup_path(profile)
    if not backup.is_file():
        config.LNK_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, backup)

    executable, prefix, workdir = launcher_command()
    arguments = f"{prefix} {APP_ARGS_PREFIX} {profile.id}".strip()
    _write_lnk(
        original,
        executable,
        arguments,
        workdir,
        _icon_location(profile),
        f"{profile.name}（经代理启动）",
    )
    profile.adopted_shortcut = str(original)
    return True


def restore_adopted(profile: Profile) -> bool:
    """还原被接管的快捷方式。"""
    if not profile.adopted_shortcut:
        return False
    backup = adoption_backup_path(profile)
    if not backup.is_file():
        profile.adopted_shortcut = None
        return False
    try:
        shutil.copy2(backup, profile.adopted_shortcut)
        backup.unlink()
    except OSError:
        return False
    profile.adopted_shortcut = None
    return True


def adoption_backups() -> list[Path]:
    if not config.LNK_BACKUP_DIR.is_dir():
        return []
    return sorted(config.LNK_BACKUP_DIR.glob("*.lnk"))
