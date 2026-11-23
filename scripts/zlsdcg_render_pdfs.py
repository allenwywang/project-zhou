#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zlsdcg.com 新文章：暂存 MD → PDF 归档渲染器。

输入：data/zlsdcg_archive/publish_manifest.json（数组，每项含 stem / year / staging_md）
输出：周老师茶馆历史文档/周先生的茶馆四代目/<year>/<stem>.pdf

边界（本脚本只做渲染，不做候选筛选）：
  - 只读清单指定的 staging_md，图片按相对 MD 目录的本地路径解析并 base64 内嵌；
  - 目标 PDF 已存在则跳过，绝不覆盖；目标目录可按清单 year 创建；
  - 不向资料库写任何 .md；失败条目保留在清单里供下次重试。

用法：
  env -u PYTHONPATH /usr/bin/python3 scripts/zlsdcg_render_pdfs.py --check-inputs
  env -u PYTHONPATH /usr/bin/python3 scripts/zlsdcg_render_pdfs.py
  env -u PYTHONPATH /usr/bin/python3 scripts/zlsdcg_render_pdfs.py --self-test
"""

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

TZ = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "zlsdcg_archive" / "publish_manifest.json"
DEFAULT_RESULTS = PROJECT_ROOT / "data" / "zlsdcg_archive" / "publish_pdf_results.json"
ARCHIVE_ROOT = PROJECT_ROOT / "周老师茶馆历史文档" / "周先生的茶馆四代目"
DEFAULT_ACCOUNT = "周先生的茶馆四代目"
SELF_TEST_DIR = PROJECT_ROOT / "data" / "zlsdcg_archive" / "pdf_self_test"

# 1x1 PNG（程序生成的最小合法 PNG，自测用）
SELF_TEST_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

TERMINAL_PUNCT = set("。！？…；：.!?;:”）」』】》〉～—\"'")

HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font: 12pt/1.9 "PingFang SC","Songti SC","Microsoft YaHei",serif;
         color:#222; max-width: 640px; margin: 0 auto; word-wrap: break-word; }}
  h1 {{ font-size: 17pt; margin: 0 0 4px; }}
  h2 {{ font-size: 14pt; margin: 18px 0 6px; }}
  h3, h4, h5, h6 {{ font-size: 12.5pt; margin: 14px 0 4px; }}
  .meta {{ color:#888; font-size: 9pt; margin-bottom: 14px;
          border-bottom: 1px solid #ddd; padding-bottom: 8px; }}
  p {{ margin: 0 0 10px; }}
  img {{ max-width: 100%; height: auto; }}
  blockquote {{ color:#666; border-left: 3px solid #ccc; margin: 8px 0;
               padding: 2px 12px; }}
  pre {{ background:#f6f6f6; padding: 8px 10px; font-size: 9.5pt;
        white-space: pre-wrap; word-wrap: break-word; }}
  a {{ color:#576b95; text-decoration: none; word-break: break-all; }}
  .img-missing {{ color:#999; }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">{meta}</div>
{body}
</body></html>"""


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


# ---------------------------------------------------------------- 输入处理

def load_manifest(path):
    """返回 (entries, error)。清单不存在/空 → ([], None)。"""
    p = Path(path)
    if not p.exists():
        return [], None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return [], f"清单无法解析为 JSON：{e}"
    if not isinstance(data, list):
        return [], "清单顶层必须是数组"
    return data, None


def parse_frontmatter(text):
    """返回 (meta, body)。支持带引号/不带引号的 key: value。"""
    text = text.replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line.strip())
            if not mm:
                continue
            key, val = mm.group(1), mm.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            meta[key] = val
        text = text[m.end():]
    return meta, text


def iter_image_srcs(md_text):
    """抽出所有 MD 图片引用里的原始 src（按出现顺序，含重复）。"""
    return [m.group(2).strip() for m in
            re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", md_text)]


def resolve_local_image(src, base_dir):
    """本地图片 → (Path, None)；远程/data URI → (None, 原因)。"""
    raw = src.strip()
    if not raw:
        return None, "空路径"
    first = raw.split()[0]
    if first.startswith("data:"):
        return None, "data-uri"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", first):
        return None, "远程图片未本地化"
    rel = unquote(first)
    p = Path(base_dir) / rel
    return p, None


def image_data_uri(src, base_dir, warnings):
    p, reason = resolve_local_image(src, base_dir)
    if p is None:
        if reason != "data-uri":
            warnings.append(f"图片未内嵌：{src}（{reason}）")
        return None
    if not p.is_file():
        warnings.append(f"图片缺失：{p}")
        return None
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    try:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:
        warnings.append(f"图片读取失败：{p}（{e}）")
        return None
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------- MD → HTML

def _emph(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"<em>\1</em>", s)
    return s


def render_inline(text, base_dir, warnings):
    """行内元素：图片 / 链接 / 粗体 / 斜体；标题与 URL 均转义。"""
    tokens = []

    def stash(fragment):
        tokens.append(fragment)
        return "\x00%d\x00" % (len(tokens) - 1)

    def img_repl(m):
        alt, src = m.group(1), m.group(2)
        data = image_data_uri(src, base_dir, warnings)
        if data is None:
            return stash('<span class="img-missing">[图片]</span>')
        return stash('<img src="%s" alt="%s">' % (data, html.escape(alt, quote=True)))

    def link_repl(m):
        label = m.group(1)
        raw = m.group(2).strip()
        href = raw.split()[0] if raw else ""
        label_html = _emph(html.escape(label, quote=False))
        return stash('<a href="%s">%s</a>' % (html.escape(href, quote=True), label_html))

    def code_repl(m):
        return stash("<code>%s</code>" % html.escape(m.group(1), quote=False))

    text = re.sub(r"`([^`\n]+)`", code_repl, text)
    # Linked images must be stashed before ordinary links. Otherwise the outer
    # link consumes the whole construct and its nested image disappears.
    def linked_image_repl(m):
        href = html.escape(m.group(2).strip().split()[0], quote=True)
        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", m.group(1))
        alt, src = image_match.groups()
        data = image_data_uri(src, base_dir, warnings)
        if data is None:
            image = '<span class="img-missing">[图片]</span>'
        else:
            image = '<img src="%s" alt="%s">' % (data, html.escape(alt, quote=True))
        return stash('<a href="%s">%s</a>' % (href, image))

    linked_image_re = re.compile(r"\[(!\[[^\]]*\]\([^)]+\))\]\(([^)]+)\)")
    text = linked_image_re.sub(linked_image_repl, text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_repl, text)
    text = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", link_repl, text)
    text = html.escape(text, quote=False)
    text = _emph(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)


def _join_lines(prev, nxt):
    """行拼接：中英文交界处补空格，其余直接相连（对齐项目排版规则）。"""
    if not prev:
        return nxt
    a, b = prev[-1], nxt[0]
    if a.isascii() and b.isascii() and (a.isalnum() or a in ",.;:!?)]}\"'") \
            and (b.isalnum() or b in "([{\"'$"):
        return prev + " " + nxt
    return prev + nxt


def md_to_html(md_text, base_dir, warnings):
    lines = md_text.replace("\r\n", "\n").split("\n")
    out, para, i = [], [], 0
    in_quote = False

    def close_quote():
        nonlocal in_quote
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>%s</p>" % "<br>".join(para))
            para = []

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        # 围栏代码块
        if stripped.startswith("```"):
            flush_para()
            close_quote()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            out.append("<pre><code>%s</code></pre>"
                       % html.escape("\n".join(code), quote=False))
            continue

        if not stripped:
            flush_para()
            close_quote()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_quote()
            level = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (level, render_inline(m.group(2), base_dir, warnings), level))
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            close_quote()
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            content = stripped[1:].lstrip()
            if content:
                out.append("<p>%s</p>" % render_inline(content, base_dir, warnings))
            i += 1
            continue

        m = re.match(r"^([-*+]|\d+\.)\s+(.*)$", stripped)
        if m:
            flush_para()
            close_quote()
            ordered = m.group(1)[0].isdigit()
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                mm = re.match(r"^([-*+]|\d+\.)\s+(.*)$", lines[i].strip())
                if not mm:
                    break
                items.append("<li>%s</li>" % render_inline(mm.group(2), base_dir, warnings))
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
            continue

        close_quote()
        rendered = render_inline(stripped, base_dir, warnings)
        if para and lines[i - 1].strip() and lines[i - 1].strip()[-1] in TERMINAL_PUNCT:
            flush_para()
        if para:
            para[-1] = _join_lines(para[-1], rendered) if not rendered.startswith("<") else para[-1] + rendered
        else:
            para.append(rendered)
        i += 1

    flush_para()
    close_quote()
    return "\n".join(out)


def build_html(meta, stem, body_html):
    title = meta.get("title") or stem
    account = meta.get("account") or meta.get("author") or DEFAULT_ACCOUNT
    meta_bits = [html.escape(x) for x in (meta.get("date"), account) if x]
    source = (meta.get("source") or "").strip()
    if source:
        meta_bits.append('<a href="%s">原文链接</a>' % html.escape(source, quote=True))
    return HTML_TMPL.format(title=html.escape(title, quote=False),
                            meta=" · ".join(meta_bits),
                            body=body_html)


# ---------------------------------------------------------------- 校验

def validate_entries(entries, out_root=ARCHIVE_ROOT):
    """返回 (problems, warnings, conflicts, ready)。

    problems = 逐篇阻断（不渲染该篇/整批）；warnings = 可降级继续（如图片缺失，
    渲染时保留占位）；conflicts = 目标已存在将跳过。
    """
    problems, warnings, conflicts, ready = [], [], [], []
    out_root = Path(out_root)
    seen = set()
    for idx, e in enumerate(entries):
        tag = f"#{idx + 1}"
        if not isinstance(e, dict):
            problems.append(f"{tag} 条目不是对象")
            continue
        stem = str(e.get("stem") or "").strip()
        year = str(e.get("year") or "").strip()
        staging = str(e.get("staging_md") or "").strip()
        label = stem or tag
        if not stem:
            problems.append(f"{tag} 缺少 stem")
            continue
        if not re.fullmatch(r"[0-9]{4}", year):
            problems.append(f"{label} year 非 4 位年份：{year or '(空)'}")
        if any(ch in stem for ch in "/\\") or stem in (".", ".."):
            problems.append(f"{label} stem 含路径分隔符，拒绝写入")
            continue
        if not staging:
            problems.append(f"{label} 缺少 staging_md")
            continue
        key = (year, stem)
        if key in seen:
            problems.append(f"{label} 清单内重复（{year}/{stem}）")
            continue
        seen.add(key)
        md = Path(staging)
        if not md.is_file():
            problems.append(f"{label} staging_md 不存在：{staging}")
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception as ex:
            problems.append(f"{label} MD 读取失败（需 UTF-8）：{ex}")
            continue
        meta, body = parse_frontmatter(text)
        if not meta.get("title"):
            problems.append(f"{label} frontmatter 缺少 title")
        if not body.strip():
            problems.append(f"{label} 正文为空")
        warns = []
        for src in iter_image_srcs(body):
            p, reason = resolve_local_image(src, md.parent)
            if p is None:
                if reason == "远程图片未本地化":
                    warns.append(f"远程图片未本地化：{src}")
                else:
                    problems.append(f"{label} 图片无法内嵌：{src}（{reason}）")
            elif not p.is_file():
                warns.append(f"本地图片缺失，渲染时留占位：{p}")
        warnings.extend(f"{label} {w}" for w in warns)
        target = out_root / year / f"{stem}.pdf"
        if target.exists():
            conflicts.append((label, str(target)))
        ready.append({"idx": idx, "stem": stem, "year": year, "staging_md": str(md),
                      "target": str(target), "warnings": warns})
    return problems, warnings, conflicts, ready


def check_inputs(manifest_path):
    entries, err = load_manifest(manifest_path)
    if err:
        log("FAIL", err)
        return 1
    if not entries:
        log("OK", "输入清单尚未生成")
        return 0
    problems, warnings, conflicts, ready = validate_entries(entries)
    for label, target in conflicts:
        log("SKIP", f"{label} 目标已存在，将跳过：{target}")
    for w in warnings:
        log("WARN", w)
    for p in problems:
        log("FAIL", p)
    log("OK" if not problems and not warnings else "FAIL",
        f"清单 {len(entries)} 条：可渲染 {len(ready) - len(conflicts)}，目标冲突跳过 "
        f"{len(conflicts)}，警告 {len(warnings)}，问题 {len(problems)}")
    return 0 if not problems and not warnings else 1


# ---------------------------------------------------------------- 渲染

def render_manifest(manifest_path, out_root, results_path, limit=0, start=0,
                    shard_index=0, shard_count=1):
    entries, err = load_manifest(manifest_path)
    if err:
        log("FAIL", err)
        return 1
    if not entries:
        log("OK", "输入清单尚未生成")
        return 0

    out_root = Path(out_root)
    problems, warnings, _conflicts, ready = validate_entries(entries, out_root)
    for w in warnings:
        log("WARN", w)
    if problems or warnings:
        for p in problems:
            log("FAIL", p)
        log("FAIL", "清单存在输入问题或图片警告，未开始渲染（请先修复清单或 --check-inputs 排查）")
        return 1
    if limit:
        ready = ready[:limit]
    ready = ready[start:]
    ready = [item for position, item in enumerate(ready) if position % shard_count == shard_index]

    from playwright.sync_api import sync_playwright

    out_root = Path(out_root)
    results = []
    n_new = n_skip = n_fail = n_warn = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page()
        for item in ready:
            stem, year = item["stem"], item["year"]
            target = Path(item["target"])
            if target.exists():
                log("SKIP", f"{stem} 已存在")
                n_skip += 1
                results.append({"stem": stem, "year": year, "target": str(target),
                                "status": "skipped", "reason": "target_exists"})
                continue
            md = Path(item["staging_md"])
            warnings = []
            try:
                text = md.read_text(encoding="utf-8")
                meta, body = parse_frontmatter(text)
                body_html = md_to_html(body, md.parent, warnings)
                doc = build_html(meta, stem, body_html)
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(f".{stem}.{os.getpid()}.tmp.pdf")
                page.set_content(doc, wait_until="load")
                page.wait_for_timeout(300)
                page.pdf(path=str(tmp), format="A4", print_background=True,
                         display_header_footer=False,
                         margin={"top": "18mm", "bottom": "18mm",
                                 "left": "16mm", "right": "16mm"})
                if target.exists():
                    tmp.unlink(missing_ok=True)
                    log("SKIP", f"{stem} 渲染后目标已出现，丢弃临时文件")
                    n_skip += 1
                    results.append({"stem": stem, "year": year, "target": str(target),
                                    "status": "skipped", "reason": "target_exists"})
                    continue
                os.replace(tmp, target)
                n_new += 1
                tag = "WARN" if warnings else "OK"
                n_warn += 1 if warnings else 0
                log(tag, f"{stem} -> {target}" + ("；" + "；".join(warnings) if warnings else ""))
                results.append({"stem": stem, "year": year, "target": str(target),
                                "status": "rendered", "warnings": warnings})
            except Exception as ex:
                n_fail += 1
                for tmpf in target.parent.glob(f".{stem}.*.tmp.pdf"):
                    tmpf.unlink(missing_ok=True)
                log("FAIL", f"{stem} 渲染失败：{ex}")
                results.append({"stem": stem, "year": year, "target": str(target),
                                "status": "failed", "error": str(ex)})
        browser.close()

    payload = {
        "generated_at": now_iso(),
        "manifest": str(manifest_path),
        "out_root": str(out_root),
        "summary": {"total": len(ready), "rendered": n_new, "skipped": n_skip,
                    "failed": n_fail, "with_warnings": n_warn},
        "items": results,
    }
    results_path = Path(results_path)
    merged = {}
    if results_path.is_file():
        try:
            previous = json.loads(results_path.read_text(encoding="utf-8"))
            if previous.get("manifest") == str(manifest_path) and previous.get("out_root") == str(out_root):
                merged = {(item["year"], item["stem"]): item for item in previous.get("items", [])}
        except Exception as exc:
            log("FAIL", f"既有渲染结果无法合并，停止以免丢失审计记录：{exc}")
            return 1
    merged.update({(item["year"], item["stem"]): item for item in results})
    cumulative = [merged[(item["year"], item["stem"])] for item in ready
                  if (item["year"], item["stem"]) in merged]
    counts = {status: sum(item["status"] == status for item in cumulative)
              for status in ("rendered", "skipped", "failed")}
    payload["last_run"] = payload["summary"]
    payload["summary"] = {"total": len(cumulative), **counts,
                          "with_warnings": sum(bool(item.get("warnings")) for item in cumulative)}
    payload["items"] = cumulative
    results_path = Path(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_results = results_path.with_name(results_path.name + ".tmp")
    tmp_results.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    os.replace(tmp_results, results_path)
    log("OK" if n_fail == 0 else "FAIL",
        f"本次 {len(ready)}：渲染 {n_new}，跳过 {n_skip}，失败 {n_fail}，带警告 {n_warn}")
    log("OK" if not payload["summary"]["failed"] else "FAIL",
        f"累计 {payload['summary']}")
    log("OK", f"结果记录：{results_path}")
    return 0 if not payload["summary"]["failed"] else 1


# ---------------------------------------------------------------- 自测

def self_test():
    """在 pdf_self_test/ 造最小中文 MD + 1x1 PNG，渲染到临时目录并用 fitz 验证。"""
    SELF_TEST_DIR.mkdir(parents=True, exist_ok=True)
    png_path = SELF_TEST_DIR / "selftest_1x1.png"
    png_bytes = base64.b64decode(SELF_TEST_PNG_B64)
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        log("FAIL", "内置 PNG 常量不是合法 PNG")
        return 1
    png_path.write_bytes(png_bytes)

    md_path = SELF_TEST_DIR / "selftest_归档渲染测试.md"
    md_content = (
        "---\n"
        'title: "归档渲染测试"\n'
        'date: "2026-11-22 09:00"\n'
        'source: "https://example.com/selftest?a=1&b=2"\n'
        'account: "周先生的茶馆四代目"\n'
        "---\n\n"
        "# 归档渲染测试\n\n"
        "这是一段**归档渲染测试**的正文，包含[链接](https://example.com/?x=1&y=2)与*斜体*。\n\n"
        "![](selftest_1x1.png)\n\n"
        "第二段用于确认分页与文本提取。\n"
    )
    md_path.write_text(md_content, encoding="utf-8")

    workdir = Path(tempfile.mkdtemp(prefix="zlsdcg_pdf_selftest_"))
    try:
        manifest = workdir / "manifest.json"
        manifest.write_text(json.dumps([{
            "stem": "selftest_归档渲染测试",
            "year": "2099",
            "staging_md": str(md_path),
        }], ensure_ascii=False, indent=2), encoding="utf-8")
        results = workdir / "results.json"
        out_root = workdir / "out"

        problems, warnings, conflicts, ready = validate_entries(
            json.loads(manifest.read_text(encoding="utf-8")), out_root)
        if problems:
            log("FAIL", "自测校验未通过：" + "；".join(problems))
            return 1

        rc = render_manifest(manifest, out_root, results)
        if rc != 0:
            log("FAIL", "自测渲染返回非 0")
            return 1

        pdf_path = out_root / "2099" / "selftest_归档渲染测试.pdf"
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            log("FAIL", f"自测未产出 PDF：{pdf_path}")
            return 1

        import fitz
        with fitz.open(str(pdf_path)) as doc:
            pages = doc.page_count
            text = "\n".join(doc[p].get_text() for p in range(pages))
            images = {image[0] for page in doc for image in page.get_images(full=True)}
        if len(images) != 1:
            log("FAIL", f"自测 PDF 图片数量异常：{len(images)}")
            return 1
        if pages < 1:
            log("FAIL", f"自测 PDF 页数不足：{pages}")
            return 1
        if "归档渲染测试" not in text:
            log("FAIL", "自测 PDF 文本未包含「归档渲染测试」")
            return 1
        if "example.com" not in text and "原文链接" not in text:
            log("WARN", "自测 PDF 未检出链接文本（不阻断）")
        log("OK", f"自测通过：页数 {pages}，文本 {len(text)} 字，PDF {pdf_path}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="zlsdcg 新文章 MD → PDF 归档渲染")
    ap.add_argument("--check-inputs", action="store_true",
                    help="只校验清单/MD/图片/目标冲突，不渲染")
    ap.add_argument("--self-test", action="store_true",
                    help="用 pdf_self_test/ 的最小样例验证渲染链路")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--out-root", default=str(ARCHIVE_ROOT))
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--limit", type=int, default=0, help="最多渲染 N 篇（0=全部）")
    ap.add_argument("--start", type=int, default=0, help="从清单的 N 条之后开始（0=开头）")
    ap.add_argument("--shard-index", type=int, default=0, help="当前分片序号，从 0 开始")
    ap.add_argument("--shard-count", type=int, default=1, help="按清单位置划分互斥分片数")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.check_inputs:
        return check_inputs(args.manifest)
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        ap.error("shard index/count 无效")
    return render_manifest(args.manifest, args.out_root, args.results, args.limit,
                           args.start, args.shard_index, args.shard_count)


if __name__ == "__main__":
    sys.exit(main())
