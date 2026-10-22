#!/bin/bash
# 归藏工作区初始化（macOS / Linux）
# 用法：在终端里 bash setup.sh
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  归藏 · 工作区初始化"
echo "============================================================"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "[错误] 没有找到 python3。"
  echo "       装一个：https://www.python.org/downloads/ 或者 brew install python@3.13"
  exit 1
fi
echo "使用解释器：$PY"
"$PY" --version

# macOS 上 python3 可能是 Xcode 自带的 3.9，venv 能建但 PySide6 装不上，这里挡一下
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "[错误] 需要 Python 3.10 以上，当前版本偏低。"
  exit 1
}

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] 创建虚拟环境 .venv"
  "$PY" -m venv .venv
else
  echo "[1/3] .venv 已存在，跳过"
fi

echo "[2/3] 安装依赖（先试阿里云镜像，失败再走官方源）"
.venv/bin/python -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple --quiet || true
if ! .venv/bin/python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple; then
  echo "       镜像失败，改用官方源..."
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "[3/3] 生成图标"
.venv/bin/python tools/make_icon.py

echo
echo "完成。启动：./run.command（或 .venv/bin/python main.py）"
