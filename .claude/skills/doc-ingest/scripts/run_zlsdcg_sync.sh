#!/bin/bash
# zlsdcg.com 个人站管线（通道 C）启动器
#
# 为什么有这个封装：脚本本体在 project-zhou/scripts/（单一事实源，本 skill 不复制），
# 但这条链要跨两种解释器（HTML/MD 用 wapi venv，PDF/fitz 用 /usr/bin/python3）、
# 两个阶段（中间要人/LLM 做语义复核）、多个状态文件（缓存失效、批次与决定对应），
# 手工敲错一次代价很大。这层封装把这些约束一次做对。
#
# 用法：
#   scripts/run_zlsdcg_sync.sh prepare   # 抓取→建知识库索引→正文比对→生成本轮复核批次
#   scripts/run_zlsdcg_sync.sh publish   # 合并复核决定→暂存→图片本地化→发布→PDF→验收→报告
#
# 完整跑法（站点新增文章后）：
#   1) prepare                       # 自动失效 fetch 缓存、比对、生成批次
#   2) 语义复核：按 data/zlsdcg_archive/semantic_batches/batch-*.json 逐批判断，
#      决定写入 data/zlsdcg_archive/review_decisions/semantic-<NNN>.json（ID 集必须完全一致）
#   3) publish                       # 其余步骤全自动
#
# 规则与坑详见 project-zhou/AGENTS.md §5.6（全量）与 §5.7（增量）。
set -u

PROJ="${DOC_INGEST_PROJECT_ROOT:-/Users/allenwywang/allen个人项目/project-zhou}"
WORK="$PROJ/data/zlsdcg_archive"
PY="/usr/bin/python3"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAPI="${DOC_INGEST_WAPI_PYTHON:-$SKILL_DIR/services/wapi-venv/bin/python}"
PHASE="${1:-prepare}"

cd "$PROJ/scripts" || { echo "[错误] 找不到 $PROJ/scripts"; exit 1; }
[ -d "$WORK" ] || { echo "[错误] 找不到工作目录 $WORK（先跑过全量轮才会有）"; exit 1; }

# 前置自检：两套解释器的依赖
env -u PYTHONPATH "$PY" -c "import fitz" 2>/dev/null || { echo "[错误] /usr/bin/python3 缺 fitz（PyMuPDF）"; exit 2; }
"$WAPI" -c "import bs4, markdownify" 2>/dev/null || { echo "[错误] wapi venv 缺 bs4/markdownify"; exit 3; }

run_py()  { env -u PYTHONPATH "$PY" -u "$@"; }
run_wapi(){ env -u PYTHONPATH "$WAPI" -u "$@"; }

case "$PHASE" in
prepare)
  # fetch 缓存必须失效：站点新增文章会让分页整体错位，缓存不失效会拉回错页。
  if [ -d "$WORK/raw_pages" ]; then
    STAMP="$(date +%Y-%m-%d)"
    [ -d "$WORK/raw_pages_$STAMP" ] && rm -rf "$WORK/raw_pages"
    mv "$WORK/raw_pages" "$WORK/raw_pages_$STAMP"
    echo "[OK] 旧抓取缓存已归档为 raw_pages_$STAMP"
  fi
  run_py  zlsdcg_fetch.py      --workers 4
  run_py  zlsdcg_index_kb.py
  run_wapi zlsdcg_process.py   --prepare
  run_py  zlsdcg_compare.py
  run_py  zlsdcg_compact_review.py
  echo
  echo "[下一步] 语义复核：批次在 $WORK/semantic_batches/，"
  echo "         决定写到 $WORK/review_decisions/semantic-<NNN>.json（ID 集须与批次完全一致），"
  echo "         然后执行：scripts/run_zlsdcg_sync.sh publish"
  ;;

publish)
  run_py zlsdcg_finalize_review.py || { echo "[错误] 复核未完成，禁止发布（见 review_incomplete.json）"; exit 4; }
  APPROVED="$(env -u PYTHONPATH "$PY" - "$WORK/review_decisions.json" <<'PY'
import json, pathlib, sys
d = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(sum(1 for v in d.values() if v["decision"] == "new"))
PY
)"
  if [ "$APPROVED" = "0" ]; then
    echo "[OK] 本轮无新增文章，跳过发布与验收（上一轮验收记录仍有效）"
    exit 0
  fi
  echo "[OK] 本轮批准新增 $APPROVED 篇"
  run_wapi zlsdcg_publish.py --stage
  run_py   zlsdcg_finalize_assets.py   # 图片下载+本地化+验收（不要改用 download_assets.py）
  run_wapi zlsdcg_publish.py --publish
  run_py   zlsdcg_render_pdfs.py
  run_py   zlsdcg_verify.py             || exit 5
  run_py   zlsdcg_final_report.py
  ;;

*)
  echo "用法: $0 [prepare|publish]"; exit 1
  ;;
esac
