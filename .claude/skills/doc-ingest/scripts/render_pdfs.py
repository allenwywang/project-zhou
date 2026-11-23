#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号文章 MD → PDF 渲染归档。

输入：Obsidian 公众号直采目录下的 .md（已清洗引流块、图片已本地化到 _attachments/）
输出：资料库年度目录下的同名 .pdf（YYYYMMDD_标题.pdf → 资料库/<号名>/YYYY/）

做法：MD → 简洁 HTML（内嵌本地图片为 base64，离线自包含）→ Playwright/Chromium 打印。
依赖：/usr/bin/python3 的 site-packages 里有 playwright + fitz（本机已装）。
     需要 `python3 -m playwright install chromium` 一次（首次）。

跳过已存在的同名 PDF（增量）；--force 全量重打。
"""

import argparse
import base64
import glob
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))

MD_DIR = os.environ.get(
    "TRIM_TARGET_DIR",
    "/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
# PDF 资料库根：公众号来源 → 资料库/<ACCOUNT>/YYYY/
ARCHIVE_ROOT = os.environ.get(
    "PDF_ARCHIVE_ROOT",
    "/Users/allenwywang/allen个人项目/project-zhou/周老师茶馆历史文档")
ACCOUNT = os.environ.get("TEA_NICKNAME", "周先生的茶馆四代目")

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font: 12pt/1.9 "PingFang SC","Songti SC","Microsoft YaHei",serif;
         color:#222; max-width: 640px; margin: 0 auto; word-wrap: break-word; }}
  h1 {{ font-size: 17pt; margin: 0 0 4px; }}
  .meta {{ color:#888; font-size: 9pt; margin-bottom: 14px;
          border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
  img {{ max-width: 100%; height: auto; }}
  blockquote {{ color:#666; border-left: 3px solid #ccc; margin: 8px 0;
               padding: 2px 12px; }}
  a {{ color:#576b95; text-decoration: none; word-break: break-all; }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">{meta}</div>
{body}
</body></html>"""


def inline_images(md_text, base_dir):
    """把 MD 里 _attachments/x 引用换成 data URI（离线自包含）。"""

    def repl(m):
        rel = m.group(1)
        p = os.path.join(base_dir, rel)
        if not os.path.exists(p):
            return m.group(0)
        mime = mimetypes.guess_type(p)[0] or "image/jpeg"
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        return f"data:{mime};base64,{b64}"

    return re.sub(r"!\[[^\]]*\]\((_attachments/[A-Za-z0-9_.\-]+)\)",
                  lambda m: f"![]({repl(m)})", md_text)


def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r'^(\w+):\s*"(.*)"$', line.strip())
            if mm:
                meta[mm.group(1)] = mm.group(2)
        text = text[m.end():]
    return meta, text


def md_to_html(md_text):
    """轻量 MD→HTML：标题/粗体/引用/图片/链接/段落。正文以文字为主，够用。"""
    out = []
    in_quote = False
    for ln in md_text.splitlines():
        s = ln.rstrip()
        esc = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        # 链接 [t](u)
        esc = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', esc)
        # 粗体 **x**
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        # 图片 ![](src)
        esc = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', esc)
        if s.startswith("# "):
            if in_quote:
                out.append("</blockquote>"); in_quote = False
            out.append(f"<h2>{esc[2:]}</h2>")
        elif s.startswith("> "):
            if not in_quote:
                out.append("<blockquote>"); in_quote = True
            out.append(esc[2:])
        else:
            if in_quote:
                out.append("</blockquote>"); in_quote = False
            if s.strip():
                out.append(f"<p>{esc}</p>")
            else:
                out.append("")
    if in_quote:
        out.append("</blockquote>")
    return "\n".join(out)


def year_of(fname, meta):
    d = fname[:8]
    try:
        return f"{int(d[:4])}"
    except Exception:
        return str(datetime.now(TZ).year)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="重打已存在的 PDF")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 篇（0=不限）")
    args = ap.parse_args()

    mds = sorted(glob.glob(os.path.join(MD_DIR, "*.md")))
    if args.limit:
        mds = mds[:args.limit]
    n_new = n_skip = n_fail = 0

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for md in mds:
            base = os.path.basename(md)
            stem = base[:-3]
            meta, body = parse_frontmatter(open(md, encoding="utf-8").read())
            year = year_of(stem, meta)
            out_dir = os.path.join(ARCHIVE_ROOT, ACCOUNT, year)
            os.makedirs(out_dir, exist_ok=True)
            pdf_path = os.path.join(out_dir, stem + ".pdf")
            if os.path.exists(pdf_path) and not args.force:
                n_skip += 1
                continue
            html_body = md_to_html(inline_images(body, MD_DIR))
            meta_line = " · ".join(
                x for x in (meta.get("date"), meta.get("author"), ACCOUNT) if x)
            html = HTML_TMPL.format(title=meta.get("title", stem),
                                    meta=meta_line, body=html_body)
            tmp = pdf_path + ".html"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            try:
                page.goto("file://" + tmp, wait_until="networkidle")
                page.wait_for_timeout(300)  # data URI 解码余量
                page.pdf(path=pdf_path, format="A4", print_background=True,
                         margin={"top": "18mm", "bottom": "18mm",
                                 "left": "16mm", "right": "16mm"})
                n_new += 1
            except Exception as e:
                n_fail += 1
                print(f"  FAIL {base[:40]}: {e}", file=sys.stderr)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        browser.close()

    print(f"PDF 渲染：新增 {n_new}，跳过 {n_skip}，失败 {n_fail}")
    print(f"输出根目录：{os.path.join(ARCHIVE_ROOT, ACCOUNT)}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
