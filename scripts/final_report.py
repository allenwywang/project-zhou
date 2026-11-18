#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收官对账：索引 vs raw vs MD vs 广告 vs 失败，四方核对 + 缺图检查 + 最终报告。"""

import json
import hashlib
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
D = PROJECT_ROOT / "data" / "wechat_archive"
ARTICLES = D / "articles.jsonl"
FAILED = D / "failed.jsonl"
ADS = D / "ads.jsonl"
RAW = D / "raw"
OBS = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")


def key(link):
    return hashlib.sha1(link.split("#")[0].strip().encode()).hexdigest()[:16]


def jlen(p):
    try:
        return sum(1 for _ in open(p, encoding="utf-8"))
    except FileNotFoundError:
        return 0


def main():
    # 索引（按 link 去重）
    arts, seen = [], set()
    for line in open(ARTICLES, encoding="utf-8"):
        try:
            a = json.loads(line)
        except Exception:
            continue
        l = a.get("link")
        if not l or l in seen:
            continue
        seen.add(l)
        arts.append(a)

    raws = {f[:-5] for f in os.listdir(RAW) if f.endswith(".json")}
    fails = {}
    for line in open(FAILED, encoding="utf-8"):
        try:
            f = json.loads(line)
        except Exception:
            continue
        fails[f.get("link", "")] = f.get("reason", "")
    ads = set()
    if ADS.exists():
        for line in open(ADS, encoding="utf-8"):
            try:
                a = json.loads(line)
            except Exception:
                continue
            ads.add(a.get("link", ""))

    have_raw = {a["link"] for a in arts if key(a["link"]) in raws}
    no_raw = [a for a in arts if key(a["link"]) not in raws]
    no_raw_perm = [a for a in no_raw if a["link"] in fails and "违规" in fails[a["link"]]]
    no_raw_ads = [a for a in no_raw if a["link"] in ads]
    no_raw_other = [a for a in no_raw if a["link"] not in fails and a["link"] not in ads]

    # MD 与图片
    mds = list(OBS.glob("*.md"))
    imgs = list((OBS / "_attachments").glob("*")) if (OBS / "_attachments").is_dir() else []
    img_names = {p.name for p in imgs}

    # MD 引用的图片是否存在
    missing_imgs = 0
    empty_md = 0
    for md in mds:
        t = md.read_text(encoding="utf-8", errors="replace")
        for m in re.findall(r"!\[[^\]]*\]\(_attachments/([^)]+)\)", t):
            if m not in img_names:
                missing_imgs += 1
        if len(t) < 200 and "视频卡片" not in t and "纯媒体" not in t:
            empty_md += 1

    print("=" * 62)
    print("最终对账报告 · 周先生的茶馆四代目 · 公众号直采")
    print("=" * 62)
    print(f"索引文章（去重 link）      : {len(arts)}")
    print(f"已抓 raw                   : {len(have_raw)}")
    print(f"  其中渲染为 MD            : {len(mds)}")
    print(f"未抓 raw                   : {len(no_raw)}")
    print(f"  违规/删除（永久失效）    : {len(no_raw_perm)}")
    print(f"  广告卡                   : {len(no_raw_ads)}")
    print(f"  其他未抓（需关注）       : {len(no_raw_other)}")
    if no_raw_other:
        for a in no_raw_other[:10]:
            print(f"    - {a.get('title','')[:36]}")
    print(f"广告清单（含已抓）         : {jlen(ADS)}")
    print(f"失败清单                   : {jlen(FAILED)}")
    print("-" * 62)
    print(f"MD 文件数                  : {len(mds)}")
    print(f"图片文件数                 : {len(imgs)}")
    print(f"MD 引用但缺失的图片        : {missing_imgs}")
    print(f"疑似空 MD（<200B 非媒体卡）: {empty_md}")

    # 核对等式
    expect = len(have_raw)
    diff = expect - len(mds)
    print("-" * 62)
    print(f"对账：raw {expect} - MD {len(mds)} = {diff} "
          f"（广告/媒体卡剔除数，应≈{jlen(ADS)} + 纯媒体卡数）")
    if diff < 0:
        print("⚠️ MD 比 raw 还多，检查是否有重渲染残留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
