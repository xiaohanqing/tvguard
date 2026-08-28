"""监控守护线程：轮询电视前台应用，累计时长，执行限额与时段控制。"""
import logging
import threading
import time
from datetime import datetime

from .adb import AdbError
from .store import WEEKDAYS

WEEKDAY_CN = {"mon": "一", "tue": "二", "wed": "三", "thu": "四",
              "fri": "五", "sat": "六", "sun": "日"}

log = logging.getLogger("tvguard.monitor")


class Monitor(threading.Thread):
    def __init__(self, cfg: dict, store, adb):
        super().__init__(daemon=True, name="monitor")
        self.store = store
        self.adb = adb
        self.poll_interval = cfg["tv"]["poll_interval"]
        # 整机禁看的放行包：配置里的桌面/画报 + 提示页自身 + 系统 UI
        self.lock_allow = set(cfg["tv"].get("lock_allow") or [])
        self.lock_allow.add("com.tvguard.blocker")
        self.lock_allow.add("com.android.systemui")
        self._stop_event = threading.Event()
        self._last_tick = time.time()
        self._last_block_log = {}   # package -> 上次记录拦截事件的时间戳
        self._last_err_log = {}     # key -> 上次记录错误事件的时间戳
        self._last_conn_state = None

    def _log_recurring(self, key: str, message: str):
        """同一错误 10 分钟内只记一条，避免刷屏。"""
        now = time.time()
        if now - self._last_err_log.get(key, 0) > 600:
            self._last_err_log[key] = now
            self.store.log_event("error", message)
            log.error("%s", message)

    def stop(self):
        self._stop_event.set()

    def run(self):
        log.info("监控线程启动，轮询间隔 %ss，目标 %s",
                 self.poll_interval, self.adb.host)
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("监控循环异常")
            self._stop_event.wait(self.poll_interval)

    def tick(self):
        now = time.time()
        # 用真实间隔计时（允许误差），上限 3 倍轮询间隔防止断连后一次性补扣
        elapsed = min(now - self._last_tick, self.poll_interval * 3)
        self._last_tick = now

        adb_error = False
        try:
            connected = self.adb.ensure_connected()
        except AdbError as e:
            connected = False
            adb_error = True
            self._log_recurring("adberr", f"adb 运行异常：{e}")
        except Exception:
            connected = False
            adb_error = True
            log.exception("连接检查异常")
        self.store.connected = connected
        if not adb_error and connected != self._last_conn_state:
            self.store.log_event(
                "conn" if connected else "disconn",
                "已连接电视" if connected else f"电视连接断开（{self.adb.host}）")
            self._last_conn_state = connected
        if not connected:
            self.store.foreground = None
            self.store.screen_on = None
            return

        fg = self.adb.get_foreground()
        screen_on = self.adb.is_screen_on()
        self.store.foreground = fg
        self.store.screen_on = screen_on

        # 待机或回到桌面（识别不到包名）时不计时
        if fg is None or not screen_on:
            return

        # 整机禁看：优先级最高（高于暂停），除放行包外一律关闭
        locked, lock_end = self.store.lock_info()
        if locked:
            if fg in self.lock_allow:
                return
            end_str = lock_end.strftime("%H:%M") if lock_end else ""
            self.block(fg, {"name": fg},
                       f"家长设置了现在不能看电视，{end_str} 后再来吧")
            return

        if self.store.is_paused():
            return

        rule = self.store.get_rule(fg)
        if rule is None:
            return  # 未纳入管控的应用

        day = self.store.today_key()
        now_dt = datetime.now()
        usage = self.store.usage_seconds(day, fg)
        limit = rule.get("daily_limit_minutes", 0) * 60
        bonus = self.store.bonus_minutes(day, fg) * 60

        win_idx = self.store.find_window(rule, now_dt)

        if win_idx is None:
            # 不在任何允许窗口内
            self.block(fg, rule, self._reason_schedule(rule))
            return

        # 每日总上限（0 = 不限）
        if limit > 0 and usage + elapsed > limit + bonus:
            self.block(fg, rule, self._reason_daily(rule, usage, bonus))
            return

        if win_idx == -1:
            # 无窗口定义，全天允许，只受每日总额约束
            self.store.add_usage(day, fg, elapsed)
            return

        # 窗口内：窗口限额（0 = 窗口内不限，仅受每日总额约束）
        w = rule["windows"][win_idx]
        wlimit = w.get("limit_minutes", 0) * 60
        wbonus = self.store.win_bonus_minutes(day, fg, win_idx) * 60
        wusage = self.store.win_usage(day, fg, win_idx)
        if wlimit > 0 and wusage + elapsed > wlimit + wbonus:
            self.block(fg, rule, self._reason_window(w, wusage))
            return

        self.store.add_usage(day, fg, elapsed)
        self.store.add_win_usage(day, fg, win_idx, elapsed)

    def _fmt_days(self, days) -> str:
        """["mon","tue","wed","thu","fri"] → "周一至周五"；离散天用顿号。"""
        idx = sorted(WEEKDAYS.index(d) for d in days if d in WEEKDAYS)
        if not idx:
            return "每天"
        groups, start, prev = [], idx[0], idx[0]
        for i in idx[1:]:
            if i == prev + 1:
                prev = i
                continue
            groups.append((start, prev))
            start = prev = i
        groups.append((start, prev))
        parts = []
        for a, b in groups:
            if a == b:
                parts.append(f"周{WEEKDAY_CN[WEEKDAYS[a]]}")
            elif b - a == 1:
                parts.append(f"周{WEEKDAY_CN[WEEKDAYS[a]]}、周{WEEKDAY_CN[WEEKDAYS[b]]}")
            else:
                parts.append(f"周{WEEKDAY_CN[WEEKDAYS[a]]}至周{WEEKDAY_CN[WEEKDAYS[b]]}")
        return "、".join(parts)

    def _reason_schedule(self, rule: dict) -> str:
        """时段外拦截文案：告诉孩子什么时候可以看、各能看多久。"""
        windows = rule.get("windows") or []
        if not windows:
            return "现在不能观看"
        parts = []
        for w in windows:
            cap = f"（限{w['limit_minutes']}分钟）" if w.get("limit_minutes") else ""
            parts.append(f"{self._fmt_days(w['days'])} {w['start']}–{w['end']}{cap}")
        return "现在不是可以看的时间。可以看：" + "；".join(parts)

    def _reason_window(self, w: dict, wusage: float) -> str:
        limit = w.get("limit_minutes", 0)
        used = int(wusage // 60)
        return f"这个时段的 {limit} 分钟用完了（已看 {used} 分钟），等下一个时段吧"

    def _reason_daily(self, rule: dict, usage: float, bonus: float) -> str:
        cap = rule.get("daily_limit_minutes", 0)
        used = int(usage // 60)
        if bonus > 0:
            return f"今天的 {cap} 分钟 + 加时 {int(bonus // 60)} 分钟都用完啦（共看 {used} 分钟）"
        return f"今天的总时长 {cap} 分钟已经用完了（共看 {used} 分钟）"

    def block(self, package: str, rule: dict, reason: str):
        name = rule.get("name", package)
        log.warning("[BLOCK-DBG] 开始拦截 %s (%s)", name, package)
        try:
            self.adb.force_stop(package)
            log.warning("[BLOCK-DBG] force-stop 已执行")
        except Exception:
            log.exception("[BLOCK-DBG] force-stop 失败 %s", package)
        # 先杀应用，稍等再弹提示页：避免 force-stop 引起的任务栈重置冲掉提示页
        time.sleep(1.2)
        try:
            shown = self.adb.show_blocker(name, reason)
            log.warning("[BLOCK-DBG] show_blocker 返回 %s", shown)
        except Exception:
            log.exception("[BLOCK-DBG] 提示页拉起异常 %s", package)
        # 提示页拉起后立即确认是否真在前台
        try:
            fg_after = self.adb.get_foreground()
            log.warning("[BLOCK-DBG] 拦截后前台 = %s", fg_after)
        except Exception:
            log.exception("[BLOCK-DBG] 查前台异常")

        # 拦截事件限流：同一应用 60 秒内只记一条，避免刷屏
        now = time.time()
        if now - self._last_block_log.get(package, 0) > 60:
            self._last_block_log[package] = now
            self.store.log_event("block", f"已拦截「{name}」：{reason}", package)
            log.info("拦截 %s(%s): %s", name, package, reason)
