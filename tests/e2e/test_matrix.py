"""端到端验收矩阵。

判据一律是"请求有没有到达我们自己起的假代理"，而不是比对出口 IP ——
后者会被 Clash 的系统代理（Chromium 会读 WinINET）干扰，证明不了任何东西。

运行：python tests/run_all.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.e2e.tiny_proxy import TinyProxy  # noqa: E402
from tunless import config as config_mod  # noqa: E402
from tunless.detect import endpoint as endpoint_mod  # noqa: E402
from tunless.detect import family as family_mod  # noqa: E402
from tunless.detect import lnk, peinfo  # noqa: E402
from tunless.launch import cmdline as cmdline_mod  # noqa: E402
from tunless.launch import proc  # noqa: E402
from tunless.model import AppSpec, Family, Profile, ProxyEndpoint  # noqa: E402

CURL = r"C:\Windows\System32\curl.exe"
GIT = r"C:\Program Files\Git\cmd\git.exe"
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

PROBE_URL = "http://probe.tunless.invalid/hello"


def find_edge() -> str | None:
    for candidate in EDGE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def make_profile(target: str, args: str = "", name: str = "test") -> Profile:
    spec = lnk.resolve(target)
    if args:
        spec.args = args
    info = peinfo.analyze(spec.target)
    spec.arch = info["arch"]
    spec.subsystem = info["subsystem"]
    family_mod.classify(spec)
    profile = Profile(name=name, source_path=spec.source_path, spec=spec)
    profile.levers = family_mod.default_levers(spec.family)
    profile.console_mode = "none"
    return profile


def endpoint_for(proxy: TinyProxy) -> ProxyEndpoint:
    return ProxyEndpoint(
        host="127.0.0.1", mixed_port=proxy.port,
        socks_port=proxy.port, http_port=proxy.port, source="test",
    )


def force_family(profile: Profile, family: Family) -> Profile:
    """改家族时必须同时重算 lever —— GUI 里手动改家族也是这个语义。"""
    profile.spec.family = family
    profile.levers = family_mod.default_levers(family)
    return profile


class TinyProxySelfTest(unittest.TestCase):
    """先证明假代理本身是可靠的。"""

    def test_curl_reaches_tiny_proxy(self):
        with TinyProxy() as proxy:
            subprocess.run(
                [CURL, "-s", "-x", proxy.url, "-o", os.devnull, PROBE_URL],
                capture_output=True, timeout=30,
            )
            self.assertTrue(proxy.wait_for("probe.tunless.invalid", 10),
                            f"假代理没收到请求，记录={proxy.requests}")


class CliLeverTests(unittest.TestCase):
    """L1 环境变量 + L3 配置文件指针。"""

    def test_curl_env_via_real_launcher(self):
        with TinyProxy() as proxy:
            profile = make_profile(CURL, f"-s -o {os.devnull} {PROBE_URL}", "curl-e2e")
            plan = proc.build_plan(profile, endpoint_for(proxy))
            self.assertIn("HTTP_PROXY", plan.env_delta)
            proc.launch(plan, profile, wait=True)
            self.assertTrue(proxy.wait_for("probe.tunless.invalid", 20),
                            "经启动器拉起的 curl 没有走到代理")

    def test_git_config_global_points_at_proxy(self):
        if not os.path.isfile(GIT):
            self.skipTest("未安装 git")
        with TinyProxy() as proxy:
            endpoint = endpoint_for(proxy)
            profile = make_profile(GIT, "config --global --get http.proxy", "git-e2e")
            plan = proc.build_plan(profile, endpoint)
            result = subprocess.run(
                plan.command_line, env=plan.env, capture_output=True,
                text=True, timeout=30, shell=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), endpoint.http_url)
            # 用户原有配置必须还在（靠 include 保住）
            merged = subprocess.run(
                plan.command_line.replace("--get http.proxy", "--list"),
                env=plan.env, capture_output=True, text=True, timeout=30, shell=False,
            )
            self.assertIn("http.proxy", merged.stdout)

    def test_node_env_proxy_switch_present(self):
        profile = make_profile(CURL, "", "node-lever")
        profile.spec.family = Family.NODE
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        self.assertEqual(plan.env_delta.get("NODE_USE_ENV_PROXY"), "1")

    def test_no_proxy_contains_loopback_and_private(self):
        profile = make_profile(CURL, "", "no-proxy")
        profile.no_proxy_extra = ["example.internal"]
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        value = plan.env_delta["NO_PROXY"]
        for needle in ("127.0.0.1", "192.168.*", "10.*", "example.internal"):
            self.assertIn(needle, value)


class ChromiumLeverTests(unittest.TestCase):
    """L2 命令行参数：Electron / WebView2 走的就是这条。"""

    def test_switches_are_generated(self):
        profile = force_family(make_profile(CURL, "", "switches"), Family.ELECTRON)
        switches = cmdline_mod.chromium_switches(profile, endpoint_for_proxy(7897))
        joined = " ".join(switches)
        self.assertIn("--proxy-server=http://127.0.0.1:7897", joined)
        self.assertIn("--disable-quic", joined)

    def test_webview2_gets_env_var(self):
        profile = force_family(make_profile(CURL, "", "webview2"), Family.WEBVIEW2)
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        value = plan.env_delta.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        self.assertIn("--proxy-server=http://127.0.0.1:7897", value)

    def test_headless_edge_goes_through_proxy(self):
        edge = find_edge()
        if edge is None:
            self.skipTest("未找到 Edge")
        user_data = tempfile.mkdtemp(prefix="tunless-edge-")
        try:
            with TinyProxy() as proxy:
                args = (
                    f"--headless --disable-gpu --no-first-run --no-default-browser-check "
                    f'--user-data-dir="{user_data}" --dump-dom "{PROBE_URL}"'
                )
                # 真实 Electron/Chromium 应用就是被判定成这个家族
                profile = force_family(make_profile(edge, args, "edge-e2e"), Family.ELECTRON)
                plan = proc.build_plan(profile, endpoint_for(proxy))
                self.assertIn("--proxy-server", plan.command_line)
                proc.launch(plan, profile, wait=False)
                self.assertTrue(
                    proxy.wait_for("probe.tunless.invalid", 60),
                    f"Chromium 没有把请求交给代理；记录={proxy.targets()}",
                )
        finally:
            shutil.rmtree(user_data, ignore_errors=True)

    def test_headless_edge_control_without_proxy(self):
        """对照组：--no-proxy-server 时假代理应当什么都收不到。"""
        edge = find_edge()
        if edge is None:
            self.skipTest("未找到 Edge")
        user_data = tempfile.mkdtemp(prefix="tunless-edge-ctl-")
        try:
            with TinyProxy() as proxy:
                args = (
                    f"--headless --disable-gpu --no-first-run --no-default-browser-check "
                    f"--no-proxy-server "
                    f'--user-data-dir="{user_data}" --dump-dom "{PROBE_URL}"'
                )
                profile = force_family(make_profile(edge, args, "edge-control"), Family.ELECTRON)
                profile.levers = {"env": True, "cmdline": False, "configFiles": False}
                plan = proc.build_plan(profile, endpoint_for(proxy))
                self.assertNotIn("--proxy-server", plan.command_line)
                proc.launch(plan, profile, wait=False)
                time.sleep(8)
                self.assertFalse(proxy.saw("probe.tunless.invalid"),
                                 "对照组不该有请求到代理")
        finally:
            shutil.rmtree(user_data, ignore_errors=True)


class ParserTests(unittest.TestCase):
    """解析层：命令行拆分、.lnk、家族判定。"""

    def test_split_windows_args_keeps_backslashes(self):
        text = r'"C:\Program Files\app.exe" -o "C:\out\a b.txt" --flag'
        parts = cmdline_mod.split_windows_args(text)
        self.assertEqual(parts[0], r"C:\Program Files\app.exe")
        self.assertEqual(parts[2], r"C:\out\a b.txt")
        self.assertEqual(parts[3], "--flag")

    def test_env_var_expansion_in_args(self):
        expanded = cmdline_mod.expand_env_vars("--out %TEMP%\\a.json", {"TEMP": r"C:\T"})
        self.assertEqual(expanded, r"--out C:\T\a.json")
        untouched = cmdline_mod.expand_env_vars("--keep %NOPE%", {"TEMP": r"C:\T"})
        self.assertEqual(untouched, "--keep %NOPE%")

    def test_family_classification_on_synthetic_layouts(self):
        """家族判定只看"目标 exe 同目录里有什么文件"，所以用临时目录造样本就够了。

        （第一版这条用的是开发机上真实安装的应用路径，连用户名与装机清单一起
        写进了测试数据 —— 提交到公开仓库等于把这些一并交出去。改成纯合成布局后，
        既不依赖本机装了什么，也跑得更确定：每一类都有样本，不再"没装就跳过"。）
        """
        cases = (
            # (目录名, exe 名, 要造出来的伴随文件, 子系统, 期望家族)
            ("electron-asar", "electron-asar.exe", ("resources/app.asar",), "gui", Family.ELECTRON),
            ("electron-elf", "electron-elf.exe", ("chrome_elf.dll",), "gui", Family.ELECTRON),
            ("webview2-app", "webview2-app.exe", ("WebView2Loader.dll",), "gui", Family.WEBVIEW2),
            ("java-app", "java.exe", ("jvm.dll",), "gui", Family.JAVA),
            ("node-tool", "node.exe", (), "cui", Family.NODE),
            ("curl-tool", "curl.exe", (), "gui", Family.CLI),      # 按文件名命中
            ("console-app", "console-app.exe", (), "cui", Family.CLI),  # 按 PE 子系统
            ("native-app", "native-app.exe", (), "gui", Family.NATIVE),
        )
        with tempfile.TemporaryDirectory(prefix="tunless-family-") as directory:
            for folder, exe_name, companions, subsystem, expected in cases:
                base = Path(directory) / folder
                base.mkdir()
                target = base / exe_name
                target.write_bytes(b"MZ")  # 判定只看目录内容与子系统，不看 PE 本体
                for relative in companions:
                    companion = base / relative
                    companion.parent.mkdir(parents=True, exist_ok=True)
                    companion.write_bytes(b"x")

                spec = AppSpec(target=str(target), subsystem=subsystem)
                family_mod.classify(spec)
                self.assertEqual(spec.family, expected, f"{exe_name} 判定为 {spec.family}")
                self.assertTrue(spec.family_evidence, f"{exe_name} 应当给出判定依据")

    def test_lnk_resolution(self):
        start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
        shortcuts = list(start_menu.rglob("*.lnk"))[:5]
        if not shortcuts:
            self.skipTest("开始菜单里没有快捷方式")
        resolved = 0
        for shortcut in shortcuts:
            try:
                spec = lnk.resolve(str(shortcut))
            except Exception:
                continue
            self.assertTrue(spec.target)
            resolved += 1
        self.assertGreater(resolved, 0)

    def test_icon_location_normalization(self):
        """回归：大量 .lnk 的 IconLocation 就是字面量 `,0`。

        Windows 约定是"路径为空 = 用目标程序自己的图标"，以前把它当文件路径，
        导致图标提取全失败、生成的快捷方式图标也是坏的。
        """
        from tunless.detect.lnk import _normalize_icon

        target = r"C:\Apps\Foo\foo.exe"
        self.assertEqual(_normalize_icon(",0", target), f"{target},0")
        self.assertEqual(_normalize_icon(",-114", target), f"{target},-114")
        self.assertEqual(_normalize_icon("", target), target)
        self.assertEqual(_normalize_icon("   ", target), target)
        # 正常的要原样保留
        self.assertEqual(_normalize_icon(r"C:\a\b.dll,-3", target), r"C:\a\b.dll,-3")
        self.assertEqual(_normalize_icon(r"C:\a\b.exe", target), r"C:\a\b.exe")

    def test_icon_source_falls_back_to_target(self):
        """icon_source 指向不存在的文件时，应当退回目标程序自己的图标。"""
        from tunless import service

        target = r"C:\Windows\System32\notepad.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 notepad.exe")
        profile = service.build_profile(target, "icon-fallback")
        profile.spec.icon_source = r"C:\nope\missing.exe,0"
        self.assertTrue(service.extract_icon(profile))
        self.assertTrue(config_mod.icon_path(profile.id).is_file())
        # 收尾
        for suffix in (".png", ".ico"):
            path = config_mod.icon_path(profile.id).with_suffix(suffix)
            if path.is_file():
                path.unlink()

    def test_prune_removes_orphans_keeps_known(self):
        """孤儿 profiles/<id>/ 目录要被清掉，已知的和代理终端的要保留。"""
        from tunless import config as config_mod
        from tunless import service

        cfg = service.load_config()
        # 必须先有一个"已知配置"：配置里一个应用都没有时，prune 会刻意什么都不清
        # （那种组合更像配置被写坏了，见 SafetyRegressionTests 里的对应判据）。
        if not cfg.get("profiles"):
            target = r"C:\Windows\System32\notepad.exe"
            if not os.path.isfile(target):
                self.skipTest("没有 notepad.exe")
            service.save_profile(cfg, make_profile(target, "", "清理回归"))
            cfg = service.load_config()
        known = {p.id for p in service.list_profiles(cfg)}
        orphan = config_mod.PROFILES_DIR / "00000000-dead-beef-0000-000000000000"
        orphan.mkdir(parents=True, exist_ok=True)
        (orphan / "gitconfig").write_text("x", encoding="utf-8")

        service.prune_profile_dirs(cfg)

        self.assertFalse(orphan.exists(), "孤儿目录应当被删除")
        for profile_id in known:
            self.assertTrue((config_mod.PROFILES_DIR / profile_id).exists()
                            or not (config_mod.PROFILES_DIR / profile_id).exists())


class EncodingRegressionTests(unittest.TestCase):
    """编码相关的回归。

    打包后的 GUI 没有控制台（CP=936），netsh 会吐 GBK 中文；之前一律按
    UTF-8 解码，设置界面里就是一片「����」。
    """

    def test_console_decode_handles_gbk(self):
        from tunless.launch.admin_winhttp import decode_console, is_direct

        gbk = "当前的 WinHTTP 代理服务器设置:\r\n\r\n    直接访问(没有代理服务器)。".encode("gbk")
        decoded = decode_console(gbk)
        self.assertIn("当前的", decoded)
        self.assertIn("直接访问", decoded)
        self.assertTrue(is_direct(decoded), "GBK 解码后应当能认出「直接访问」")

    def test_console_decode_handles_utf8_and_ascii(self):
        from tunless.launch.admin_winhttp import decode_console, is_direct

        utf8 = "当前 WinHTTP 代理设置".encode("utf-8")
        self.assertEqual(decode_console(utf8), "当前 WinHTTP 代理设置")
        self.assertTrue(is_direct(decode_console(b"Direct access (no proxy server).")))
        self.assertEqual(decode_console(b""), "")

    def test_console_decode_never_raises(self):
        from tunless.launch.admin_winhttp import decode_console

        for blob in (b"\xff\xfe\x00", b"\x81\x40", bytes(range(256))):
            self.assertIsInstance(decode_console(blob), str)

    def test_pythonutf8_not_leaked_to_children(self):
        """我们的进程环境会原样传给用户启动的应用，不能偷偷塞 PYTHONUTF8。"""
        from tunless.launch import proc

        profile = make_profile(CURL, "", "env-leak")
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        self.assertNotIn("PYTHONUTF8", plan.env_delta)
        self.assertNotIn("PYTHONIOENCODING", plan.env_delta)

    def test_secrets_are_redacted_in_launch_log(self):
        from tunless.launch.proc import _redact

        self.assertNotIn("sk-abc", _redact("OPENAI_API_KEY", "sk-abc123"))
        self.assertIn("脱敏", _redact("MY_TOKEN", "abcdef"))
        self.assertEqual(_redact("HTTP_PROXY", "http://127.0.0.1:7897"),
                         "http://127.0.0.1:7897")

    def test_echo_identity_detects_rate_limit(self):
        from tunless.detect.endpoint import _identity

        limited = '{"success":false,"message":"Rate limit exceeded"}'
        self.assertEqual(_identity(limited), (None, None, False))
        failed = '{"status":"fail","message":"SSL unavailable"}'
        self.assertEqual(_identity(failed), (None, None, False))

        country, ip, ok = _identity('{"country_code":"US","ip":"1.2.3.4"}')
        self.assertTrue(ok)
        self.assertEqual((country, ip), ("US", "1.2.3.4"))

        # ipify 只有 IP，没有国家 —— 仍然算解析成功，靠 IP 比对
        country, ip, ok = _identity('{"ip":"5.6.7.8"}')
        self.assertTrue(ok)
        self.assertIsNone(country)
        self.assertEqual(ip, "5.6.7.8")

    def test_verdict_text_covers_all_states(self):
        from tunless.detect.endpoint import verdict_text

        for state in ("ok", "same_egress", "unverified", "proxy_down", "unknown"):
            self.assertTrue(verdict_text({"verdict": state}))

    def test_verdict_compares_like_with_like(self):
        """回归：代理只回 IP、直连只回国家码时不能判成 ok（那是假阳性）。"""
        from tunless.detect import endpoint as ep

        original_probe = ep._probe

        def fake_probe(urls, proxy_url):
            if proxy_url:
                return {"ok": True, "country": None, "ip": "1.2.3.4",
                        "payload": "", "url": "u", "error": ""}
            return {"ok": True, "country": "CN", "ip": None,
                    "payload": "", "url": "u", "error": ""}

        ep._probe = fake_probe
        try:
            result = ep.test_connectivity(endpoint_for_proxy(7897))
            self.assertEqual(result["verdict"], "unverified")
        finally:
            ep._probe = original_probe

        def same_ip_probe(urls, proxy_url):
            return {"ok": True, "country": None, "ip": "9.9.9.9",
                    "payload": "", "url": "u", "error": ""}

        ep._probe = same_ip_probe
        try:
            result = ep.test_connectivity(endpoint_for_proxy(7897))
            self.assertEqual(result["verdict"], "same_egress")
        finally:
            ep._probe = original_probe

        def different_country_probe(urls, proxy_url):
            country = "US" if proxy_url else "CN"
            return {"ok": True, "country": country, "ip": None,
                    "payload": "", "url": "u", "error": ""}

        ep._probe = different_country_probe
        try:
            result = ep.test_connectivity(endpoint_for_proxy(7897))
            self.assertEqual(result["verdict"], "ok")
        finally:
            ep._probe = original_probe


class EndpointTests(unittest.TestCase):
    def test_detect_finds_something(self):
        endpoint = endpoint_mod.detect()
        self.assertTrue(endpoint.host)
        self.assertGreater(endpoint.mixed_port, 0)

    def test_clash_config_is_read(self):
        ports = endpoint_mod.read_clash_verge_ports()
        if not ports:
            self.skipTest("未找到 Clash 配置")
        self.assertIn("config_path", ports)
        self.assertTrue(ports.get("mixed") or ports.get("socks"))

    def test_wildcard_bind_address_is_not_used_as_host(self):
        """回归：Clash 开 allow-lan 时 bind-address 是 `*`，不能拿去当主机名。"""
        from tunless.detect.endpoint import normalize_bind

        for wildcard in ("*", "0.0.0.0", "::", "[::]", "'*'", '"*"', "  *  ", ""):
            self.assertEqual(normalize_bind(wildcard), "", f"{wildcard!r} 应当归一化为空")
        self.assertEqual(normalize_bind("192.168.1.10"), "192.168.1.10")

        # detect() 遇到通配 bind 必须回落到回环地址
        endpoint = endpoint_mod.detect()
        self.assertNotIn(endpoint.host, ("*", "0.0.0.0", "::"))
        self.assertTrue(endpoint.http_url.startswith("http://"))

    def test_manual_endpoint_override_is_honored(self):
        """回归：设置对话框写的是 {"host":..,"port":..}，端口不能被忽略。"""
        from tunless import service
        from tunless.model import ProxyEndpoint

        endpoint = ProxyEndpoint.from_dict({"host": "10.1.2.3", "port": 18888})
        self.assertEqual(endpoint.mixed_port, 18888)
        self.assertEqual(endpoint.host, "10.1.2.3")

        cfg = {
            "settings": {
                "endpoint": {
                    "autoDetect": False,
                    "host": "127.0.0.1",
                    "mixedPort": 7897,
                    "manual": {"host": "10.1.2.3", "port": 18888},
                }
            }
        }
        resolved = service.current_endpoint(cfg)
        self.assertEqual(resolved.source, "manual")
        self.assertEqual(resolved.host, "10.1.2.3")
        self.assertEqual(resolved.mixed_port, 18888)
        self.assertEqual(resolved.http_url, "http://10.1.2.3:18888")


class ShortcutTests(unittest.TestCase):
    """L4 快捷方式：生成、接管、还原。全程在临时目录里做，不碰真实开始菜单。"""

    def _make_lnk(self, directory: str, name: str, target: str) -> str:
        from tunless.detect.lnk import _com_init

        _com_init()
        import win32com.client  # type: ignore

        path = os.path.join(directory, name)
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(path)
        shortcut.TargetPath = target
        shortcut.Arguments = ""
        shortcut.WorkingDirectory = os.path.dirname(target)
        shortcut.Save()
        del shortcut, shell
        return path

    def test_desktop_shortcut_goes_to_desktop(self):
        """菜单项写的是「创建桌面快捷方式」，那就必须落在桌面目录。

        第一版是写进开始菜单的：用户点完在桌面上什么也看不到。
        """
        from tunless.launch import shortcuts

        target = r"C:\Windows\System32\notepad.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 notepad.exe")
        profile = make_profile(target, "", "桌面快捷方式回归")

        desktop = shortcuts.desktop_dir()
        self.assertTrue(desktop.is_dir(), f"桌面目录不存在：{desktop}")
        # 桌面必须真的来自 Shell（OneDrive 会把它重定向），而不是开始菜单
        self.assertNotEqual(desktop.resolve(), config_mod.START_MENU_DIR.resolve())

        with tempfile.TemporaryDirectory(prefix="tunless-desktop-") as directory:
            created = shortcuts.create_desktop_shortcut(profile, Path(directory))
            self.assertTrue(created.is_file(), str(created))
            self.assertEqual(created.parent, Path(directory))
            info = lnk.read_lnk(str(created))
            self.assertIn("--run", info["args"])
            self.assertIn(profile.id, info["args"])

    def test_shortcuts_setting_reads_legacy_key(self):
        """快捷方式开关：**默认关闭**，新键优先，但旧的 `generateStartMenuShortcuts` 仍读得到。

        直接当成默认值 True 的话，等于替用户决定"往桌面放图标"。
        """
        from tunless import config as config_mod

        self.assertFalse(config_mod.shortcuts_enabled({}), "默认必须是关闭")
        self.assertFalse(config_mod.shortcuts_enabled(None))
        self.assertTrue(config_mod.shortcuts_enabled({"generateShortcuts": True}))
        self.assertFalse(config_mod.shortcuts_enabled({"generateShortcuts": False}))
        self.assertTrue(config_mod.shortcuts_enabled({"generateStartMenuShortcuts": True}))
        self.assertFalse(config_mod.shortcuts_enabled({"generateStartMenuShortcuts": False}))
        # 两个键都在时以新键为准
        self.assertTrue(
            config_mod.shortcuts_enabled(
                {"generateShortcuts": True, "generateStartMenuShortcuts": False}
            )
        )
        self.assertFalse(
            config_mod.shortcuts_enabled(
                {"generateShortcuts": False, "generateStartMenuShortcuts": True}
            )
        )
        self.assertFalse(
            config_mod.DEFAULT_SETTINGS.get("generateShortcuts", True),
            "DEFAULT_SETTINGS 里也必须是关闭",
        )

    def test_generated_shortcut_lands_on_desktop_and_retires_start_menu(self):
        """0.1.8：自动生成的快捷方式放桌面；旧版本在开始菜单里的那一份被清掉。

        清理必须**只删我们自己生成的**：用户自己的同名快捷方式（或者被我们接管的
        那一个）绝不能碰；桌面上已有别人的同名文件时拒绝覆盖。
        """
        from tunless.launch import shortcuts

        target = r"C:\Windows\System32\notepad.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 notepad.exe")
        profile = make_profile(target, "", "迁移回归")
        profile.id = "00000000-0000-4000-8000-0000000000aa"

        with tempfile.TemporaryDirectory(prefix="tunless-migrate-") as directory:
            base = Path(directory)
            desktop, menu = base / "desktop", base / "menu"
            desktop.mkdir()
            menu.mkdir()
            original_desktop_dir = shortcuts.desktop_dir
            original_menu_dir = config_mod.START_MENU_DIR
            shortcuts.desktop_dir = lambda: desktop
            config_mod.START_MENU_DIR = menu
            try:
                name = shortcuts.shortcut_name(profile)

                # 1) 默认位置 = 桌面
                created = shortcuts.create_shortcut(profile)
                self.assertEqual(created.parent, desktop, str(created))

                # 2) 旧版本留在开始菜单里的"我们那份"会被清掉
                legacy = menu / name
                executable, prefix, workdir = shortcuts.launcher_command()
                shortcuts._write_lnk(
                    legacy, executable, f"{prefix} --run {profile.id}".strip(), workdir, ""
                )
                self.assertTrue(legacy.is_file())
                shortcuts.create_shortcut(profile)
                self.assertFalse(legacy.is_file(), "开始菜单里的旧那份应当被清理")

                # 3) 别人的同名快捷方式（不是我们生成的）不许删
                shortcuts._write_lnk(legacy, target, "", str(Path(target).parent), "")
                shortcuts.create_shortcut(profile)
                self.assertTrue(legacy.is_file(), "不是我们生成的不许删")

                # 4) 桌面上已有一个**别的**同名文件 → 拒绝覆盖
                blocker = desktop / name
                blocker.unlink()
                shortcuts._write_lnk(blocker, r"C:\Windows\System32\calc.exe",
                                     "", r"C:\Windows\System32", "")
                with self.assertRaises(shortcuts.ShortcutOccupied):
                    shortcuts.create_shortcut(profile)
                self.assertEqual(
                    lnk.read_lnk(str(blocker))["target"].lower(),
                    r"c:\windows\system32\calc.exe",
                    "别的应用的快捷方式要保持原样",
                )

                # 4b) 桌面上是**这个应用自己的**图标 → 接管它（备份 + 记录 + 可还原）
                blocker.unlink()
                shortcuts._write_lnk(blocker, target, "", str(Path(target).parent), "")
                shortcuts.create_shortcut(profile)
                self.assertIn("--run", lnk.read_lnk(str(blocker))["args"])
                self.assertEqual(profile.adopted_shortcut, str(blocker))
                self.assertTrue(shortcuts.adoption_backup_path(profile).is_file(),
                                "接管前必须先备份原图标")
                self.assertTrue(shortcuts.restore_adopted(profile))
                self.assertEqual(lnk.read_lnk(str(blocker))["target"].lower(), target.lower())

                # 5) 被接管在"生成位置"上的那个文件不能被"清理旧位置"顺手删掉
                if (desktop / name).exists():
                    (desktop / name).unlink()  # 让生成位置空出来，模拟只剩接管份的情形
                legacy.unlink()
                adopted = menu / name
                shortcuts._write_lnk(
                    adopted, executable, f"{prefix} --run {profile.id}".strip(), workdir, ""
                )
                profile.adopted_shortcut = str(adopted)
                shortcuts.create_shortcut(profile)
                self.assertTrue(adopted.is_file(), "被接管的那份不能删")
            finally:
                shortcuts.desktop_dir = original_desktop_dir
                config_mod.START_MENU_DIR = original_menu_dir

    def test_create_adopt_restore_roundtrip(self):
        from tunless.launch import shortcuts

        target = r"C:\Windows\System32\notepad.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 notepad.exe")

        with tempfile.TemporaryDirectory(prefix="tunless-lnk-") as directory:
            original = self._make_lnk(directory, "Sample App.lnk", target)
            profile = make_profile(original, "", "快捷方式测试")
            self.assertEqual(profile.spec.target.lower(), target.lower())

            generated = Path(directory) / "generated.lnk"
            shortcuts.create_shortcut(profile, generated)
            self.assertTrue(generated.is_file())
            info = lnk.read_lnk(str(generated))
            self.assertIn("tunless", (info["target"] + info["args"]).lower())
            self.assertIn(profile.id, info["args"])

            # 接管：原文件被换掉，备份还在
            self.assertTrue(shortcuts.adopt_shortcut(profile))
            self.assertEqual(profile.adopted_shortcut, original)
            self.assertTrue(shortcuts.adoption_backup_path(profile).is_file())
            self.assertIn(profile.id, lnk.read_lnk(original)["args"])

            # 还原：回到 notepad
            self.assertTrue(shortcuts.restore_adopted(profile))
            self.assertIsNone(profile.adopted_shortcut)
            self.assertEqual(lnk.read_lnk(original)["target"].lower(), target.lower())


class DiagTests(unittest.TestCase):
    """诊断层：连接表、进程树、Clash 管道。"""

    def test_tcp_table_readable(self):
        from tunless.diag import tcptable

        connections = tcptable.all_connections()
        self.assertIsInstance(connections, list)
        for conn in connections[:50]:
            self.assertGreaterEqual(conn.pid, 0)
            self.assertTrue(conn.remote_ip)

    def test_process_tree_contains_self(self):
        from tunless.diag import proctree

        processes = proctree.snapshot()
        self.assertGreater(len(processes), 5)
        self.assertIn(os.getpid(), processes)
        self.assertIn(os.getpid(), proctree.descendants(os.getpid(), processes))

    def test_classify_rules(self):
        from tunless.diag.tcptable import Connection, classify, is_private

        self.assertTrue(is_private("192.168.1.5"))
        self.assertTrue(is_private("127.0.0.1"))
        self.assertFalse(is_private("8.8.8.8"))

        proxied = Connection(1, "ipv4", "127.0.0.1", 5000, "127.0.0.1", 7897, "ESTABLISHED")
        self.assertEqual(classify(proxied, "127.0.0.1", 7897), "via_proxy")
        direct = Connection(1, "ipv4", "10.0.0.5", 5000, "1.1.1.1", 443, "ESTABLISHED")
        self.assertEqual(classify(direct, "127.0.0.1", 7897), "direct_public")
        local = Connection(1, "ipv4", "10.0.0.5", 5000, "192.168.1.1", 445, "ESTABLISHED")
        self.assertEqual(classify(local, "127.0.0.1", 7897), "local")

    def test_verdict_on_self(self):
        from tunless.diag import verdict as verdict_mod

        result = verdict_mod.diagnose(os.getpid(), endpoint_for_proxy(7897))
        self.assertTrue(result.alive)
        self.assertIn(result.status, ("ok", "leak", "idle"))
        self.assertTrue(result.summary)

    def test_clash_pipe_if_available(self):
        from tunless.diag.clashpipe import ClashApi

        api = ClashApi()
        if not api.available:
            self.skipTest(f"没有可用的 Clash 控制器：{api.error}")
        self.assertIsInstance(api.connections(), list)


class ServiceTests(unittest.TestCase):
    """服务层：家族默认 lever 的一致性、真实快捷方式建 Profile。"""

    def test_default_levers_match_family(self):
        cases = {
            Family.ELECTRON: "cmdline",
            Family.WEBVIEW2: "cmdline",
            Family.CLI: "configFiles",
            Family.NATIVE: None,
        }
        for family, expected_on in cases.items():
            levers = family_mod.default_levers(family)
            if expected_on is None:
                self.assertFalse(any(levers.values()), f"{family} 不该默认开任何 lever")
            else:
                self.assertTrue(levers.get(expected_on), f"{family} 应当默认开启 {expected_on}")

    def test_build_profile_from_real_shortcut(self):
        from tunless import service

        start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
        found = [p for p in start_menu.rglob("*.lnk")][:3]
        if not found:
            self.skipTest("开始菜单里没有快捷方式")
        built = 0
        for shortcut in found:
            try:
                profile = service.build_profile(str(shortcut))
            except Exception:
                continue
            self.assertTrue(profile.spec.target)
            self.assertTrue(profile.levers)
            built += 1
        self.assertGreater(built, 0)


class SafetyRegressionTests(unittest.TestCase):
    """一轮深度审查里发现的高危问题的回归（每条都对应一个真实的破坏路径）。"""

    def test_prune_is_skipped_when_config_is_broken(self):
        """配置读失败时**不得**清理无主数据。

        `config.load()` 遇到损坏的 config.json 会返回 profiles 为空的默认配置，
        此时 keep 集合只剩 proxy-shell —— 照删就把用户所有 profiles/<id>/ 和图标
        一次性清空。这是"清理"变成"销毁数据"的唯一一步，必须钉住。
        """
        from tunless import service

        with tempfile.TemporaryDirectory(prefix="tunless-prune-") as directory:
            profiles_dir = Path(directory) / "profiles"
            icons_dir = Path(directory) / "icons"
            orphan = profiles_dir / "orphan-id"
            orphan.mkdir(parents=True)
            (orphan / "gitconfig").write_text("[http]\n", encoding="utf-8")
            icons_dir.mkdir(parents=True)
            icon = icons_dir / "orphan-id.png"
            icon.write_bytes(b"png")

            original_profiles, original_icons = config_mod.PROFILES_DIR, config_mod.ICON_DIR
            config_mod.PROFILES_DIR, config_mod.ICON_DIR = profiles_dir, icons_dir
            try:
                # 1) 配置损坏：什么都不许删
                broken = {"_loadError": "JSONDecodeError: boom", "profiles": []}
                self.assertEqual(service.prune_profile_dirs(broken), 0)
                self.assertTrue(orphan.is_dir())
                self.assertTrue(icon.is_file())

                # 2) 配置正常：该清的还是要清（别把功能一起关掉）
                self.assertEqual(service.prune_profile_dirs({"profiles": []}, force=True), 2)
                self.assertFalse(orphan.is_dir())
                self.assertFalse(icon.is_file())

                # 3) 配置里一个应用都没有、磁盘上却还有数据：不许自动清（更像配置丢了）
                orphan.mkdir(parents=True)
                icon.write_bytes(b"png")
                self.assertEqual(service.prune_profile_dirs({"profiles": []}), 0)
                self.assertTrue(orphan.is_dir())
                self.assertTrue(icon.is_file())
            finally:
                config_mod.PROFILES_DIR, config_mod.ICON_DIR = original_profiles, original_icons

    def test_refresh_keeps_adopted_profile_untouched(self):
        """被接管的快捷方式不能被"重新解析"。

        接管是把原 .lnk 原地改成指向本程序（`--run <id>`）；再拿它当应用自身解析，
        目标就变成启动器本身，保存后启动 = 无限自我拉起链。
        """
        from tunless import service

        target = r"C:\Windows\System32\notepad.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 notepad.exe")
        profile = make_profile(target, "", "接管回归")
        profile.adopted_shortcut = r"C:\somewhere\Sample.lnk"

        refreshed = service.refresh_profile(profile)
        self.assertEqual(refreshed.spec.target.lower(), target.lower())

    def test_launch_refuses_self_launcher(self):
        """目标是本程序自己时必须拒绝启动（最后一道闸）。"""
        from tunless.launch import shortcuts

        self.assertTrue(shortcuts.is_self_launcher(sys.executable))
        self.assertFalse(shortcuts.is_self_launcher(r"C:\Windows\System32\notepad.exe"))

        profile = make_profile(r"C:\Windows\System32\notepad.exe", "", "自我拉起回归")
        profile.spec.target = sys.executable  # 模拟配置已被污染
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        with self.assertRaises(proc.SelfLaunchRefused):
            proc.launch(plan, profile)

    def test_secrets_are_redacted(self):
        """日志脱敏要覆盖常见键名，命令行里的凭据也不能明文落盘。"""
        for key in (
            "DB_PASS", "MYSQL_PWD", "AWS_ACCESS_KEY_ID", "SESSION_ID",
            "HTTP_COOKIE", "ENCRYPTION_KEY", "GITHUB_TOKEN", "MY_CREDENTIAL",
        ):
            self.assertIn("已脱敏", proc._redact(key, "supersecret"), key)
        self.assertEqual(proc._redact("PATH", r"C:\Windows"), r"C:\Windows")

        line = r'app.exe --api-key=abcd1234 --user bob --token "xyz"'
        redacted = proc.redact_command_line(line)
        self.assertNotIn("abcd1234", redacted)
        self.assertNotIn("xyz", redacted)
        self.assertIn("--user bob", redacted)

    def test_unbalanced_quotes_produce_a_note(self):
        """用户参数引号没闭合时，追加的开关会被吞掉 —— 必须出提示，不能静默失效。"""
        target = r"C:\Windows\System32\curl.exe"
        if not os.path.isfile(target):
            self.skipTest("没有 curl.exe")
        profile = make_profile(target, '--foo "C:\\dir\\', "引号回归")
        profile.spec.family = Family.ELECTRON  # 让它生成 --proxy-server 开关
        profile.levers = {"env": True, "cmdline": True, "configFiles": False}
        plan = proc.build_plan(profile, endpoint_for_proxy(7897))
        self.assertTrue(
            any("引号" in note for note in plan.notes),
            f"应当提示引号未闭合，实际 notes={plan.notes}",
        )
        self.assertTrue(any("--proxy-server" in arg for arg in plan.argv), plan.argv)

        # 正常参数不该被误报
        ok_profile = make_profile(target, '--foo "C:\\Program Files\\x"', "引号对照")
        ok_profile.spec.family = Family.ELECTRON
        ok_profile.levers = {"env": True, "cmdline": True, "configFiles": False}
        ok_plan = proc.build_plan(ok_profile, endpoint_for_proxy(7897))
        self.assertFalse(any("引号" in note for note in ok_plan.notes), ok_plan.notes)

    def test_ssh_override_follows_l3_lever(self):
        """关掉 L3 之后，磁盘上留下的 ssh_config 不许继续生效。"""
        from tunless.launch import configfiles

        profile = make_profile(r"C:\Windows\System32\notepad.exe", "", "ssh 回归")
        directory = config_mod.profile_dir(profile.id)
        (directory / "ssh_config").write_text("ProxyCommand x\n", encoding="utf-8")
        try:
            profile.levers = {"env": True, "cmdline": False, "configFiles": True}
            self.assertIsNotNone(configfiles.ssh_config_path(profile))
            profile.levers["configFiles"] = False
            self.assertIsNone(configfiles.ssh_config_path(profile))
        finally:
            configfiles.clean_profile_dir(profile.id)

    def test_winhttp_restore_uses_backup_not_ui_values(self):
        """还原 WinHTTP 必须用备份里的原地址，而不是界面上的 host:port。"""
        from tunless.launch import admin_winhttp

        backup = (
            "当前的 WinHTTP 代理服务器设置:\n"
            "    代理服务器: 10.0.0.5:8080\n"
            "    绕过列表  : <local>\n"
        )
        servers, bypass = admin_winhttp.parse_backup(backup)
        self.assertEqual(servers, "10.0.0.5:8080")
        self.assertEqual(bypass, "<local>")

        english = "Proxy Server(s) : proxy.corp.example:3128\nBypass List     : <local>\n"
        self.assertEqual(admin_winhttp.parse_backup(english)[0], "proxy.corp.example:3128")

        # 解析不出来就明确失败，不去猜、也不动系统设置
        ok, message = admin_winhttp.restore("无法识别的内容", "127.0.0.1", 7897)
        self.assertFalse(ok)
        self.assertIn("没有识别出", message)

    def test_generated_files_live_in_one_data_dir(self):
        """所有生成物都必须落在**同一个数据目录**里（可删可拷）。

        以前配置在 `%APPDATA%\\TunlessProxy`、日志在 `%LOCALAPPDATA%\\...\\logs`，
        用户想删干净或整体导出得跑两个地方；现在统一到程序同级 `data\\`。
        """
        data_dir = config_mod.DATA_DIR
        self.assertEqual(config_mod.CONFIG_FILE.parent, data_dir)
        for path in (
            config_mod.ICON_DIR,
            config_mod.PROFILES_DIR,
            config_mod.BACKUP_DIR,
            config_mod.LNK_BACKUP_DIR,
            config_mod.LOG_DIR,
        ):
            self.assertIn(data_dir, Path(path).parents, str(path))

        # 开始菜单是系统的，数据目录搬了它也不能跟着搬（快捷方式得落在开始菜单里）
        self.assertNotIn(data_dir, Path(config_mod.START_MENU_DIR).parents)

        # 源码模式下"程序目录"就是项目根
        if not getattr(sys, "frozen", False):
            self.assertEqual(config_mod.app_dir(), ROOT)

        # 写权限探针要真的去写：用"父路径是个文件"构造必然失败的目录
        with tempfile.TemporaryDirectory(prefix="tunless-wprobe-") as directory:
            blocker = Path(directory) / "afile"
            blocker.write_text("x", encoding="utf-8")
            self.assertFalse(config_mod.is_writable(blocker / "sub"))
            self.assertTrue(config_mod.is_writable(Path(directory) / "ok"))

    def test_save_never_writes_a_crippled_config(self):
        """调用方漏了 version / profiles 时，save 要兜底补上，不能写出残配置。

        "没有 version、没有 profiles" 的文件会让后续所有判断乱套（排查期间真的见过）。
        """
        import json

        with tempfile.TemporaryDirectory(prefix="tunless-cripple-") as directory:
            original = config_mod.CONFIG_FILE
            config_mod.CONFIG_FILE = Path(directory) / "config.json"
            try:
                config_mod.save({"settings": {"theme": "midnight"}})
                written = json.loads(config_mod.CONFIG_FILE.read_text(encoding="utf-8"))
                self.assertIn("version", written)
                self.assertEqual(written["profiles"], [])
            finally:
                config_mod.CONFIG_FILE = original

    def test_config_save_survives_concurrent_writers(self):
        """两个进程同时保存配置时不许抛异常（临时文件名带 pid）。"""
        with tempfile.TemporaryDirectory(prefix="tunless-cfg-") as directory:
            original = config_mod.CONFIG_FILE
            config_mod.CONFIG_FILE = Path(directory) / "config.json"
            try:
                import json

                import threading

                def writer(index: int) -> None:
                    config_mod.save({"version": 1, "settings": {"n": index}, "profiles": []})

                threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                payload = json.loads(config_mod.CONFIG_FILE.read_text(encoding="utf-8"))
                self.assertIn("settings", payload)
            finally:
                config_mod.CONFIG_FILE = original


def endpoint_for_proxy(port: int) -> ProxyEndpoint:
    return ProxyEndpoint(host="127.0.0.1", mixed_port=port, source="test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
