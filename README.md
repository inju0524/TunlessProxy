# TunlessProxy

**免 TUN 驱动、零注入的按应用代理启动器**　·　Per-app proxy launcher for Windows — no TUN driver, no code injection.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg)](#环境要求)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](#技术栈)
[![UI](https://img.shields.io/badge/UI-PyQt6-41CD52.svg)](#技术栈)
[![No driver](https://img.shields.io/badge/TUN%2FWFP%20driver-not%20required-success.svg)](#项目简介)

---

## 项目简介

Clash / mihomo 的 **TUN 模式**要装虚拟网卡、改全局路由，既影响整机、又常和
杀软、VPN、WSL、Docker 打架。而**系统代理**只对读 WinINET/WinHTTP 的程序有效 ——
Electron 应用、`git`、`npm`、`pip`、`curl` 这些往往根本不看它。

TunlessProxy 换个思路：**不动系统、不动目标进程，只在"启动应用"这一步做手脚**。

把快捷方式（或 exe）拖进窗口 → 以后从本程序、或从它生成的快捷方式启动这个应用 →
**只有这个应用**的流量走你的代理。关掉它就恢复原样，整机路由与系统设置全程没被改过。

> 一句话：**不用 TUN 模式，也能让指定的几个应用走代理。**

## 功能特性

**五种"杠杆"，按应用类型自动选**（判定依据是目标 exe 同目录里的特征文件 + PE 子系统）

| | 手段 | 覆盖的应用 |
|---|---|---|
| **L1** | 环境变量 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY` | Go / Rust / Python / Node / .NET Core / curl / git / npm / pip / cargo |
| **L2** | 命令行参数 `--proxy-server` / `--host-resolver-rules` / `--disable-quic` | Electron / Chromium / WebView2 应用（它们不读代理环境变量） |
| **L3** | 私有配置文件指针（`GIT_CONFIG_GLOBAL` / `NPM_CONFIG_USERCONFIG` / `PIP_CONFIG_FILE` …） | git / npm / pip / curl / wget / docker / ssh —— **不改你的真实配置** |
| **L4** | 快捷方式：生成独立入口，或**接管原图标**（可一键还原） | 想"点原图标就走代理"的场合 |
| **L5** | 机器级 `netsh winhttp set proxy`（可选、需管理员） | 只走 WinHTTP 的原生应用（全机生效，谨慎使用） |

**其它**

- **四套主题**：极光幻彩（默认）/ 深空曜石 / 微晶雾面 / 超白水晶（浅色），即时切换
- **轻量便携模式**：340×385 的小启动器，常驻桌面角落
- **诊断中心**：连接表、进程树、Clash 管道、启动日志、代理连通性（经代理 vs 直连对照）
- **数据便携**：所有生成物都在程序同级的 `data\`，删/导出只需处理一个文件夹
- **启动日志**：记录实际用到的层、注入的每个环境变量、生成的配置文件、PID 与退出码，并**按关键字脱敏**（不记 token）
- **命令行齐全**：`--add / --list / --run / --remove / --doctor / --repair / --test / --shell / --diagnose`

## 截图

| 完整界面（极光幻彩） | 轻量便携模式 |
|---|---|
| ![完整界面](docs/screenshot-main.png) | ![轻量便携模式](docs/screenshot-compact.png) |

| 设置 | 关于 |
|---|---|
| ![设置](docs/screenshot-settings.png) | ![关于](docs/screenshot-about.png) |

## 技术栈

- **语言 / 运行时**：Python 3.10+（开发与打包用 3.12）
- **界面**：PyQt6（纯 Widgets，按主题动态生成 QSS；四套主题由 `theme_tokens` 统一供给）
- **Windows 集成**：pywin32（`win32com` 操作 `.lnk`、`win32gui`/`win32ui` 取图标、`win32file`）
- **PE 解析**：pefile（判断子系统、提取图标资源，用来决定施加哪些杠杆）
- **打包**：PyInstaller 6.x，onedir、不开 UPX（两个 exe：窗口化 + 控制台）
- **不依赖**：没有 TUN/TAP/WFP 驱动、没有 DLL 注入、没有 hook、没有常驻服务

## 环境要求

| | 要求 |
|---|---|
| 系统 | Windows 10 1809+ / Windows 11（x64） |
| Python | 3.10 或更高（仅从源码运行/自行打包时需要） |
| 代理 | 本机有一个 HTTP 或 SOCKS 代理。默认按 **Clash Verge Rev / mihomo 的 `mixed-port`（7897）** 自动探测，也支持手动指定 |
| 权限 | **不需要**管理员。只有 L5（机器级 WinHTTP）需要 |
| 依赖 | `PyQt6` / `pywin32` / `pefile`（见 [`requirements.txt`](requirements.txt)） |

## 安装步骤

### 方式一：直接用打包好的程序（推荐）

1. 到 [Releases](https://github.com/inju0524/TunlessProxy/releases) 下载
   `TunlessProxy-<版本>-win64.zip`（约 63 MB），解压到任意可写目录
2. 双击 `TunlessProxy.exe` —— 无需安装、无需 Python、不需要管理员权限
3. 首次运行会在程序同级建一个 `data\` 文件夹放配置（不写注册表、不写系统目录）

> 移动/删除：整个文件夹一起拷走或删掉即可。**注意**：重新打包 `dist` 会连
> `dist\TunlessProxy\data\` 一起覆盖，升级前先把 `data\` 挪出来。
>
> 没有 release 或想自己构建，用下面两种方式。

### 方式二：从源码运行

```powershell
git clone https://github.com/inju0524/TunlessProxy.git
cd TunlessProxy
pip install -r requirements.txt
python tunless_entry.py           # 打开界面（等价于 python -m tunless --gui）
```

### 方式三：自己打包

```powershell
pip install pyinstaller
python -m PyInstaller --noconfirm --clean tunless.spec
python tests\verify_package.py     # 23 项打包验收
```

## 运行方式

**图形界面**：双击 `TunlessProxy.exe`（或 `python tunless_entry.py`）。
把快捷方式/exe **拖进窗口**即可添加；应用卡片上的「启动代理」按钮启动它。
关闭窗口默认驻留托盘，托盘菜单里可退出。

**命令行**（打包版是 `tunless.exe`，源码版是 `python -m tunless`）

```powershell
tunless.exe --add <路径> [<路径>…]   # 添加应用配置（--shortcut 才在桌面建独立快捷方式）
tunless.exe --list                   # 列出全部配置（--json 便于脚本处理）
tunless.exe --run <ID>               # 用代理启动某个应用（生成的快捷方式走的就是这条）
tunless.exe --remove <ID>            # 删除配置（会还原被接管的快捷方式）
tunless.exe --test                   # 测试代理端点：端口探活 + 经代理/直连出网对照
tunless.exe --doctor                 # 环境自检（数据目录、端点、权限、配置统计）
tunless.exe --repair                 # 重新解析全部配置并重建图标/快捷方式
tunless.exe --diagnose [ID]          # 看某次启动的连接与进程树
tunless.exe --shell                  # 打开一个已带代理环境的终端
tunless.exe --version                # 版本 + 作者 + 许可
```

## 配置说明

配置是一个 JSON 文件，位置固定在**程序同级的 `data\`** 里（源码运行则是项目根）：

```
<TunlessProxy.exe 所在目录>\data\config.json          全部配置
                            \data\icons\<id>.png/.ico  提取的图标
                            \data\profiles\<id>\       L3 生成的私有配置
                            \data\backup\lnk\          被接管快捷方式的原始备份
                            \data\logs\                启动日志、launches.jsonl、crash.log
```

常用键：

```jsonc
{
  "settings": {
    "endpoint": {                    // 代理端点；autoDetect=true 时自动探测 Clash
      "autoDetect": true,
      "host": "127.0.0.1", "mixedPort": 7897,
      "manual": null                 // {"host": "...", "port": 7897, "scheme": "http"|"socks5"}
    },
    "defaultLevers": { "env": true, "cmdline": true, "configFiles": true },
    "noProxyExtra": ["*.internal", "10.0.0.0/8"],   // 追加到 NO_PROXY
    "disableQuic": true,             // 注入 --disable-quic（UDP/443 无法走 TCP 代理）
    "forceRemoteDns": false,         // 注入 --host-resolver-rules，杜绝本地 DNS 泄漏
    "generateShortcuts": false,      // 添加新应用时是否在桌面建独立快捷方式（默认关）
    "theme": "aurora",               // aurora | midnight | frosted | pure-crystal
    "compactMode": false             // 以轻量便携模式启动
  },
  "profiles": [ /* 每个应用一条：目标、参数、工作目录、图标、启用的杠杆 */ ]
}
```

- **端点探测顺序**：Clash Verge 的 `clash-verge.yaml`（mihomo 实际在跑的合并配置）→
  注册表里的系统代理 → 探活 `7897/7898/7899/1080/10808/7890/2080`。
- **每个应用可以单独**改参数、工作目录与杠杆开关：「概览 → 配置」页里改，「诊断中心」页看效果。
- **数据目录不可写时**（比如装在 `C:\Program Files\`）会自动退回 `%APPDATA%\TunlessProxy\`，
  `--doctor` 里的 `dataDirSource` 会告诉你当前用的是哪种。

更细的说明（L1–L5 的注入细节、快捷方式"生成 vs 接管"的安全规则、日志字段、
`config.json` 全量键、已知问题）见 **[完整手册 MANUAL.md](MANUAL.md)**。

## 开发与测试

```powershell
python tests\run_all.py               # 单元 + 端到端（标准库 unittest，不需要 pytest）—— 49 项
python tests\check_layout.py          # 界面规格：布局、顶部软件名字标、关于页 —— 39 项
python tests\check_gui_robustness.py  # GUI 健壮性：槽异常不许 abort、按钮点击不许报错 —— 8 项
python tests\gui_smoke.py             # 把界面渲染成 PNG，确认布局没崩
python tests\capture_docs.py          # 用真实字体重新生成 docs/ 里的四张截图
python tests\verify_package.py        # 打包产物验收：对着 dist 里的 exe 跑真实链路 —— 23 项
```

这些判据刻意**不靠"看起来差不多"**：例如"打包版就是眼前这份源码"是把 exe 内嵌 PYZ 里
每个模块的字节码与源码逐字段比对；"顶部软件名是三段式"是抓真实窗口像素做颜色统计；
"请求到底有没有到达代理"用的是自带的假代理（记录收到的请求），而不是拿 ip-api 比对
出口 IP —— 后者会被系统代理干扰，证明不了什么。

## 已知限制

- **不提供全局透明代理**：按应用代理是设计目标，不做"整机所有流量都走代理"。
- **UWP / 商店应用**不支持（进程模型上无法在启动时施加手段）。
- **只走 WinHTTP 的原生应用**无法按应用覆盖 —— 这类只能用 L5（全机生效，需管理员）。
- **同名应用**的生成快捷方式会互相占用；搬到桌面后，第二个重名应用会被拒绝而不是覆盖。
- `config.json` 多进程共写时是"后写的赢"，极端情况下可能丢一次启动次数更新。
- 完整列表见 [MANUAL.md 的已知问题](MANUAL.md#已知问题)。

## 后续开发计划

**近期（0.2 系列）**

- [ ] 视觉一致性治理：家族徽章、顶栏图标、诊断表格里那几处硬编码颜色，改成随主题取值
      （目前浅色主题「超白水晶」下这几处对比度不理想）
- [ ] 诊断轮询移出 GUI 线程（现在最坏会卡一下界面），并补上 mihomo 管道的读超时
- [ ] 托盘菜单补齐模式/主题项；重命名应用后托盘里的旧名字立即刷新
- [ ] `config.json` 并发写改成带锁的合并式写入，消掉"后写的赢"

**中期**

- [ ] 配置一键导出/导入（把 `data\` 打成便携包，方便换机）
- [ ] L3 覆盖更多工具链（pnpm / yarn / cargo / go / nuget / gradle）
- [ ] 应用分组与"工作 / 娱乐"两套配置快速切换
- [ ] 启动前置检查：代理不通时给出可操作的提示，而不是等应用打不开网页

**再远一点 / 暂不考虑**

- [ ] 英文界面（i18n）：目前只有中文
- [ ] macOS / Linux 版本：思路类似（环境变量 + 独立启动器），但没有 Windows 这套
      shortcut/PE 集成，属于**另起一个项目**的量级，暂不打算做

有想法或 bug 欢迎在 [Issues](https://github.com/inju0524/TunlessProxy/issues) 提。

## 作者与许可

![关于页](docs/screenshot-about.png)

- **作者**：INJU银烛
- **GitHub**：<https://github.com/inju0524>
- **许可**：[MIT](LICENSE) —— 可自由使用、修改、分发（包括商用），保留版权声明即可
- **版权**：© 2026 INJU银烛

> 这是一个**按应用**施加代理的启动器，不装 TUN/TAP/WFP 驱动，也不向目标进程注入代码。
> 它不提供"全局透明代理"，也不替你决定合规性 —— 请自行遵守所在地法律法规与所用软件的许可条款。
