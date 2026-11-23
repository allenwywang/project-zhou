#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
索引去重：把公众号历史文章标题与知识库已有的 JM 系列正文比对，
命中的文章不再重复抓正文（省掉最耗时的一步）。

已有正文来源（知识库，flat 存放）：
    历史学习资料/历史学习/raw/articles/茶馆杂谈/*.md   形如 20.11月-JM104-比例原则的边界.md

输出：
    data/wechat_archive/skip_titles.txt   命中的标题（每行一个），供 wechat_archive.py 跳过
    终端打印命中率与未命中的抽样
"""

import json
import os
import re
import sys
from pathlib import Path

WORK_ROOT = Path(os.environ.get("DOC_INGEST_WORKDIR", Path.home() / ".doc-ingest")).expanduser()
DATA_DIR = WORK_ROOT / "data" / "wechat_archive"
ARTICLES = DATA_DIR / "articles.jsonl"
SKIP_OUT = DATA_DIR / "skip_titles.txt"

KB_ROOT = Path(os.environ.get(
    "KB_CHAGUAN_DIR",
    "/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/JM系列"))

# 知识库里非 JM 的老文件（早期文章 / 其它），一并纳入比对
PUNCT = re.compile(r"[\s　-〿！-｠！-･‘’“”《》【】—…·,.;:!?\"'()\[\]{}<>~`@#\$%^&*_+=|\\/]+")


def norm(s: str) -> str:
    return PUNCT.sub("", (s or "").strip().lower())


def kb_titles():
    """返回 {规范化标题: 原始文件名} 与 {原始标题: 原始文件名}"""
    exact, raw = {}, {}
    if not KB_ROOT.is_dir():
        return exact, raw
    for p in KB_ROOT.rglob("*.md"):
        if p.parent.name in ("公众号直采",):
            continue
        stem = p.stem
        # 去掉 YY.MM月-JMxxx- 前缀
        t = re.sub(r"^\d{2}\.\d{2}月-", "", stem)
        t = re.sub(r"^JM早期文章-", "", t)
        t = re.sub(r"^JM\d+-", "", t)
        t = re.sub(r"^JM\d+[-_]", "", t)
        t = re.sub(r"^JM早期文章", "", t).strip(" -_")
        if not t:
            continue
        raw[t] = p.name
        exact.setdefault(norm(t), p.name)
    return exact, raw


def main():
    if not ARTICLES.exists():
        print("还没有 articles.jsonl，先跑 fetch")
        return 2

    arts = []
    seen = set()
    for line in ARTICLES.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(line)
        except Exception:
            continue
        t = a.get("title") or ""
        if not t or t in seen:
            continue
        seen.add(t)
        arts.append(a)

    exact, raw = kb_titles()
    print(f"知识库已有正文条目：{len(exact)} 个（规范化后）")
    print(f"公众号索引条目：{len(arts)} 篇")

    # 1) 精确命中
    hit_exact, rest = {}, []
    for a in arts:
        n = norm(a.get("title", ""))
        if n and n in exact:
            hit_exact[a["title"]] = exact[n]
        else:
            rest.append(a)

    # 2) 前缀命中：知识库标题被截断或带尾注时
    hit_prefix = {}
    still = []
    for a in rest:
        n = norm(a.get("title", ""))
        matched = None
        if len(n) >= 8:
            for kn, fname in exact.items():
                if len(kn) >= 8 and (kn.startswith(n) or n.startswith(kn)):
                    matched = fname
                    break
        if matched:
            hit_prefix[a["title"]] = matched
        else:
            still.append(a)

    total_hit = len(hit_exact) + len(hit_prefix)
    print(f"\n命中：精确 {len(hit_exact)} + 前缀 {len(hit_prefix)} = {total_hit} 篇"
          f"（{total_hit * 100.0 / max(1, len(arts)):.1f}%）")
    print(f"需抓正文：{len(still)} 篇")

    if hit_prefix:
        print("\n前缀命中样例：")
        for k, v in list(hit_prefix.items())[:8]:
            print(f"  公众号《{k}》  →  知识库 {v}")

    if still:
        print("\n未命中样例（前 15，供参考确认规则是否合理）：")
        for a in still[:15]:
            print(f"  {a.get('title','')[:52]}   [{a.get('publish_time',0)}]")

    SKIP_OUT.write_text("\n".join(sorted(list(hit_exact.keys()) + list(hit_prefix.keys()))),
                        encoding="utf-8")
    print(f"\n跳过清单已写入：{SKIP_OUT}")
    print("备注：跳过的文章不会出现在 公众号直采/，其正文已在知识库根目录（JM 系列）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
