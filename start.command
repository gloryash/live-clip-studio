#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h}"
PORT=8788
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "没有找到 uv。请先安装 uv，再重新双击。"
  read "?按回车键关闭..."
  exit 1
fi

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 $PORT 已被其他进程占用。为保护现有任务，本启动器不会结束它："
  lsof -nP -iTCP:$PORT -sTCP:LISTEN
  echo "请关闭占用者，或在终端用其他端口启动 Live Clip Studio。"
  read "?按回车键关闭..."
  exit 1
fi

echo "正在同步本地依赖..."
uv sync --extra diarization

echo "Live Clip Studio 即将打开：http://127.0.0.1:8788"
(sleep 1; open http://127.0.0.1:8788) &
exec uv run uvicorn live_clip_studio.app:app --host 127.0.0.1 --port 8788
