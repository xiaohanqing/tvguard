"""TVGuard 配置加载。

静态配置（电视地址、服务端口等）放在 config.yaml；
应用管控规则（哪个 App 限额多少）由 Web 面板动态编辑，持久化在 data/rules.json。
"""
import os

import yaml

DEFAULTS = {
    "tv": {
        "adb_path": "adb",
        "adb_host": "192.168.1.100",   # 电视 IP，不带端口时默认 5555
        "poll_interval": 5,             # 轮询前台应用的间隔（秒）
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8787,
        "password": "",                 # 非空则面板访问需要密码
    },
    "reset_time": "00:00",              # 每日额度重置时间
}


def load_config(path: str) -> dict:
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    merged = _merge(DEFAULTS, cfg)

    host = str(merged["tv"]["adb_host"])
    if ":" not in host:
        host = f"{host}:5555"
    merged["tv"]["adb_host"] = host
    merged["tv"]["poll_interval"] = int(merged["tv"]["poll_interval"])
    merged["server"]["port"] = int(merged["server"]["port"])
    return merged


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out
