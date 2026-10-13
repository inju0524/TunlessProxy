"""TunlessProxy —— 免 TUN、零注入的按应用代理启动器。

设计约束（见 README）：
  * 不使用 TUN/TAP/WFP 驱动；
  * 不向目标进程注入任何代码；
  * 所有覆盖能力来自"启动时施加的、作用域限于该进程树的零注入手段"：
    环境变量(L1)、命令行参数(L2)、配置文件指针(L3)、快捷方式(L4)、
    以及可选的机器级开关(L5)。
"""

__version__ = "0.1.10"
APP_NAME = "TunlessProxy"

# ---------------------------------------------------------------- 作者与许可
# 「关于」页、README 与测试都读这一份，避免改了一处漏一处。

__author__ = "INJU银烛"
__url__ = "https://github.com/inju0524"
__url_label__ = "github.com/inju0524"
__license__ = "MIT"
__license_label__ = "MIT License"
__copyright__ = "© 2026 INJU银烛"

#: 关于页上的两句话：第一句说它是干什么的，第二句是态度。
__tagline__ = "把快捷方式拖进来，以后从它启动就走代理"
__tagline2__ = "去他妈的 TUN 模式"
