#!/bin/bash
# 一键安装提示页 APK 到电视（服务端/本地均可）
# 用法: ./install-blocker.sh [电视IP]   默认读 config.yaml 的 adb_host
set -e
cd "$(dirname "$0")"

IP="${1:-$(python -c "import yaml; print(yaml.safe_load(open('config.yaml'))['tv']['adb_host'].split(':')[0])" 2>/dev/null || echo)}"
if [ -z "$IP" ]; then echo "用法: $0 <电视IP>"; exit 1; fi

APK="tvguard-blocker/tvguard-blocker.apk"
if [ ! -f "$APK" ]; then echo "找不到 $APK，请先构建"; exit 1; fi

adb connect "$IP:5555" >/dev/null
adb -s "$IP:5555" install -r "$APK"
echo "安装完成。可在面板点「测试提示页」验证。"
