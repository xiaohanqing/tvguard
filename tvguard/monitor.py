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
        if self.store.is_paused():
            return

        rule = self.store.get_rule(fg)
        if rule is None:
            return  # 未纳入管控的应用

        day = self.store.today_key()
        usage = self.store.usage_seconds(day, fg)
        limit = rule.get("daily_limit_minutes", 0) * 60
        bonus = self.store.bonus_minutes(day, fg) * 60

        if not self.store.in_schedule(rule, datetime.now()):
            self.block(fg, rule, self._reason_schedule(rule))
        elif limit > 0 and usage + elapsed > limit + bonus:
            self.block(fg, rule, self._reason_timeout(rule, fg, usage, bonus))
        else:
            self.store.add_usage(day, fg, elapsed)

    def _reason_schedule(self, rule: dict) -> str:
        """时段外拦截文案：告诉孩子什么时候可以看。"""
        schedules = rule.get("schedules") or []
        if not schedules:
            return "现在不能观看"
        parts = []
        for s in schedules:
            days = "、".join(WEEKDAY_CN.get(d, d) for d in s.get("days", []))
            parts.append(f"周{days} {s.get('start', '')}–{s.get('end', '')}")
        return "现在的时段不能看。可以看的时间：" + "；".join(parts)

    def _reason_timeout(self, rule: dict, pkg: str, usage: float, bonus: float) -> str:
        """超时拦截文案：今天用了多久，限额多少。"""
        limit = rule.get("daily_limit_minutes", 0)
        used = int(usage // 60)
        if bonus > 0:
            return f"今天的 {limit} 分钟 + 加时 {int(bonus // 60)} 分钟都用完啦（已看 {used} 分钟）"
        return f"今天的 {limit} 分钟已经用完了（已看 {used} 分钟）"

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
