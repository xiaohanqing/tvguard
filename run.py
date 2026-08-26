"""TVGuard 入口。

用法：
  python run.py                # 启动监控服务 + Web 面板
  python run.py --preflight    # 预检：连接电视并打印系统信息（回家第一次试时先跑这个）
  python run.py --list-apps    # 列出电视上已安装的第三方应用包名
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tvguard.adb import Adb, AdbError
from tvguard.config import load_config
from tvguard.monitor import Monitor
from tvguard.store import Store
from tvguard.web import create_app

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def build(cfg):
    adb = Adb(cfg["tv"]["adb_path"], cfg["tv"]["adb_host"])
    store = Store(os.path.join(BASE_DIR, "data"), cfg.get("reset_time", "00:00"))
    return adb, store


def preflight(cfg):
    adb, _ = build(cfg)
    print(f"== TVGuard 预检 ==\n目标: {adb.host}\n")
    try:
        ok = adb.ensure_connected()
    except AdbError as e:
        ok = False
        print(f"[1] adb connect 失败: {e}")
    if not ok:
        print("\n连接失败排查：")
        print("  1) 电视上是否已开启 ADB 调试？（雷鸟：设置→系统→系统信息，遥控器依次按 上 下 左 右）")
        print("  2) 电视和服务端是否在同一局域网？ping 一下电视 IP")
        print("  3) 首次连接电视屏幕会弹 RSA 授权框，用遥控器选允许/确定")
        sys.exit(1)
    print("[1] adb connect ................ OK")
    model = adb.getprop("ro.product.model")
    ver = adb.getprop("ro.build.version.release")
    print(f"[2] 电视型号 .................... {model or '未知'}（Android {ver or '未知'}）")
    if ver and ver.split(".")[0].isdigit() and int(ver.split(".")[0]) >= 13:
        print("    ⚠ Android 13+，注意验证重启后 ADB 开关是否保持")
    screen = adb.is_screen_on()
    print(f"[3] 屏幕状态 .................... {'亮屏' if screen else '息屏'}")
    fg = adb.get_foreground()
    print(f"[4] 当前前台应用 ................ {fg or '（待机或桌面，打开任意应用后重跑）'}")
    if fg:
        print(f"    → 可测试拦截: python -c \"...\" 或直接在面板添加后再观察")
    print("\n全部通过。重启电视后再跑一次本命令，验证 ADB 开关是否保持开启。")
    print("验证通过后运行: python run.py  然后浏览器打开 http://<本机IP>:8787")


def list_apps(cfg):
    adb, _ = build(cfg)
    if not adb.ensure_connected():
        print("电视连接失败，请先跑 python run.py --preflight")
        sys.exit(1)
    pkgs = adb.list_packages(third_party_only=True)
    print(f"电视上共 {len(pkgs)} 个第三方应用:\n")
    for p in pkgs:
        print("  " + p)


def serve(cfg):
    adb, store = build(cfg)
    monitor = Monitor(cfg, store, adb)
    monitor.start()
    app = create_app(cfg, store, adb)
    host = cfg["server"]["host"]
    port = cfg["server"]["port"]
    print(f"TVGuard 已启动: 面板 http://{'本机IP' if host == '0.0.0.0' else host}:{port}")
    print(f"监控目标: {adb.host}（轮询 {cfg['tv']['poll_interval']}s）")
    app.run(host=host, port=port, use_reloader=False, threaded=True)


def main():
    parser = argparse.ArgumentParser(description="TVGuard 电视时间管家")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config.yaml"))
    parser.add_argument("--preflight", action="store_true", help="预检电视连接")
    parser.add_argument("--list-apps", action="store_true", help="列出电视第三方应用")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = load_config(args.config)
    if args.preflight:
        preflight(cfg)
    elif args.list_apps:
        list_apps(cfg)
    else:
        serve(cfg)


if __name__ == "__main__":
    main()
