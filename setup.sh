#!/bin/bash
# TVGuard 服务器一键部署：git clone 后在本目录执行
#   ./setup.sh <电视IP>
# 例如: ./setup.sh 192.168.31.22
set -e
cd "$(dirname "$0")"

TV_IP="${1:-}"
if [ -z "$TV_IP" ]; then
  echo "用法: ./setup.sh <电视IP>"
  echo "电视IP在电视上查看: 设置 → 关于 → 网络状态"
  exit 1
fi

echo "==> 检查 Docker..."
command -v docker >/dev/null || { echo "!! 未安装 docker"; exit 1; }
docker compose version >/dev/null 2>&1 || docker-compose version >/dev/null 2>&1 || \
  { echo "!! 未安装 docker compose"; exit 1; }

echo "==> 生成配置..."
if [ ! -f config.yaml ]; then
  sed "s/192.168.1.100/$TV_IP/" config.example.yaml > config.yaml
  echo "    config.yaml 已生成（电视: $TV_IP）。如需面板密码请编辑 server.password"
else
  echo "    config.yaml 已存在，保留现有配置"
fi

echo "==> 构建并启动（首次约 2-5 分钟）..."
if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
else
  docker-compose up -d --build
fi

echo "==> 健康检查..."
UP=0
for i in $(seq 1 30); do
  sleep 2
  if curl --noproxy '*' -s -m 3 http://127.0.0.1:8787/api/status >/dev/null 2>&1; then
    UP=1; break
  fi
done

if [ "$UP" = "1" ]; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo ""
  echo "✅ TVGuard 已启动"
  echo "   面板: http://${IP:-<本机IP>}:8787"
  echo "   电视: $TV_IP:5555"
  echo ""
  echo "下一步:"
  echo "   1. 电视上打开 ADB（设置→系统→系统信息，遥控器按 上下左右）"
  echo "   2. 首次连接电视会弹授权框，遥控器选允许"
  echo "   3. 浏览器打开面板添加要管控的应用"
  echo "   4. 已装过提示页 APK 的电视无需重装"
else
  echo "!! 服务未就绪，查看日志:"
  docker compose logs --tail 30 2>/dev/null || docker-compose logs --tail 30
  exit 1
fi
