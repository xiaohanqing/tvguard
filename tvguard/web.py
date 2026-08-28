"""Web 家长面板：Flask API + 单页面。"""
import functools
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from .adb import label_for

WEEKDAY_LABELS = {
    "mon": "一", "tue": "二", "wed": "三", "thu": "四",
    "fri": "五", "sat": "六", "sun": "日",
}


def create_app(cfg: dict, store, adb) -> Flask:
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    password = cfg["server"].get("password") or ""

    def auth_required(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if password:
                supplied = request.headers.get("X-Auth-Token") or \
                    (request.authorization.password if request.authorization else None)
                if supplied != password:
                    return jsonify({"error": "密码错误"}), 401
            return fn(*args, **kwargs)
        return wrapper

    # ---------- 页面 ----------

    @app.route("/")
    def index():
        return render_template("index.html")

    # ---------- 状态 ----------

    @app.route("/api/status")
    @auth_required
    def api_status():
        day = store.today_key()
        now = datetime.now()
        apps = []
        for rule in store.all_rules():
            pkg = rule["package"]
            usage = store.usage_seconds(day, pkg)
            bonus = store.bonus_minutes(day, pkg)
            limit = rule.get("daily_limit_minutes", 0)
            win_idx = store.find_window(rule, now)
            wins = []
            for i, w in enumerate(rule.get("windows", [])):
                wusage = store.win_usage(day, pkg, i)
                wbonus = store.win_bonus_minutes(day, pkg, i)
                wlimit = w.get("limit_minutes", 0)
                wins.append({
                    "days": w.get("days", []),
                    "start": w.get("start"),
                    "end": w.get("end"),
                    "limit_minutes": wlimit,
                    "bonus_minutes": wbonus,
                    "usage_minutes": round(wusage / 60, 1),
                    "remaining_minutes": None if wlimit <= 0
                        else round(max(0, (wlimit + wbonus) - wusage / 60), 1),
                    "active": i == win_idx,
                })
            apps.append({
                "package": pkg,
                "name": rule.get("name", pkg),
                "banned": rule.get("banned", False),
                "daily_limit_minutes": limit,
                "bonus_minutes": bonus,
                "usage_minutes": round(usage / 60, 1),
                "remaining_minutes": None if limit <= 0
                    else round(max(0, (limit + bonus) - usage / 60), 1),
                "in_window": win_idx is not None,
                "no_windows": win_idx == -1,
                "is_foreground": pkg == store.foreground,
                "windows": wins,
            })
        locked, lock_end = store.lock_info()
        return jsonify({
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "connected": store.connected,
            "screen_on": store.screen_on,
            "foreground": store.foreground,
            "foreground_controlled": store.foreground is not None and store.get_rule(store.foreground) is not None,
            "paused": store.is_paused(),
            "paused_until": store.state.get("paused_until"),
            "locked": locked,
            "lock_until": lock_end.isoformat() if lock_end else None,
            "apps": apps,
            "events": store.events(20),
        })

    # ---------- 控制 ----------

    @app.route("/api/pause", methods=["POST"])
    @auth_required
    def api_pause():
        minutes = int(request.json.get("minutes", 30))
        store.set_paused(minutes)
        store.log_event("pause", f"家长暂停控制 {minutes} 分钟")
        return jsonify({"ok": True})

    @app.route("/api/resume", methods=["POST"])
    @auth_required
    def api_resume():
        store.resume()
        store.log_event("resume", "恢复控制")
        return jsonify({"ok": True})

    @app.route("/api/lock", methods=["POST"])
    @auth_required
    def api_lock():
        minutes = int(request.json.get("minutes", 10))
        store.set_lock(minutes)
        store.log_event("lock", f"家长开启禁看 {minutes} 分钟")
        return jsonify({"ok": True})

    @app.route("/api/unlock", methods=["POST"])
    @auth_required
    def api_unlock():
        store.clear_lock()
        store.log_event("unlock", "家长解除禁看")
        return jsonify({"ok": True})

    @app.route("/api/ban", methods=["POST"])
    @auth_required
    def api_ban():
        pkg = (request.json.get("package") or "").strip()
        banned = bool(request.json.get("banned", True))
        rule = store.get_rule(pkg)
        if not rule:
            return jsonify({"error": "应用未纳入管控"}), 404
        rule["banned"] = banned
        store.upsert_rule(rule)
        name = rule.get("name", pkg)
        store.log_event("ban" if banned else "unban",
            (f"已禁止「{name}」使用" if banned else f"解除「{name}」的禁止"), pkg)
        return jsonify({"ok": True})

    @app.route("/api/bonus", methods=["POST"])
    @auth_required
    def api_bonus():
        pkg = request.json.get("package", "")
        minutes = int(request.json.get("minutes", 15))
        rule = store.get_rule(pkg)
        if not rule:
            return jsonify({"error": "应用未纳入管控"}), 404
        name = rule.get("name", pkg)
        win_idx = request.json.get("window")
        if win_idx is None:
            store.add_bonus(store.today_key(), pkg, minutes)
            store.log_event("bonus", f"「{name}」今日总时长加 {minutes} 分钟", pkg)
        else:
            win_idx = int(win_idx)
            wins = rule.get("windows", [])
            if win_idx < 0 or win_idx >= len(wins):
                return jsonify({"error": "时段不存在"}), 404
            store.add_win_bonus(store.today_key(), pkg, win_idx, minutes)
            w = wins[win_idx]
            store.log_event("bonus",
                f"「{name}」时段 {w['start']}–{w['end']} 加 {minutes} 分钟", pkg)
        return jsonify({"ok": True})

    # ---------- 规则 ----------

    @app.route("/api/apps", methods=["POST"])
    @auth_required
    def api_upsert_app():
        data = request.json or {}
        pkg = (data.get("package") or "").strip()
        if not pkg or "." not in pkg:
            return jsonify({"error": "包名不合法"}), 400
        windows = []
        for w in data.get("windows") or []:
            days = [d for d in (w.get("days") or []) if d in WEEKDAY_LABELS]
            start = (w.get("start") or "").strip()
            end = (w.get("end") or "").strip()
            if not (days and start and end):
                continue
            try:
                limit = max(0, int(w.get("limit_minutes", 0) or 0))
            except (TypeError, ValueError):
                limit = 0
            windows.append({"days": days, "start": start, "end": end,
                            "limit_minutes": limit})
        # 兼容旧客户端的 schedules 字段（整日限额语义）
        if not windows and data.get("schedules"):
            for s in data["schedules"]:
                days = [d for d in (s.get("days") or []) if d in WEEKDAY_LABELS]
                if days and s.get("start") and s.get("end"):
                    windows.append({"days": days, "start": s["start"],
                                    "end": s["end"], "limit_minutes": 0})
        try:
            daily_cap = max(0, int(data.get("daily_limit_minutes", 0) or 0))
        except (TypeError, ValueError):
            daily_cap = 0
        rule = {
            "package": pkg,
            "name": (data.get("name") or pkg).strip(),
            "daily_limit_minutes": daily_cap,
            "windows": windows,
            "banned": bool(data.get("banned", False)),
        }
        store.upsert_rule(rule)
        cap_txt = f"每日总限 {daily_cap} 分钟" if daily_cap else "不限总时长"
        store.log_event("rule",
            f"保存规则：「{rule['name']}」{len(windows)} 个时段，{cap_txt}")
        return jsonify({"ok": True})

    @app.route("/api/apps/delete", methods=["POST"])
    @auth_required
    def api_delete_app():
        pkg = (request.json.get("package") or "").strip()
        rule = store.get_rule(pkg)
        ok = store.delete_rule(pkg)
        if ok:
            store.log_event("rule", f"移除管控：「{rule.get('name', pkg)}」", pkg)
        return jsonify({"ok": ok})

    # ---------- 辅助 ----------

    @app.route("/api/foreground")
    @auth_required
    def api_foreground():
        fg = store.foreground
        rule = store.get_rule(fg) if fg else None
        if rule:
            name = rule.get("name")
        else:
            name = label_for(fg) if fg else None
        return jsonify({
            "package": fg,
            "activity_raw": "",
            "controlled": rule is not None,
            "name": name,
        })

    @app.route("/api/packages")
    @auth_required
    def api_packages():
        try:
            apps = adb.list_apps()
        except Exception as e:
            return jsonify({"error": f"获取失败: {e}"}), 502
        # 已有规则的应用补上家长起的名字
        for a in apps:
            rule = store.get_rule(a["package"])
            if rule:
                a["name"] = rule.get("name") or a["name"]
                a["controlled"] = True
            else:
                a["controlled"] = False
        return jsonify({"apps": apps})

    @app.route("/api/test-blocker", methods=["POST"])
    @auth_required
    def api_test_blocker():
        try:
            ok = adb.show_blocker("测试应用", "这是一次测试拦截（家长触发）")
        except Exception as e:
            return jsonify({"error": f"调用失败: {e}"}), 502
        if not ok:
            return jsonify({"error": "电视上未安装提示页 APK（tvguard-blocker）"}), 502
        store.log_event("test", "测试显示拦截提示页")
        return jsonify({"ok": True})

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not found"}), 404

    return app


def format_schedule(s) -> str:
    days = "周" + "".join(WEEKDAY_LABELS.get(d, "?") for d in s.get("days", []))
    return f"{days} {s['start']}-{s['end']}"
