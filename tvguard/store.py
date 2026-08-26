"""规则与运行状态的持久化存储。

- data/rules.json : 应用管控规则（面板可编辑）
- data/state.json : 每日用量、加时、暂停状态、事件日志

运行时瞬态字段（连接状态、当前前台应用）只放内存。
"""
import json
import os
import threading
from datetime import datetime, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Store:
    def __init__(self, data_dir: str, reset_time: str = "00:00"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.rules_path = os.path.join(data_dir, "rules.json")
        self.state_path = os.path.join(data_dir, "state.json")
        self.reset_time = reset_time
        self._lock = threading.RLock()

        # 运行时瞬态（不持久化）
        self.connected = False
        self.foreground = None
        self.screen_on = None

        self.rules = self._load_json(self.rules_path, {"apps": []})
        if "apps" not in self.rules:
            self.rules = {"apps": []}
        self.state = self._load_json(self.state_path, {})
        self.state.setdefault("days", {})
        self.state.setdefault("paused_until", None)
        self.state.setdefault("events", [])
        self._prune_days()

    # ---------- 持久化 ----------

    def _load_json(self, path: str, default):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save(self):
        self._dump(self.rules_path, self.rules)
        self._dump(self.state_path, self.state)

    def _dump(self, path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # 只保留最近 14 天的用量数据
    def _prune_days(self):
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        self.state["days"] = {d: v for d, v in self.state["days"].items() if d >= cutoff}

    # ---------- 日期与额度 ----------

    def today_key(self) -> str:
        now = datetime.now()
        try:
            rh, rm = map(int, self.reset_time.split(":"))
        except ValueError:
            rh, rm = 0, 0
        if (now.hour, now.minute) < (rh, rm):
            now -= timedelta(days=1)
        return now.strftime("%Y-%m-%d")

    def _day(self, day: str) -> dict:
        d = self.state["days"].setdefault(day, {})
        d.setdefault("usage", {})
        d.setdefault("bonus", {})
        return d

    def add_usage(self, day: str, package: str, seconds: float):
        with self._lock:
            self._day(day)["usage"][package] = \
                self._day(day)["usage"].get(package, 0) + seconds
            self._save()

    def add_bonus(self, day: str, package: str, minutes: int):
        with self._lock:
            self._day(day)["bonus"][package] = \
                self._day(day)["bonus"].get(package, 0) + minutes
            self._save()

    def usage_seconds(self, day: str, package: str) -> float:
        return self.state.get("days", {}).get(day, {}).get("usage", {}).get(package, 0)

    def bonus_minutes(self, day: str, package: str) -> int:
        return self.state.get("days", {}).get(day, {}).get("bonus", {}).get(package, 0)

    # ---------- 暂停 ----------

    def set_paused(self, minutes: int):
        with self._lock:
            self.state["paused_until"] = (
                datetime.now() + timedelta(minutes=minutes)).isoformat()
            self._save()

    def resume(self):
        with self._lock:
            self.state["paused_until"] = None
            self._save()

    def is_paused(self) -> bool:
        until = self.state.get("paused_until")
        if not until:
            return False
        try:
            return datetime.now() < datetime.fromisoformat(until)
        except ValueError:
            return False

    # ---------- 事件日志 ----------

    def log_event(self, etype: str, message: str, package: str = ""):
        with self._lock:
            self.state["events"].insert(0, {
                "time": datetime.now().strftime("%m-%d %H:%M:%S"),
                "type": etype,
                "package": package,
                "message": message,
            })
            del self.state["events"][200:]
            self._save()

    def events(self, limit: int = 20):
        return self.state.get("events", [])[:limit]

    # ---------- 规则 ----------

    def get_rule(self, package: str):
        for app in self.rules["apps"]:
            if app["package"] == package:
                return app
        return None

    def all_rules(self):
        return self.rules["apps"]

    def upsert_rule(self, rule: dict):
        rule["daily_limit_minutes"] = int(rule.get("daily_limit_minutes", 0))
        rule.setdefault("name", rule["package"])
        rule.setdefault("schedules", [])
        with self._lock:
            for i, app in enumerate(self.rules["apps"]):
                if app["package"] == rule["package"]:
                    self.rules["apps"][i] = rule
                    break
            else:
                self.rules["apps"].append(rule)
            self._save()

    def delete_rule(self, package: str) -> bool:
        with self._lock:
            before = len(self.rules["apps"])
            self.rules["apps"] = [a for a in self.rules["apps"] if a["package"] != package]
            changed = len(self.rules["apps"]) != before
            if changed:
                self._save()
            return changed

    # ---------- 时间段判断 ----------

    def in_schedule(self, rule: dict, now: datetime) -> bool:
        """无 schedules 字段或为空 = 全天允许（仅受每日额度约束）。"""
        schedules = rule.get("schedules") or []
        if not schedules:
            return True
        t = now.hour * 60 + now.minute
        wd = WEEKDAYS[now.weekday()]
        yd = WEEKDAYS[(now.weekday() - 1) % 7]
        for s in schedules:
            days = [d.lower()[:3] for d in s.get("days", [])]
            try:
                sh, sm = map(int, s.get("start", "00:00").split(":"))
                eh, em = map(int, s.get("end", "24:00").split(":"))
            except ValueError:
                continue
            start, end = sh * 60 + sm, eh * 60 + em
            if end > start:
                # 常规窗口
                if wd in days and start <= t < end:
                    return True
            else:
                # 跨午夜窗口：开始时刻在当天后半段，结束在次日前半段
                if wd in days and t >= start:
                    return True
                if yd in days and t < end:
                    return True
        return False
