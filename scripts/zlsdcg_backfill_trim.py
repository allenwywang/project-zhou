#!/usr/bin/env python3
"""回填修复：截掉 zlsdcg 个人站管线已发布 MD 里的作者引流尾块（含配图）。

背景（2026-11-23）：个人站管线原先只在「（完）/404文章获取/个人网站：」处截断引流尾块，
漏掉作者自带的「**更多交流，请关注小红圈（孤苑白首…）**」这一段——那段连同它后面那张
配图与正文无关，属于引流内容，不该留在正文里。管线侧已补规则
（`zlsdcg_process.trim_promo`），本脚本负责把存量已发布 MD 一并修掉。

规则与管线保持一致：调用 `zlsdcg_process.trim_promo`，不在本脚本里另写一套判断。

只处理 frontmatter `source` 为 zlsdcg.com 的 MD（公众号管线的 MD 归公众号管线管）。

用法（解释器需带 markdownify，用 doc-ingest 的 API venv）：
    <wapi-venv>/bin/python scripts/zlsdcg_backfill_trim.py --dry-run   # 只看影响面
    <wapi-venv>/bin/python scripts/zlsdcg_backfill_trim.py             # 实际修复（先备份）
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from zlsdcg_process import trim_promo  # noqa: E402  复用管线唯一的截断规则

KB = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
BACKUP = ROOT / "data" / "zlsdcg_archive" / "backfill_trim_backup"
REPORT = ROOT / "data" / "zlsdcg_archive" / "backfill_trim_report.json"
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(_attachments/([^)]+)\)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写任何文件")
    args = parser.parse_args()

    records = []
    for path in sorted(KB.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        head = text[:800]
        source = re.search(r'^source:\s*"([^"]+)"\s*$', head, re.M)
        if not source or not source.group(1).startswith(("http://zlsdcg.com", "https://zlsdcg.com")):
            continue
        kept, cut = trim_promo(text)
        if cut is None or kept == text:
            continue
        removed = text[len(kept):] if text.startswith(kept) else text[text.index(kept):]
        images = IMAGE_RE.findall(removed)
        records.append({"file": path.name, "cut_at_line": cut,
                        "removed_bytes": len(text.encode()) - len(kept.encode()),
                        "removed_images": images})

    payload = {"dry_run": args.dry_run, "files": len(records),
               "records": records}
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dry_run": args.dry_run, "待修文件": len(records),
                      "涉及图片": sum(len(r["removed_images"]) for r in records),
                      "报告": str(REPORT)}, ensure_ascii=False, indent=2))
    if args.dry_run or not records:
        return 0

    BACKUP.mkdir(parents=True, exist_ok=True)
    changed = 0
    for record in records:
        path = KB / record["file"]
        text = path.read_text(encoding="utf-8")
        kept, cut = trim_promo(text)
        if cut is None or kept == text:
            continue
        shutil.copy2(path, BACKUP / record["file"])
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(kept, encoding="utf-8")
        os.replace(temporary, path)
        changed += 1
    print(json.dumps({"已修复": changed, "备份目录": str(BACKUP)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
