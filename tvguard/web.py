"""Web 家长面板：Flask API + 单页面。"""
import functools
from datetime import datetime

from flask import Flask, jsonify, render_template, request

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
        apps = []
        for rule in store.all_rules():
            pkg = rule["package"]
            usage = store.usage_seconds(day, pkg)
            bonus = store.bonus_minutes(day, pkg)
            limit = rule.get("daily_limit_minutes", 0)
            in_sched = store.in_schedule(rule, datetime.now())
            apps.append({
                "package": pkg,
                "name": rule.get("name", pkg),
                "limit_minutes": limit,
                "bonus_minutes": bonus,
                "usage_minutes": round(usage / 60, 1),
                "remaining_minutes": None if limit <= 0
                else round(max(0, (limit + bonus) - usage / 60), 1),
                "in_schedule": in_sched,
                "is_foreground": pkg == store.foreground,
                "schedules": rule.get("schedules", []),
            })
        return jsonify({
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "connected": store.connected,
            "screen_on": store.screen_on,
            "foreground": store.foreground,
            "foreground_controlled": store.foreground is not None and store.get_rule(store.foreground) is not None,
            "paused": store.is_paused(),
            "paused_until": store.state.get("paused_until"),
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

    @app.route("/api/bonus", methods=["POST"])
    @auth_required
    def api_bonus():
        pkg = request.json.get("package", "")
        minutes = int(request.json.get("minutes", 15))
        rule = store.get_rule(pkg)
        if not rule:
            return jsonify({"error": "应用未纳入管控"}), 404
        store.add_bonus(store.today_key(), pkg, minutes)
        store.log_event("bonus", f"「{rule.get('name', pkg)}」加时 {minutes} 分钟", pkg)
        return jsonify({"ok": True})

    # ---------- 规则 ----------

    @app.route("/api/apps", methods=["POST"])
    @auth_required
    def api_upsert_app():
        data = request.json or {}
        pkg = (data.get("package") or "").strip()
        if not pkg or "." not in pkg:
            return jsonify({"error": "包名不合法"}), 400
        rule = {
            "package": pkg,
            "name": (data.get("name") or pkg).strip(),
            "daily_limit_minutes": max(0, int(data.get("daily_limit_minutes", 0))),
            "schedules": _clean_schedules(data.get("schedules") or []),
        }
        store.upsert_rule(rule)
        store.log_event("rule", f"保存规则：「{rule['name']}」每日 {rule['daily_limit_minutes']} 分钟")
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
        return jsonify({
            "package": fg,
            "activity_raw": "",
            "controlled": rule is not None,
            "name": rule.get("name") if rule else None,
        })

    @app.route("/api/packages")
    @auth_required
    def api_packages():
        try:
            pkgs = adb.list_packages(third_party_only=True)
        except Exception as e:
            return jsonify({"error": f"获取失败: {e}"}), 502
        return jsonify({"packages": pkgs})

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"error": "not found"}), 404

    return app


def _clean_schedules(schedules):
    cleaned = []
    for s in schedules:
        days = [d for d in (s.get("days") or []) if d in WEEKDAY_LABELS]
        start = (s.get("start") or "").strip()
        end = (s.get("end") or "").strip()
        if days and start and end:
            cleaned.append({"days": days, "start": start, "end": end})
    return cleaned


def format_schedule(s) -> str:
    days = "周" + "".join(WEEKDAY_LABELS.get(d, "?") for d in s.get("days", []))
    return f"{days} {s['start']}-{s['end']}"
