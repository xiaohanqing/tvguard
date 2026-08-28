"""ADB 子进程封装。

通过无线 ADB（adb connect <ip>:5555）控制电视：
- 查询前台应用：dumpsys window / dumpsys activity
- 查询亮屏状态：dumpsys power / dumpsys display
- 关闭应用：am force-stop；回桌面：input keyevent HOME
"""
import logging
import re
import subprocess

logger = logging.getLogger("tvguard.adb")

# 形如 "mCurrentFocus=Window{... u0 com.pkg/com.pkg.MainActivity}"
_FOCUS_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)/[a-zA-Z0-9_.$]+")

# 常见电视应用包名 → 中文名（电视 App 多数无法通过 shell 拿到显示名，
# 用字典兜底；用户添加规则时填的名称也会被记住，见 store 的规则）。
KNOWN_APPS = {
    # 国内视频 TV 版
    "com.ktcp.video": "云视听极光（腾讯视频TV）",
    "com.gitv.dolphin": "银河奇异果（爱奇艺TV）",
    "com.gitv.dolphin.weishi": "银河奇异果（爱奇艺TV）",
    "com.hunantv.tv": "芒果TV（电视版）",
    "com.xiaodianshi.tv": "哔哩哔哩TV版",
    "com.dangbei.tvmarket": "当贝市场",
    # 雷鸟/TCL 系统应用（电视预装，非第三方，也在选择范围）
    "com.tcl.ffeducation": "雷鸟教育课堂",
    "com.tcl.article.news": "新闻头条",
    "com.tcl.tvoledgallery": "艺术画廊",
    # 海外流媒体（Android TV）
    "com.netflix.ninja": "Netflix",
    "com.google.android.youtube.tv": "YouTube",
    "com.disney.disneyplus": "Disney+",
    "com.amazon.amazonvideo.livingroom": "Prime Video",
}


def label_for(pkg: str) -> str:
    return KNOWN_APPS.get(pkg, "")


class AdbError(Exception):
    pass


class Adb:
    def __init__(self, adb_path: str, host: str):
        self.adb_path = adb_path
        self.host = host  # host:port

    def _run(self, *args, timeout: int = 10):
        cmd = [self.adb_path]
        if args and args[0] not in ("connect", "disconnect", "start-server"):
            cmd += ["-s", self.host]
        cmd += list(args)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout)
        except FileNotFoundError:
            raise AdbError(f"找不到 adb 可执行文件: {self.adb_path}，请安装 Android platform-tools")
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb 命令超时: {' '.join(args)}")
        return p.returncode, p.stdout or "", p.stderr or ""

    def shell(self, command: str, timeout: int = 10) -> str:
        rc, out, err = self._run("shell", command, timeout=timeout)
        blob = (out + err).lower()
        if rc != 0 or "no devices" in blob or "device offline" in blob \
                or "not found" in blob or "error:" in blob:
            # error:xxx / device offline 等都视为连接层失败，交给上层重连
            raise AdbError(f"adb shell 失败({rc}): {(err or out).strip()[:120]}")
        return out

    # ---------- 连接管理 ----------

    def connect(self) -> bool:
        rc, out, _ = self._run("connect", self.host, timeout=15)
        return "connected" in out or "already connected" in out

    def is_ready(self) -> bool:
        try:
            rc, out, _ = self._run("get-state", timeout=8)
        except AdbError:
            return False
        return rc == 0 and out.strip() == "device"

    def ensure_connected(self) -> bool:
        if self.is_ready():
            return True
        return self.connect() and self.is_ready()

    # ---------- 状态查询 ----------

    def get_foreground(self):
        """返回前台应用包名；无法识别时返回 None。

        不依赖设备端 grep（部分 TV ROM 的 toybox grep 会吞输出/截断行），
        拉全量 dumpsys 后用 Python 解析；多种来源依次尝试。
        """
        outputs = []
        for cmd in (
            "dumpsys window windows",
            "dumpsys activity activities",
        ):
            try:
                out = self.shell(cmd, timeout=15)
            except AdbError:
                continue
            if out:
                outputs.append(out)

        # 优先 mCurrentFocus / mFocusedApp（window dumpsys）
        for out in outputs:
            for line in out.splitlines():
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    m = _FOCUS_RE.search(line)
                    if m:
                        pkg = m.group(1)
                        if pkg not in ("android", "com.android.systemui"):
                            return pkg
        # 递补：ResumedActivity（activity dumpsys）
        for out in outputs:
            for line in out.splitlines():
                if "ResumedActivity" in line or "mResumedActivity" in line:
                    m = _FOCUS_RE.search(line)
                    if m:
                        pkg = m.group(1)
                        if pkg not in ("android", "com.android.systemui"):
                            return pkg
        # 最后兜底：Launcher 桌面本身不算前台应用，无命中返回 None
        return None

    def is_screen_on(self):
        try:
            out = self.shell("dumpsys power", timeout=10)
        except AdbError:
            return False
        if "mWakefulness=Awake" in out:
            return True
        if "mWakefulness=Asleep" in out or "mWakefulness=Dozing" in out:
            return False
        try:
            out = self.shell("dumpsys display", timeout=10)
        except AdbError:
            return True
        return "mScreenState=ON" in out

    def getprop(self, name: str) -> str:
        try:
            return self.shell(f"getprop {name}").strip()
        except AdbError:
            return ""

    def list_packages(self, third_party_only=True):
        flag = "-3" if third_party_only else ""
        out = self.shell(f"pm list packages {flag}")
        pkgs = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkgs.append(line[len("package:"):])
        return sorted(pkgs)

    def list_apps(self):
        """返回电视上全部应用（含预装的常见视频应用），
        带已知中文名（KNOWN_APPS 字典），供面板选择。"""
        try:
            third = set(self.list_packages(third_party_only=True))
        except AdbError:
            third = set()
        try:
            all_pkgs = self.list_packages(third_party_only=False)
        except AdbError:
            all_pkgs = sorted(third)

        apps = []
        for pkg in all_pkgs:
            name = KNOWN_APPS.get(pkg)
            if name or pkg in third:
                apps.append({
                    "package": pkg,
                    "name": name or "",
                    "third_party": pkg in third,
                })
        # 有名字的排前面，其余按包名字母序
        apps.sort(key=lambda a: (a["name"] == "", a["package"]))
        return apps


    # ---------- 控制 ----------

    BLOCKER_PKG = "com.tvguard.blocker"

    def force_stop(self, package: str):
        self.shell(f"am force-stop {package}")

    def go_home(self):
        self.shell("input keyevent 3")

    def show_blocker(self, app_name: str, reason: str, extra: str = ""):
        """拉起电视端全屏提示页。失败（未安装等）静默忽略，不影响拦截本身。"""
        def esc(s):
            return (s or "").replace("\\", "\\\\").replace('"', '\\"')
        cmd = (f'am start -n {self.BLOCKER_PKG}/.BlockerActivity -f 0x14000000 '
               f'--es app "{esc(app_name)}" --es reason "{esc(reason)}" '
               f'--es extra "{esc(extra)}"')
        try:
            out = self.shell(cmd)
            logger.warning("[BLOCK-DBG] am start 输出: %s", out.strip()[:200])
            return True
        except AdbError as e:
            logger.warning("[BLOCK-DBG] am start 失败: %s", e)
            return False

    def is_blocker_installed(self) -> bool:
        try:
            out = self.shell(f"pm path {self.BLOCKER_PKG}")
        except AdbError:
            return False
        return "package:" in out
