"""ADB 子进程封装。

通过无线 ADB（adb connect <ip>:5555）控制电视：
- 查询前台应用：dumpsys window / dumpsys activity
- 查询亮屏状态：dumpsys power / dumpsys display
- 关闭应用：am force-stop；回桌面：input keyevent HOME
"""
import re
import subprocess

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
        if rc != 0 and "no devices" in (out + err).lower():
            raise AdbError("设备未连接")
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
        """返回前台应用包名；无法识别时返回 None。"""
        for cmd in (
            "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'",
            "dumpsys activity activities | grep -E 'ResumedActivity|mResumedActivity'",
        ):
            try:
                out = self.shell(cmd)
            except AdbError:
                return None
            m = _FOCUS_RE.search(out)
            if m:
                pkg = m.group(1)
                if pkg in ("android", "com.android.systemui"):
                    # 系统弹窗/状态栏遮挡时拿不到真实前台，视为未识别
                    continue
                return pkg
        return None

    def is_screen_on(self):
        try:
            out = self.shell("dumpsys power | grep mWakefulness")
        except AdbError:
            return False
        if "Awake" in out:
            return True
        if "Asleep" in out or "Dozing" in out:
            return False
        try:
            out = self.shell("dumpsys display | grep -i mScreenState")
        except AdbError:
            return True
        return "ON" in out.upper()

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

    def force_stop(self, package: str):
        self.shell(f"am force-stop {package}")

    def go_home(self):
        self.shell("input keyevent 3")
