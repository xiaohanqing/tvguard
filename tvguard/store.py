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
    def __init__(self, data_dir: str, reset_time: str = "00:00",
                 defaults: dict = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.rules_path = os.path.join(data_dir, "rules.json")
        self.state_path = os.path.join(data_dir, "state.json")
        self.settings_path = os.path.join(data_dir, "settings.json")
        self.reset_time = reset_time
        self._lock = threading.RLock()

        # 连接设置（电视IP等，面板可改）。首次用 config.yaml 的值做种子
        self.settings = self._load_json(self.settings_path, {})
        if defaults:
            changed = False
            for k, v in (defaults or {}).items():
                if k not in self.settings:
                    self.settings[k] = v
                    changed = True
            if changed:
                self._dump(self.settings_path, self.settings)

        # 运行时瞬态（不持久化）
        self.connected = False
        self.foreground = None
        self.screen_on = None

        self.rules = self._load_json(self.rules_path, {"apps": []})
        if "apps" not in self.rules:
            self.rules = {"apps": []}
        # 旧格式（schedules + 整日限额）迁移为 windows 格式
        migrated = False
        for r in self.rules["apps"]:
            if "windows" not in r:
                self._migrate_rule(r)
                migrated = True
            self._normalize_rule(r)
        if migrated:
            self._save()
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

    # ---------- 窗口级用量 / 加时 ----------

    def _win_map(self, day: str, package: str, key: str) -> dict:
        d = self._day(day)
        return d.setdefault(key, {}).setdefault(package, {})

    def win_usage(self, day: str, package: str, idx: int) -> float:
        return self._win_map(day, package, "win_usage").get(str(idx), 0)

    def add_win_usage(self, day: str, package: str, idx: int, seconds: float):
        with self._lock:
            m = self._win_map(day, package, "win_usage")
            m[str(idx)] = m.get(str(idx), 0) + seconds
            self._save()

    def win_bonus_minutes(self, day: str, package: str, idx: int) -> int:
        return self._win_map(day, package, "win_bonus").get(str(idx), 0)

    def add_win_bonus(self, day: str, package: str, idx: int, minutes: int):
        with self._lock:
            m = self._win_map(day, package, "win_bonus")
            m[str(idx)] = m.get(str(idx), 0) + minutes
            self._save()

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

    # ---------- 禁看（家长主动锁定） ----------

    def set_lock(self, minutes: int):
        with self._lock:
            self.state["lock_until"] = (
                datetime.now() + timedelta(minutes=minutes)).isoformat()
            self._save()

    # ---------- 连接设置 ----------

    def set_setting(self, key: str, value):
        with self._lock:
            self.settings[key] = value
            self._dump(self.settings_path, self.settings)

    def save_settings(self):
        with self._lock:
            self._dump(self.settings_path, self.settings)

    def clear_lock(self):
        with self._lock:
            if self.state.get("lock_until"):
                self.state["lock_until"] = None
                self._save()

    def lock_info(self):
        """返回 (是否禁看中, 结束时间 datetime|None)。"""
        until = self.state.get("lock_until")
        if not until:
            return False, None
        try:
            end = datetime.fromisoformat(until)
        except ValueError:
            return False, None
        return datetime.now() < end, end

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

    def _migrate_rule(self, rule: dict):
        """旧格式（schedules + 整日限额）→ windows 格式。
        迁移语义：每个窗口不限窗口内时长，保留整日限额，行为与旧版一致。"""
        windows = []
        for s in rule.get("schedules") or []:
            windows.append({
                "days": s.get("days") or [],
                "start": s.get("start", ""),
                "end": s.get("end", ""),
                "limit_minutes": 0,
            })
        rule["windows"] = windows

    def _normalize_rule(self, rule: dict):
        rule.setdefault("name", rule["package"])
        rule["daily_limit_minutes"] = max(0, int(rule.get("daily_limit_minutes", 0) or 0))
        rule["banned"] = bool(rule.get("banned", False))
        wins = []
        for w in rule.get("windows") or []:
            days = [d for d in (w.get("days") or []) if d in WEEKDAYS]
            if not days or not w.get("start") or not w.get("end"):
                continue
            wins.append({
                "days": days,
                "start": w["start"],
                "end": w["end"],
                "limit_minutes": max(0, int(w.get("limit_minutes", 0) or 0)),
            })
        rule["windows"] = wins

    def get_rule(self, package: str):
        for app in self.rules["apps"]:
            if app["package"] == package:
                return app
        return None

    def all_rules(self):
        return self.rules["apps"]

    def upsert_rule(self, rule: dict):
        self._normalize_rule(rule)
        with self._lock:
            for i, app in enumerate(self.rules["apps"]):
                if app["package"] == rule["package"]:
                    self.rules["apps"][i] = rule
                    break
            else:
                self.rules["apps"].append(rule)
            self._save()

    def replace_rules(self, apps: list):
        """整批替换规则（导入用），逐条规范化。"""
        cleaned = []
        for r in apps:
            if not isinstance(r, dict) or not r.get("package"):
                continue
            self._migrate_rule(r) if "windows" not in r else None
            self._normalize_rule(r)
            cleaned.append(r)
        with self._lock:
            self.rules["apps"] = cleaned
            self._save()
        return len(cleaned)

    def delete_rule(self, package: str) -> bool:
        with self._lock:
            before = len(self.rules["apps"])
            self.rules["apps"] = [a for a in self.rules["apps"] if a["package"] != package]
            changed = len(self.rules["apps"]) != before
            if changed:
                self._save()
            return changed

    # ---------- 时段窗口 ----------

    def find_window(self, rule: dict, now: datetime):
        """返回当前时间命中的窗口下标；不在任何窗口返回 None。
        无窗口定义的规则返回 -1（全天允许，仅受每日总额约束）。"""
        windows = rule.get("windows") or []
        if not windows:
            return -1
        t = now.hour * 60 + now.minute
        wd = WEEKDAYS[now.weekday()]
        yd = WEEKDAYS[(now.weekday() - 1) % 7]
        for i, w in enumerate(windows):
            try:
                sh, sm = map(int, w["start"].split(":"))
                eh, em = map(int, w["end"].split(":"))
            except ValueError:
                continue
            start, end = sh * 60 + sm, eh * 60 + em
            if end > start:
                if wd in w["days"] and start <= t < end:
                    return i
            else:
                # 跨午夜窗口：开始时刻在当天后半段，结束在次日前半段
                if wd in w["days"] and t >= start:
                    return i
                if yd in w["days"] and t < end:
                    return i
        return None

    def in_schedule(self, rule: dict, now: datetime) -> bool:
        return self.find_window(rule, now) is not None
