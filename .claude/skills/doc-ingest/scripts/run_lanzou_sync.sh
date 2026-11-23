#!/bin/bash
# 蓝奏云+坚果云通道启动器（茶馆杂谈 JM/python 系列文档同步）
#
# 为什么有这个封装：sync.py 必须在 project-zhou/scripts/ 下运行（progress.json/
# 下载目录都是项目相对路径），且 AI 会话里要规避 WorkBuddy 沙箱注入
# （PYTHONPATH shim 会把 mkdir 伪报 EEXIST）、并保证 7z 在 PATH 里。
# 本脚本把这三件事一次做对，用户侧永远不需要记参数。
#
# 用法（参数原样透传给 sync.py）：
#   scripts/run_lanzou_sync.sh               # 从 progress.json 续跑（约每半月一次）
#   scripts/run_lanzou_sync.sh 0624          # 首次/强制指定起点
#   scripts/run_lanzou_sync.sh --headless    # 后台跑（隐藏浏览器窗口）
set -u

PROJ="${DOC_INGEST_PROJECT_ROOT:-/Users/allenwywang/allen个人项目/project-zhou}"
cd "$PROJ/scripts" || { echo "找不到 $PROJ/scripts"; exit 1; }

# 前置自检：解释器依赖 + 7z
if ! env -u PYTHONPATH /usr/bin/python3 -c "import playwright, fitz, pdfplumber" 2>/dev/null; then
  echo "[错误] /usr/bin/python3 缺 playwright/fitz/pdfplumber，先装依赖"; exit 2
fi
if ! /opt/homebrew/bin/7z >/dev/null 2>&1 && ! command -v 7z >/dev/null 2>&1; then
  echo "[错误] 找不到 7z（brew install p7zip）"; exit 3
fi

exec env -u PYTHONPATH PATH="/opt/homebrew/bin:/usr/bin:/bin" \
     /usr/bin/python3 sync.py "$@"
