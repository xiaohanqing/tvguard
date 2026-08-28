#!/bin/bash
# 本地 ↔ 服务器 规则数据同步脚本
# 用法:
#   ./sync.sh <user@服务器> push    # 本地规则 → 服务器（并重启服务）
#   ./sync.sh <user@服务器> pull    # 服务器规则 → 本地
# 示例:
#   ./sync.sh root@192.168.31.100 push
set -e
cd "$(dirname "$0")"

if [ -z "$1" ] || [ -z "$2" ]; then
  grep -E "^#" "$0" | head -6
  exit 1
fi
HOST="$1"; DIR="${REMOTE_DIR:-~/dockers/tvguard}"

case "$2" in
  push)
    [ -f data/rules.json ] || { echo "本地没有 data/rules.json"; exit 1; }
    ssh "$HOST" "mkdir -p $DIR/data"
    scp data/rules.json "$HOST:$DIR/data/rules.json"
    echo "==> 已推送规则，重启服务器上的服务..."
    ssh "$HOST" "cd $DIR && docker compose restart"
    echo "==> 完成。"
    ;;
  pull)
    scp "$HOST:$DIR/data/rules.json" data/rules.json
    echo "==> 已拉取规则到本地 data/rules.json（本地服务需重启生效：restart.bat）"
    ;;
  *) echo "第二个参数必须是 push 或 pull"; exit 1;;
esac
