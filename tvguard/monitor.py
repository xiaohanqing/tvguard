"""监控守护线程：轮询电视前台应用，累计时长，执行限额与时段控制。"""
import logging
import threading
import time
from datetime import datetime

from .adb import AdbError

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
            self.block(fg, rule, "不在允许时间段内")
        elif limit > 0 and usage + elapsed > limit + bonus:
            self.block(fg, rule, "今日时长已用完")
        else:
            self.store.add_usage(day, fg, elapsed)

    def block(self, package: str, rule: dict, reason: str):
        try:
            self.adb.force_stop(package)
            self.adb.go_home()
        except Exception:
            log.exception("拦截 %s 失败", package)

        # 拦截事件限流：同一应用 60 秒内只记一条，避免刷屏
        now = time.time()
        if now - self._last_block_log.get(package, 0) > 60:
            self._last_block_log[package] = now
            name = rule.get("name", package)
            self.store.log_event("block", f"已拦截「{name}」：{reason}", package)
            log.info("拦截 %s(%s): %s", name, package, reason)
