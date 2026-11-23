#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收官对账：索引 vs raw vs MD vs 广告 vs 失败，四方核对 + 缺图检查 + 最终报告。"""

import json
import datetime
import hashlib
import os
import re
import sys
import urllib.parse
from collections import Counter
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


def stable_id(link):
    """跨轮稳定的文章身份：mid+idx（link 的 sn 等运行期参数每轮都变）。"""
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    except Exception:
        return (link or "").split("#")[0].strip()
    mid = (query.get("mid") or [""])[0]
    idx = (query.get("idx") or [""])[0]
    return f"{mid}:{idx}" if mid and idx else (link or "").split("#")[0].strip()


def md_source(path):
    """MD frontmatter 里的 source，用于区分是哪条管线产出的。"""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:800]
    except OSError:
        return ""
    match = re.search(r'^source:\s*"([^"]+)"\s*$', head, re.M)
    return match.group(1) if match else ""


def safe_title(s):
    """与 wechat_archive.py 同名的标题清洗（渲染 MD 的目标文件名要用同一套规则）。"""
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    return (s or "无标题")[:60].rstrip()


def md_path_for(article):
    """文章对应的 MD 目标路径（渲染器用它命名，故此处必须同规则）。"""
    ts = article.get("publish_time") or 0
    try:
        stamp = datetime.datetime.fromtimestamp(int(ts)).strftime("%Y%m%d")
    except Exception:
        stamp = ""
    name = f"{stamp}_{safe_title((article.get('title') or '无标题').strip())}.md"
    return OBS / name


def pipe_of(source):
    if source.startswith("https://mp.weixin.qq.com"):
        return "mp.weixin.qq.com"
    if source.startswith("http://zlsdcg.com") or source.startswith("https://zlsdcg.com"):
        return "zlsdcg.com"
    return "其他"


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
    # 失败/广告台账按稳定身份匹配：link 的 sn 每轮都变，按整条 link 匹配会漏。
    fails = {}
    for line in open(FAILED, encoding="utf-8"):
        try:
            f = json.loads(line)
        except Exception:
            continue
        fails[stable_id(f.get("link", ""))] = f.get("reason", "")
    ads = set()
    if ADS.exists():
        for line in open(ADS, encoding="utf-8"):
            try:
                a = json.loads(line)
            except Exception:
                continue
            ads.add(stable_id(a.get("link", "")))

    have_raw = {a["link"] for a in arts if key(a["link"]) in raws}
    no_raw = [a for a in arts if key(a["link"]) not in raws]
    no_raw_perm = [a for a in no_raw if stable_id(a["link"]) in fails]
    no_raw_ads = [a for a in no_raw if stable_id(a["link"]) in ads]
    no_raw_other = [a for a in no_raw
                    if stable_id(a["link"]) not in fails and stable_id(a["link"]) not in ads]

    # MD 与图片
    mds = list(OBS.glob("*.md"))
    imgs = list((OBS / "_attachments").glob("*")) if (OBS / "_attachments").is_dir() else []
    img_names = {p.name for p in imgs}
    # 同一目录有多条管线（公众号直采 + zlsdcg 个人站），按 source 分开统计
    md_pipes = Counter(pipe_of(md_source(p)) for p in mds)

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
    print(f"索引文章（按 mid+idx 去重） : {len(arts)}")
    print(f"已抓 raw                   : {len(have_raw)}")
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
    for pipe, count in md_pipes.most_common():
        print(f"  其中 {pipe:<18}: {count}")
    print(f"图片文件数                 : {len(imgs)}")
    print(f"MD 引用但缺失的图片        : {missing_imgs}")
    print(f"疑似空 MD（<200B 非媒体卡）: {empty_md}")

    # 对账（逐篇判定，不做算术：MD 文件数 ≠ 文章数，同标题多篇会共用一个 MD）
    wechat_md = cross_pipe = ad_cases = unexplained = 0
    for a in arts:
        if key(a["link"]) not in raws:
            continue
        target = md_path_for(a)
        if target.exists():
            if pipe_of(md_source(target)) == "mp.weixin.qq.com":
                wechat_md += 1
            else:
                cross_pipe += 1
        elif stable_id(a["link"]) in ads:
            ad_cases += 1
        else:
            unexplained += 1
    total = wechat_md + cross_pipe + ad_cases + unexplained
    print("-" * 62)
    print(f"对账（公众号管线，逐篇判定）：有 raw 的文章 {total} 篇")
    print(f"  渲染为公众号 MD            : {wechat_md}")
    print(f"  跨管线同名（个人站已归档）  : {cross_pipe}")
    print(f"  广告剔除                   : {ad_cases}")
    print(f"  未归类（需关注）           : {unexplained}")
    if unexplained:
        print("⚠️ 有 raw 却没有 MD 也没记广告，需要人工看")
    return 0


if __name__ == "__main__":
    sys.exit(main())
