"""打包产物验收：对着 dist/TunlessProxy 里的 exe 跑一遍真实链路。

    python tests/verify_package.py

判据和 tests/e2e 一样 —— 用会记录请求的假代理，证明"请求真的到了代理"。
这里额外覆盖打包后才可能暴露的问题：
  * dist 到底是不是用当前源码打的（比对 PYZ 里每个模块的字节码，比看时间戳可靠）
  * 4 套主题的数据有没有被打进去
  * 入口脚本的相对导入
  * 快捷方式指向哪个 exe（必须是窗口化那个，否则双击会闪黑框）
  * 窗口化父进程拉起命令行子进程时，子进程还能不能拿到控制台
  * 品牌字标在**打包后的窗口**里确实被画出来并且真的在动（截真实窗口比对像素）

最后一项需要可见桌面：没有桌面（或已有实例在跑）时会显式跳过并说明原因。
运行期间会短暂弹出一次程序窗口，约 5 秒后自动结束。

**验收跑在临时数据目录里**（`TUNLESS_DATA_DIR`）：打包版和脚本读的必须是同一份
配置，而打包版默认用 `dist/TunlessProxy/data/`、脚本默认用 `项目根/data/` ——
不统一的话两边根本不是同一套数据。顺带也保证验收不会动用户真实的应用配置。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 必须在导入 tunless.config 之前设好（数据目录在 import 时解析）
DATA_DIR = Path(tempfile.mkdtemp(prefix="tunless-verifydata-"))
os.environ["TUNLESS_DATA_DIR"] = str(DATA_DIR)

from tests.e2e.tiny_proxy import TinyProxy  # noqa: E402
from tunless import config, service  # noqa: E402
from tunless.detect.lnk import read_lnk  # noqa: E402
from tunless.launch import shortcuts  # noqa: E402
from tunless.model import Family  # noqa: E402

DIST = ROOT / "dist" / "TunlessProxy"
GUI_EXE = DIST / "TunlessProxy.exe"
CLI_EXE = DIST / "tunless.exe"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
PROBE_URL = "http://probe.tunless.invalid/packaged"

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    RESULTS.append((ok, name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""), flush=True)
    return ok


def find_edge() -> str | None:
    for candidate in EDGE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(CLI_EXE), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def kill_tree(pid: int) -> None:
    """连子孙一起杀 —— PyInstaller 引导进程会再派生一个子进程。"""
    subprocess.run(
        ["taskkill", "/T", "/F", "/PID", str(pid)],
        capture_output=True, text=True, errors="replace",
    )


# ---------------------------------------------------------------- 字节码比对

def _code_children(code):
    return [k for k in code.co_consts if hasattr(k, "co_code")]


def _code_diffs(packaged, current, path="<module>", diffs=None):
    """递归比较两个 code object，返回差异描述（空列表 = 逐字节一致）。

    只比与文件名无关的字段，所以不会被 `co_filename` 的路径分隔符干扰 ——
    上一轮排查时正是被这个坑到，误以为产物陈旧。
    """
    if diffs is None:
        diffs = []
    for attr in ("co_code", "co_names", "co_varnames", "co_flags", "co_argcount", "co_name"):
        left, right = getattr(packaged, attr), getattr(current, attr)
        if left != right:
            diffs.append(f"{path}.{attr}: 包内={left!r} 源码={right!r}")

    left_consts = [k for k in packaged.co_consts if not hasattr(k, "co_code")]
    right_consts = [k for k in current.co_consts if not hasattr(k, "co_code")]
    if len(left_consts) != len(right_consts):
        diffs.append(f"{path}.co_consts 长度: 包内={len(left_consts)} 源码={len(right_consts)}")
    else:
        for idx, (lc, rc) in enumerate(zip(left_consts, right_consts)):
            if lc != rc or type(lc) is not type(rc):
                diffs.append(f"{path}.co_consts[{idx}]: 包内={lc!r} 源码={rc!r}")

    left_kids, right_kids = _code_children(packaged), _code_children(current)
    if len(left_kids) != len(right_kids):
        diffs.append(f"{path}: 嵌套 code 数量 {len(left_kids)} != {len(right_kids)}")
    else:
        for lk, rk in zip(left_kids, right_kids):
            _code_diffs(lk, rk, f"{path}.{lk.co_name}", diffs)
    return diffs


_PYZ_CACHE: list = []


def load_pyz():
    """把 exe 内嵌的 PYZ 解出来（onedir 下 _internal 里没有单独的 .pyz 文件）。"""
    if _PYZ_CACHE:
        return _PYZ_CACHE[0]
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    archive = CArchiveReader(str(GUI_EXE))
    pyz_tmp = Path(tempfile.gettempdir()) / "tunless_verify_pyz.pyz"
    pyz_tmp.write_bytes(archive.extract("PYZ.pyz"))
    reader = ZlibArchiveReader(str(pyz_tmp))
    _PYZ_CACHE.append(reader)
    return reader


def check_dist_matches_source() -> None:
    """dist 是不是用当前源码打的 —— 比对 PYZ 里全部 tunless.* 模块的字节码。

    比"看 exe 时间戳比 .py 新"可靠得多：时间戳会被 touch / 复制 / 校验修改骗过，
    而字节码一致意味着 exe 里跑的就是眼前这份源码。
    """
    try:
        reader = load_pyz()
    except ImportError:
        check(True, "dist 由当前源码构建", "跳过：没有 PyInstaller，无法读 PYZ")
        return
    except Exception as exc:  # noqa: BLE001
        check(False, "dist 由当前源码构建", f"读 PYZ 失败：{type(exc).__name__}: {exc}")
        return

    modules = sorted(n for n in reader.toc if n == "tunless" or n.startswith("tunless."))
    stale: list[str] = []
    checked = 0
    for name in modules:
        parts = name.split(".")
        base = ROOT.joinpath(*parts)
        source = next(
            (p for p in (base.with_suffix(".py"), base / "__init__.py") if p.is_file()), None
        )
        if source is None:
            continue
        # dont_inherit=True 很关键：本模块自己带 `from __future__ import annotations`，
        # 继承标志会让源码侧多出 CO_FUTURE_ANNOTATIONS，凭空报出 5 个假差异。
        current = compile(source.read_text(encoding="utf-8"), source.name, "exec", dont_inherit=True)
        diffs = _code_diffs(reader.extract(name), current)
        checked += 1
        if diffs:
            stale.append(f"{name}: {diffs[0]}")

    check(
        not stale and checked > 0,
        f"dist 由当前源码构建（{checked} 个模块字节码逐字段一致）",
        "；".join(stale[:3]),
    )


def check_bundled_themes() -> None:
    """4 套主题的数据确实在包里。

    以前这里断言的是"theme.qss 已打进包"—— 那是废弃的静态样式表，
    产品代码早就改成 theme_tokens 动态生成 QSS，等于在给一个死文件上保险。
    """
    try:
        reader = load_pyz()
        code = reader.extract("tunless.gui.theme_tokens")
    except Exception as exc:  # noqa: BLE001
        check(False, "4 套主题已打进包", f"读主题模块失败：{type(exc).__name__}: {exc}")
        return

    constants: set[str] = set()

    def walk(node) -> None:
        for value in node.co_consts:
            if isinstance(value, str):
                constants.add(value)
            elif hasattr(value, "co_consts"):
                walk(value)

    walk(code)
    wanted = {"midnight", "pure-crystal", "aurora", "frosted"}
    missing = sorted(wanted - constants)
    check(not missing, "4 套主题已打进包（theme_tokens 里四个 id 都在）",
          f"缺：{missing}" if missing else "midnight / pure-crystal / aurora / frosted")


# ---------------------------------------------------------------- 真实窗口截图

def make_dpi_aware() -> None:
    """系统 125% 缩放时，DPI 不感知的进程拿到的是虚拟化坐标。

    那样 PrintWindow 会按缩小后的矩形去画真实的大窗口，截图右边被裁掉
    （第一版就是这样，看起来像"界面被切了"，其实只是截图工具的问题）。
    """
    try:
        import ctypes

        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:  # noqa: BLE001 - 老系统没有这个 API
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass


def find_visible_window(pid: int) -> int | None:
    import win32gui
    import win32process

    found: list[int] = []

    def callback(hwnd, _extra):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            _tid, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid:
                found.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return found[0] if found else None


def capture_window(hwnd: int):
    """把窗口内容抓成 QImage（PrintWindow + PW_RENDERFULLCONTENT，DWM 下也有效）。"""
    import ctypes

    import win32con
    import win32gui
    import win32ui
    from PyQt6.QtGui import QImage

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    memory_dc.SelectObject(bitmap)
    try:
        if not ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), 2):
            memory_dc.BitBlt((0, 0), (width, height), source_dc, (0, 0), win32con.SRCCOPY)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return QImage(
            bits, info["bmWidth"], info["bmHeight"], QImage.Format.Format_ARGB32
        ).copy()
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


#: 打包版标题那三条判据的名字（跳过时也要如实报出条数）
TITLE_CHECK_NAMES = (
    "打包版顶部软件名是三段式（Tunless ● Proxy）",
    "打包版 Proxy 是横向渐变（左端与右端明显不同色）",
    "打包版字标不再有紫色发光（旧样式已彻底移除）",
)


def _is_dot_green(color) -> bool:
    return (
        abs(color.red() - 16) < 55
        and abs(color.green() - 185) < 55
        and abs(color.blue() - 129) < 55
    )


def _is_bluish(color) -> bool:
    red, green, blue = color.red(), color.green(), color.blue()
    return blue > red + 25 and blue > green + 10 and blue > 110


def _is_neutral_text(color, bg_luma: float) -> bool:
    spread = max(color.red(), color.green(), color.blue()) - min(
        color.red(), color.green(), color.blue()
    )
    luma = 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
    return spread < 40 and abs(luma - bg_luma) > 35


def _is_purple(color) -> bool:
    """明显的紫色发光（旧那套字标的特征：R 与 B 都远高于 G，而且**够亮**）。

    为什么还要卡亮度：Windows 的 ClearType 会在字形边缘留下几个偏色的亚像素毛边
    （实测 "Proxy" 边缘有 3 个 `rgb(59,14,116)` 的暗紫点），那既不是发光也不该算。
    旧光晕的核心色是 `#7C5CF0`（亮度 ≈ 110），在 206×41 的区域里能有几千个点亮紫，
    所以"够亮 + 数量"两条一起卡，既不会误报也漏不掉真的回来。
    """
    if not (color.red() > color.green() + 25 and color.blue() > color.green() + 25):
        return False
    luma = 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
    return luma > 60


def title_region_stats(image) -> dict[str, int]:
    """统计软件名那一段的像素分类，并确认三段的左右顺序。

    取样行**以绿色微点为锚点**：先在较大范围里找这个绿点（它是字标自身的一部分，
    位置最可靠），再只看它上下各 16px 的那一带。不这么做就很容易把标题下方
    「添加应用」那个紫色按钮一起算进来 —— 第一版就是这么误报"还有紫色"的。
    """
    width, height = image.width(), image.height()
    x0, x1 = int(width * 0.06), int(width * 0.20)
    result = {
        "green": 0, "blue": 0, "neutral": 0, "purple": 0, "samples": 0,
        "dot_x": -1, "blue_x": -1, "neutral_x": -1, "ordered": 0,
    }

    probes = [
        (x, y)
        for y in range(int(height * 0.05), int(height * 0.30))
        for x in range(x0, x1)
        if _is_dot_green(image.pixelColor(x, y))
    ]
    if not probes:
        return result

    rows = sorted(y for _x, y in probes)
    middle = rows[len(rows) // 2]
    top, bottom = max(0, middle - 16), min(height, middle + 16)

    tally: dict[tuple[int, int, int], int] = {}
    pixels = []
    for y in range(top, bottom):
        for x in range(x0, x1):
            color = image.pixelColor(x, y)
            pixels.append((x, color))
            key = (color.red(), color.green(), color.blue())
            tally[key] = tally.get(key, 0) + 1
    if not pixels:
        return result
    bg = max(tally.items(), key=lambda item: item[1])[0]
    bg_luma = 0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]

    greens, blues, neutrals = [], [], []
    for x, color in pixels:
        if _is_dot_green(color):
            greens.append(x)
        elif _is_bluish(color):
            blues.append(x)
        elif _is_neutral_text(color, bg_luma):
            neutrals.append(x)
        if _is_purple(color):
            result["purple"] += 1

    def median(values: list[int]) -> int:
        if not values:
            return -1
        values = sorted(values)
        return values[len(values) // 2]

    result.update(
        green=len(greens),
        blue=len(blues),
        neutral=len(neutrals),
        samples=len(pixels),
        dot_x=median(greens),
        blue_x=median(blues),
        neutral_x=median(neutrals),
        bg_luma=round(bg_luma),
    )
    # 顺序用**极值**判：Proxy 的渐变左端接近纯白，会被算进"中性字"里，
    # 用中位数比就会误判成"中性字跑到点的右边"。
    result["ordered"] = int(
        bool(neutrals) and bool(blues) and min(neutrals) < result["dot_x"] < max(blues)
    )

    # Proxy 那一段的横向渐变：左三分之一与右三分之一的最亮像素比一比
    right_zone = [
        (x, color) for x, color in pixels if x > result["dot_x"] + 6
    ]
    if right_zone:
        xs = sorted(x for x, _c in right_zone)
        span = max(1, xs[-1] - xs[0])
        left_third = [c for x, c in right_zone if x <= xs[0] + span / 3]
        right_third = [c for x, c in right_zone if x >= xs[-1] - span / 3]

        def peak_luma(colors):
            best = 0.0
            for color in colors:
                luma = (
                    0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
                )
                best = max(best, luma)
            return round(best)

        result["proxy_left_luma"] = peak_luma(left_third)
        result["proxy_right_luma"] = peak_luma(right_third)
    return result


def check_packaged_title_mark() -> None:
    """打包后的窗口里，顶部软件名是不是按三段式画出来的。

    判据全部落在**真实窗口的像素**上（不是"看起来像"）：
      * 绿色微点：与 `#10B981` 同族（四套主题都是同一个绿）；
      * 冰蓝/深蓝的 "Proxy"：明显偏蓝的像素；
      * 中性灰白/深灰的 "Tunless"：低饱和但相对背景有明显亮度差；
      * **不许有紫色像素** —— 原来那套紫色发光字标必须彻底不在了。
    """
    make_dpi_aware()
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)  # 要真的窗口，offscreen 抓不到
    proc = subprocess.Popen([str(GUI_EXE)], env=env)
    try:
        hwnd = None
        deadline = time.time() + 20
        while time.time() < deadline and hwnd is None:
            if proc.poll() is not None:
                for name in TITLE_CHECK_NAMES:
                    check(True, name, "跳过：已有实例在运行（单实例），本次没有新窗口")
                return
            hwnd = find_visible_window(proc.pid)
            if hwnd is None:
                time.sleep(0.5)
        if hwnd is None:
            for name in TITLE_CHECK_NAMES:
                check(True, name, "跳过：当前会话没有可见桌面，拿不到窗口")
            return

        time.sleep(1.0)  # 等窗口画完
        image = capture_window(hwnd)
        shot = ROOT / "tests" / "preview" / "packaged_title.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(shot), "PNG")

        counts = title_region_stats(image)
        size = f"{image.width()}x{image.height()}"
        ok = (
            counts["green"] >= 2
            and counts["blue"] >= 8
            and counts["neutral"] >= 8
            and counts["ordered"] == 1
        )
        check(
            ok,
            "打包版顶部软件名是三段式（Tunless ● Proxy）",
            f"窗口 {size}：绿点 {counts['green']} 点 @x={counts['dot_x']}、"
            f"蓝色字 {counts['blue']} 点 @x={counts['blue_x']}、"
            f"中性字 {counts['neutral']} 点 @x={counts['neutral_x']}"
            f"（顺序正确={bool(counts['ordered'])}），截图 {shot.name}",
        )
        # Proxy 是横向渐变：左端接近纯白、右端冰蓝。深色底上"左亮右暗"，
        # 浅色主题用同结构的深色版（左深右蓝），所以只卡"两端明显不同 + 右端偏蓝"。
        left_luma = counts.get("proxy_left_luma", 0)
        right_luma = counts.get("proxy_right_luma", 0)
        dark_bg = counts.get("bg_luma", 255) < 128
        gradient_ok = (
            abs(left_luma - right_luma) >= 20
            and counts["blue"] >= 8
            and (left_luma > right_luma if dark_bg else True)
        )
        check(
            gradient_ok,
            "打包版 Proxy 是横向渐变（左端与右端明显不同色）",
            f"左端峰值亮度 {left_luma}、右端 {right_luma}（背景亮度 {counts.get('bg_luma')}）",
        )
        check(
            counts["purple"] <= 30,
            "打包版字标不再有紫色发光（旧样式已彻底移除）",
            f"亮紫色像素 {counts['purple']} 点（>30 即视为旧发光回来了）",
        )
    finally:
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def main() -> int:
    if not GUI_EXE.is_file() or not CLI_EXE.is_file():
        print(f"没有找到打包产物：{DIST}\n先跑 pyinstaller --noconfirm --clean tunless.spec")
        return 1

    # ---------------------------------------------------------- 1. 基本可用
    result = run_cli("--version")
    check(result.returncode == 0 and "TunlessProxy" in result.stdout,
          "tunless.exe --version", result.stdout.strip())

    # 作者/许可跟「关于」页同源，打包后也要在
    from tunless import __author__, __copyright__, __license_label__

    check(
        __license_label__ in result.stdout and __copyright__ in result.stdout
        and __author__ in result.stdout,
        "打包版 --version 带作者/许可（与关于页同源）",
        result.stdout.strip().replace("\n", " | "),
    )

    # 产物是不是眼前这份源码打的 —— 后面的结论都建立在这一条之上，所以放最前面
    check_dist_matches_source()

    result = run_cli("--doctor", "--json")
    doctor = {}
    try:
        doctor = json.loads(result.stdout)
    except ValueError:
        pass
    check(doctor.get("frozen") is True, "打包版自报 frozen=True")
    check(doctor.get("profileCount") is not None, "--doctor --json 可解析")
    check(bool(doctor.get("endpoint", {}).get("mixed_port")), "端点探测正常",
          str(doctor.get("endpoint")))

    # 数据目录：验收用 TUNLESS_DATA_DIR 指定，打包版必须照做（否则两边不是同一份数据）
    check(
        Path(str(doctor.get("dataDir", ""))).resolve() == DATA_DIR.resolve()
        and doctor.get("dataDirSource") == "env",
        "打包版按 TUNLESS_DATA_DIR 使用指定数据目录",
        f"dataDir={doctor.get('dataDir')} source={doctor.get('dataDirSource')}",
    )

    # 默认（不给环境变量）必须落在 exe 同级的 data\，这样用户删/导出只处理一个文件夹。
    #
    # 这条**必须在沙箱里跑**：打包版第一次运行会顺手把 %APPDATA% 里的旧数据迁移到
    # exe 同级的 data\，直接在 dist 里跑就会把用户的数据（含 npmrc/gitconfig 这类
    # 可能带 token 的文件）复制进交付目录。所以临时造一个目录：拷两个 exe、
    # 用目录联接把 _internal 指回 dist，程序在那里看到的就是"exe 同级的 data\"。
    sandbox = Path(tempfile.mkdtemp(prefix="tunless-portable-"))
    try:
        shutil.copy2(GUI_EXE, sandbox / GUI_EXE.name)
        shutil.copy2(CLI_EXE, sandbox / CLI_EXE.name)
        junction = sandbox / "_internal"
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(GUI_EXE.parent / "_internal")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if junction.exists():
            plain = subprocess.run(
                [str(sandbox / CLI_EXE.name), "--doctor", "--json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120,
                env={k: v for k, v in os.environ.items() if k != "TUNLESS_DATA_DIR"},
            )
            try:
                plain_doctor = json.loads(plain.stdout)
            except ValueError:
                plain_doctor = {}
            got_dir = str(plain_doctor.get("dataDir", ""))
            check(
                got_dir and Path(got_dir).resolve() == (sandbox / "data").resolve()
                and plain_doctor.get("dataDirSource") == "portable",
                "打包版默认把生成物放在 exe 同级的 data\\",
                f"dataDir={got_dir} source={plain_doctor.get('dataDirSource')}",
            )
        else:
            check(True, "打包版默认把生成物放在 exe 同级的 data\\",
                  f"跳过：沙箱目录联接没建成（{made.stderr.strip()[:120]}）")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    # ---------------------------------------------------------- 2. 主题数据
    check_bundled_themes()

    # ---------------------------------------------------------- 3. 快捷方式指向
    # 必须由**打包后的 exe** 来建，才能验证 frozen 分支选的是窗口化那个 exe
    cfg = service.load_config()
    probe_target = r"C:\Windows\System32\notepad.exe"
    probe_lnk = shortcuts.desktop_dir() / "notepad.lnk"
    if probe_lnk.exists():
        # 桌面上已经有同名文件（可能是用户自己的）—— 绝不能覆盖或删掉它
        check(True, "打包版 --add 会在桌面创建独立快捷方式",
              f"跳过：桌面上已有 {probe_lnk.name}，不覆盖你自己的快捷方式")
        check(True, "快捷方式指向窗口化 exe（避免闪黑框）", "同上：跳过")
        check(True, "快捷方式带 --run 参数", "同上：跳过")
        check(True, "快捷方式图标用 exe/dll+索引", "同上：跳过")
    else:
        # 快捷方式默认关闭，所以这里显式要一次（--shortcut 是一次性开关，不写回设置）
        result = run_cli("--add", probe_target, "--shortcut")
        created = None
        for line in result.stdout.splitlines():
            if "快捷方式:" in line:
                created = line.split("快捷方式:", 1)[1].strip()
        check(bool(created) and Path(created).is_file(),
              "打包版 --add 会在桌面创建独立快捷方式", created or result.stdout.strip())
        check(
            bool(created) and Path(created).resolve() == probe_lnk.resolve(),
            "生成位置就是桌面（0.1.8 起从开始菜单搬过来）",
            f"{created} == {probe_lnk}",
        )
        if created and Path(created).is_file():
            info = read_lnk(created)
            check(Path(info["target"]).name.lower() == "tunlessproxy.exe",
                  "快捷方式指向窗口化 exe（避免闪黑框）", info["target"])
            check("--run" in info["args"], "快捷方式带 --run 参数", info["args"])
            check("," in info["icon"], "快捷方式图标用 exe/dll+索引", info["icon"])
            Path(created).unlink()

    # 清掉这次 --add 留下的配置
    cfg = service.load_config()
    for existing in service.list_profiles(cfg):
        if existing.spec.target.lower() == probe_target.lower():
            # 顺手验证打包版能写 ICO（imageformats 裁剪后最容易出问题的地方）
            ico = config.icon_path(existing.id).with_suffix(".ico")
            check(ico.is_file() and ico.stat().st_size > 0,
                  "打包版能写出 .ico（快捷方式图标依赖）",
                  f"{ico.name} {ico.stat().st_size if ico.is_file() else 0}B")
            service.delete_profile(cfg, existing.id)

    # ---------------------------------------------------------- 4. L2：打包版拉 Chromium
    edge = find_edge()
    if edge is None:
        check(True, "打包版 Chromium 代理注入", "跳过：未找到 Edge")
    else:
        user_data = tempfile.mkdtemp(prefix="tunless-pkg-edge-")
        profile = service.build_profile(edge, "pkg-edge")
        profile.id = "00000000-0000-4000-8000-00000000edce"
        profile.spec.args = (
            f"--headless --disable-gpu --no-first-run --no-default-browser-check "
            f'--user-data-dir="{user_data}" --dump-dom "{PROBE_URL}"'
        )
        profile.spec.family = Family.ELECTRON
        profile.levers = {"env": True, "cmdline": True, "configFiles": False}
        profile.console_mode = "none"
        service.save_profile(cfg, profile)

        with TinyProxy() as proxy:
            cfg2 = service.load_config()
            cfg2.setdefault("settings", {}).setdefault("endpoint", {})
            # 让打包版把代理指向我们的假代理
            saved = dict(cfg2["settings"]["endpoint"])
            cfg2["settings"]["endpoint"].update(
                {"autoDetect": False, "host": "127.0.0.1", "mixedPort": proxy.port,
                 "manual": {"host": "127.0.0.1", "port": proxy.port}}
            )
            config.save(cfg2)
            try:
                run_cli("--run", profile.id, timeout=120)
                reached = proxy.wait_for("probe.tunless.invalid", 60)
                check(reached, "打包版注入 --proxy-server 后请求到达代理",
                      f"记录={proxy.targets()[:3]}")
            finally:
                cfg3 = service.load_config()
                cfg3["settings"]["endpoint"] = saved
                config.save(cfg3)
                service.delete_profile(cfg3, profile.id)

    # ---------------------------------------------------------- 5. 窗口化父进程 → 控制台子进程
    probe_out = Path(tempfile.gettempdir()) / "tunless_pkg_probe.json"
    if probe_out.exists():
        probe_out.unlink()
    py = Path(sys.executable)
    probe = service.build_profile(str(py), "pkg-probe")
    probe.id = "00000000-0000-4000-8000-0000000000bb"
    probe.spec.args = f'"{ROOT / "tests" / "probe_stdout.py"}"'
    probe.console_mode = "new"
    probe.env_extra = {"PROBE_OUT": str(probe_out)}
    cfg4 = service.load_config()
    service.save_profile(cfg4, probe)
    try:
        subprocess.run(
            [str(GUI_EXE), "--run", probe.id], capture_output=True, timeout=90
        )
        deadline = time.time() + 20
        while time.time() < deadline and not probe_out.exists():
            time.sleep(0.3)
        if probe_out.exists():
            info = json.loads(probe_out.read_text(encoding="utf-8"))
            check(info.get("stdout_handle_valid") and info.get("write_ok"),
                  "窗口化父进程拉起的子进程有可用控制台",
                  f"handle={info.get('stdout_handle')} isatty={info.get('stdout_isatty')}")
        else:
            check(False, "窗口化父进程拉起的子进程有可用控制台", "探针无输出")
    finally:
        cfg5 = service.load_config()
        service.delete_profile(cfg5, probe.id)
        if probe_out.exists():
            probe_out.unlink()

    # ---------------------------------------------------------- 6. GUI 起得来
    # crash.log 是**追加**写入的，所以必须先记下当前长度，只看本次运行新增的部分。
    # 直接读文件尾部会把历史遗留的 traceback 也算进来，让这一项永远失败
    # （排查时误以为是打包问题，其实只是几天前某次调试留下的）。
    crash = config.LOG_DIR / "crash.log"
    crash_before = crash.stat().st_size if crash.is_file() else 0

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.Popen([str(GUI_EXE)], env=env)
    time.sleep(8)
    alive = proc.poll() is None
    check(alive, "打包版 GUI 能启动并常驻", f"pid={proc.pid}")
    # PyInstaller 的 onedir 引导进程会再派生一个真正的运行进程，
    # 只 kill 父进程会留下子进程占着 exe，下次打包就会「拒绝访问」。
    kill_tree(proc.pid)
    proc.wait(timeout=10)
    time.sleep(1)
    leftover = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq TunlessProxy.exe", "/NH"],
        capture_output=True, text=True, errors="replace",
    ).stdout
    check("TunlessProxy.exe" not in leftover, "退出后没有残留进程占着 exe",
          leftover.strip()[:120])

    crash_now = crash.stat().st_size if crash.is_file() else 0
    appended = ""
    if crash_now > crash_before:
        with crash.open("rb") as handle:
            handle.seek(crash_before)
            appended = handle.read().decode("utf-8", errors="replace")
    check(
        not appended.strip(),
        "打包版运行未新增崩溃日志",
        f"新增 {crash_now - crash_before} 字节：{appended.strip()[-300:]}",
    )

    # ---------------------------------------------------------- 7. 顶部软件名
    # offscreen 能证明"没崩"，但证明不了"画出来了" —— 抓真实窗口看像素。
    check_packaged_title_mark()

    # ---------------------------------------------------------- 收尾
    # 打包版每次启动都会先探一次"程序旁边能不能写"，于是 dist 里会留下一个空的 data\。
    # ---------------------------------------------------------- 收尾
    # 兜底：万一还有哪一步在 dist 里留下了空的 data\（打包版启动时会先探一次
    # "这里能不能写"），把空目录收拾掉。**非空一律不动** —— 那可能是用户自己
    # 跑打包版攒下的配置。
    portable_dir = GUI_EXE.parent / "data"
    try:
        if portable_dir.is_dir() and not any(portable_dir.iterdir()):
            portable_dir.rmdir()
    except OSError:
        pass

    # ---------------------------------------------------------- 汇总
    failed = [name for ok, name, _ in RESULTS if not ok]
    print("\n" + "=" * 60)
    print(f"共 {len(RESULTS)} 项，失败 {len(failed)} 项")
    for name in failed:
        print(f"  FAIL  {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
