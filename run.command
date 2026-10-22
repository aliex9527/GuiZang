#!/bin/bash
# 从源码启动归藏（macOS / Linux）。首次运行前先执行 bash setup.sh
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "[错误] 还没建好 .venv，请先运行：bash setup.sh"
  read -r -p "按回车关闭…" _
  exit 1
fi
.venv/bin/python main.py
