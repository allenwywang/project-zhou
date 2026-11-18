#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理公众号直采 MD 尾部的引流块，只保留正文。

引流块的形态（2026-11-18 实测，覆盖 ~99% 文章）：
  正文结束
  （完）                                    ← 正文结束符（970/977 篇有；少数用「（未完待续）」）
  404文章获取：…                             ← 找文指引（与正文无关）
  个人网站：zlsdcg.com（即"周老师的茶馆"的拼音）
  微博（**注意加v的才是真的**）：… 主/次 …
  （请直接点击上面的小程序…）
  https://weibo.com/zhoulaoshidechaguan
  https://weibo.com/zhoulaoshideziliudi
  公众号：… 公众号2：… 视频号：… 头条号：…（各配二维码图）
  更多交流，请关注觅圈/红圈的二维码（《孤苑白首二十年》…副教主倒灶…JM系列…）
  如想继续阅读后文，可加入下图红圈/微密圈…不要冲动消费。
  ![](二维码图)

规则：
  1. 有（完）/（未完待续）：从该行起整块截断（其后只剩引流）。
  2. 无结束符但有 zlsdcg / 404文章获取：从「404文章获取：」或「个人网站」行截断。
  3. 完全无上述锚点的：不动（极少数，正文本来干净）。
  4. 图书广告特例（原价/特惠价紧贴正文）：仅当正文之后无 404 段且含「特惠价」时截断到该行前。

安全：
  - 只截断文件尾部（保留 frontmatter 与正文），从不碰文件前半部分
  - 幂等：重复运行第二次 0 改动
  - 每个改动记录到 data/wechat_archive/trim_log.jsonl（文件、截断行数、保留字节数）
  - 原文备份到 data/wechat_archive/trim_backup/（可整体还原）
"""

import glob
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = ("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
BACKUP = os.path.join(PROJECT_ROOT, "data", "wechat_archive", "trim_backup")
LOG = os.path.join(PROJECT_ROOT, "data", "wechat_archive", "trim_log.jsonl")

END_MARKS = ("（完）", "（未完待续）", "（未完）")
CUT_ANCHORS = ("404文章获取", "个人网站：zlsdcg", "个人网站：")
BOOK_AD_MARK = "特惠价"


def find_cut_line(lines):
    """返回应截断的行号（0-based，即保留 lines[:cut]），无则返回 None。"""
    # 1) 结束符：正文戛然而止的可靠信号
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s in END_MARKS or (s.startswith("（完") and len(s) <= 12):
            # 确认其后确有引流锚点（避免误伤以（完）结尾且无尾块的短文——截了也无害，但保守起见）
            rest = "\n".join(lines[i:])
            if ("zlsdcg" in rest or "404文章获取" in rest or "更多交流" in rest
                    or "weibo.com" in rest or "觅圈" in rest or "孤苑白首" in rest):
                return i
    # 2) 无结束符：用引流锚点（404 段 / 个人网站）
    for i, ln in enumerate(lines):
        if ln.strip().startswith(("404文章获取", "个人网站：")):
            return i
    # 3) 图书广告特例：正文后直接接书价
    for i, ln in enumerate(lines):
        if BOOK_AD_MARK in ln and i > 5:
            # 往上找最近的空行前的非空行，确认是「原价/套」形态
            rest = "\n".join(lines[i:i + 6])
            if "原价" in rest and "元/套" in rest:
                return i
    return None


def main():
    os.makedirs(BACKUP, exist_ok=True)
    files = sorted(glob.glob(os.path.join(D, "*.md")))
    n_cut = n_keep = 0
    logf = open(LOG, "a", encoding="utf-8")
    for f in files:
        with open(f, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        cut = find_cut_line(lines)
        if cut is None:
            n_keep += 1
            continue
        orig = "\n".join(lines) + "\n"
        # 去掉截断点之后的全部内容；再把截断点前连续的尾部空行收掉
        kept = lines[:cut]
        while kept and not kept[-1].strip():
            kept.pop()
        new = "\n".join(kept) + "\n"
        if new == orig:
            n_keep += 1
            continue
        name = os.path.basename(f)
        shutil.copy2(f, os.path.join(BACKUP, name))
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(new)
        n_cut += 1
        logf.write(json.dumps({
            "file": name, "cut_at_line": cut, "removed_lines": len(lines) - cut,
            "kept_bytes": len(new.encode()), "at": datetime.now(TZ).isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n")
    logf.close()
    print(f"处理 {len(files)} 个 MD：截断 {n_cut}，无需处理 {n_keep}")
    print(f"备份目录：{BACKUP}")
    print(f"日志：{LOG}")


if __name__ == "__main__":
    sys.exit(main())
