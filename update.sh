#!/bin/bash
# 服务器端一键更新脚本：拉取最新代码并重建容器。
# 用法：./update.sh   （在 tvguard 项目目录下执行）
set -e
cd "$(dirname "$0")"

if [ ! -f config.yaml ]; then
  echo "缺少 config.yaml，请先: cp config.example.yaml config.yaml 并填写电视IP"
  exit 1
fi

echo "==> 拉取最新代码..."
git pull --ff-only

echo "==> 重建并启动容器..."
docker compose up -d --build

echo "==> 最近日志："
docker compose logs --tail 20
echo "==> 完成。面板地址: http://<本机IP>:8787"
