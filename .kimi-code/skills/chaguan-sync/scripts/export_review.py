#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出供 LLM 语义复查的比对材料：格式化后的 MD + 源 PDF 的物理行。

为什么需要这个
--------------
排版规则把「PDF 物理行」重排成「逻辑自然段」。要判断排版对不对，必须同时看到
**排版结果**和**源物理行**——只看结果，agent 无法区分：
  - 「这一段被错误切成了两段」（结果里两段都很短很怪）
  - 「原文本来就是两个独立段落，只是恰好都短」（结果里两段都正常）
  - 「这一段被错误合并了两段」（结果里一段很长）
只看源 PDF 也无法判断，因为 PDF 里根本没有段落概念。

本脚本导出三份材料：
  1. MD（排版后）—— 待检对象
  2. SRC（源 PDF 物理行）—— 判断依据
  3. CHARS（正文可见字符序列）—— 修复时必须守恒的基线

用法
----
    cd /Users/allenwywang/allen个人项目/project-zhou
    env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/export_review.py \
        --name "26.10月-JM1141-秦楚之争（63）.md" --out-dir /tmp/chaguan_review

输出目录结构：
    /tmp/chaguan_review/<stem>/
        md.md     排版后的 Markdown（待检对象）
        src.txt   源 PDF 的物理行文本（判断依据）
        meta.json 元信息（字符数、段落数、源 PDF 路径）
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import md_layout  # noqa: E402
import naming    # noqa: E402

HISTORY_KB_ROOT = PROJECT_ROOT.parent / "历史学习资料"
MARKDOWN_DIR = HISTORY_KB_ROOT / "历史学习" / "raw" / "articles" / "茶馆杂谈"
# 蓝奏云管线的 MD 在 JM系列/ 子目录（2026-11-18 起），公众号直采在平级目录。
JM_MD_DIR = MARKDOWN_DIR / "JM系列"
LIBRARY_DIR = PROJECT_ROOT / "周老师茶馆历史文档"
DOWNLOAD_DIR = PROJECT_ROOT / "茶馆杂谈文件同步"


def find_source_pdf(stem):
    """按同 stem 找源 PDF：优先项目资料库（唯一归属地），退回下载目录。"""
    for p in LIBRARY_DIR.rglob(stem + ".pdf"):
        return p
    p = DOWNLOAD_DIR / (stem + ".pdf")
    return p if p.is_file() else None


def pdf_physical_lines(pdf_path):
    """抽取 PDF 的物理行，**严格复刻 pdf_to_md.PdfConverter._convert_light 的取文逻辑**。

    复刻要点（不一致会让 agent 拿错基线）：
    - 双引擎（pdfplumber + fitz）逐页提取，fitz 长度 > pdfplumber 长度 * 1.2 时取 fitz
    - 逐页 strip 后丢弃空页
    - 页内按 splitlines 拆行、strip 后丢弃空行

    返回 (lines, page_breaks)：lines 是物理行；page_breaks[i] = True 表示
    lines[i] 是该页最后一行（页与页之间原本有空行，跨页处自然断开）。
    """
    import pdfplumber
    import fitz

    pl_pages = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                pl_pages.append(page.extract_text() or "")
    except Exception as e:
        print("[WARN] pdfplumber 失败 %s: %s" % (pdf_path.name, e))

    fitz_pages = []
    try:
        doc = fitz.open(str(pdf_path))
        for page in doc:
            fitz_pages.append(page.get_text() or "")
        doc.close()
    except Exception as e:
        print("[WARN] fitz 失败 %s: %s" % (pdf_path.name, e))

    out = []
    breaks = []
    for i in range(max(len(pl_pages), len(fitz_pages))):
        pl = pl_pages[i] if i < len(pl_pages) else ""
        fx = fitz_pages[i] if i < len(fitz_pages) else ""
        txt = fx if len(fx.strip()) > len(pl.strip()) * 1.2 else pl
        if not txt.strip():
            continue
        lines = [line.strip() for line in txt.splitlines() if line.strip()]
        for j, line in enumerate(lines):
            out.append(line)
            breaks.append(j == len(lines) - 1)   # 页末标记
    return out, breaks


def build_para_map(md_text, pdf_path):
    """建立「MD 段落序号 -> 源物理行区间」映射。

    做法：把 MD 的正文段落逐个在 src 物理行序列里做贪心前缀匹配
    （MD 段落是若干物理行拼接的结果，去空白后应等于这些行的拼接）。
    匹配不上的段落标 src_range=null，说明该段来自页内非行结构（如表格）。

    段落切分口径必须与 precheck.body_paragraphs **完全一致**，
    否则 agent 按 precheck 报的段落号查 para_map 会错位。
    """
    import precheck

    lines, _ = pdf_physical_lines(pdf_path)
    flat = [md_layout.visible(l) for l in lines]

    paras = precheck.body_paragraphs(md_text)

    out = []
    pos = 0
    for p in paras:
        target = md_layout.visible(p)
        start = pos
        acc = ""
        end = None
        while pos < len(flat):
            acc += flat[pos]
            pos += 1
            if acc == target:
                end = pos - 1
                break
            if len(acc) > len(target):
                break          # 失配，回退
        if end is None:
            pos = start      # 未匹配，下一段从原位重试
            # 退化匹配：允许跳过若干行（PDF 首行往往是标题，MD 里没有）
            for skip in range(start + 1, min(start + 4, len(flat))):
                acc = ""
                j = skip
                while j < len(flat):
                    acc += flat[j]
                    j += 1
                    if acc == target:
                        end = j - 1
                        pos = j
                        break
                    if len(acc) > len(target):
                        break
                if end is not None:
                    break
        if end is None:
            out.append({"para": len(out) + 1, "src_range": None,
                        "chars": len(target),
                        "text_head": p[:40]})
        else:
            out.append({"para": len(out) + 1,
                        "src_range": [start + 1 if end is not None else start + 1,
                                      end + 1],   # 1-based，闭区间
                        "chars": len(target),
                        "text_head": p[:40]})
    return out


def export(name, out_dir, with_src=True):
    md_path = JM_MD_DIR / name
    if not md_path.is_file():
        md_path = MARKDOWN_DIR / name
    if not md_path.is_file():
        raise SystemExit("[FAIL] MD 不存在: %s" % name)

    stem = md_path.stem
    dest = out_dir / stem
    dest.mkdir(parents=True, exist_ok=True)

    md_text = md_path.read_text(encoding="utf-8")
    (dest / "md.md").write_text(md_text, encoding="utf-8")

    meta = {
        "name": name,
        "stem": stem,
        "rule_version": md_layout.RULE_VERSION,
        "body_chars": len(md_layout.body_chars(md_text)),
        "paras": sum(1 for l in md_text.split("\n")
                     if l.strip() and not l.startswith(("#", ">", "---"))),
    }

    src_path = find_source_pdf(stem)
    if src_path and src_path.is_file():
        meta["source_pdf"] = str(src_path)
        if with_src:
            try:
                lines, breaks = pdf_physical_lines(src_path)
                if not lines:
                    # 纯图片 PDF（无文本层）：MD 来自历史 OCR 批处理，源 PDF 抽不出物理行。
                    # 此时改用「MD 自身反推」：把 MD 的每段当作一个不可分割单元，
                    # agent 只能靠语义判断，无法对照源行。明确告知 agent 这一限制。
                    meta["src_unavailable"] = "纯图片 PDF，无文本层；无法导出源物理行"
                    (dest / "src.txt").write_text(
                        "[无可用源物理行] 该 PDF 无文本层（纯图片），"
                        "MD 内容来自历史 OCR 批处理。\n"
                        "判断依据只能是 MD 自身的段落语义与上下文。\n",
                        encoding="utf-8")
                else:
                    # 标注每个物理行是否触发断段（行尾有终止标点）+ 是否是页末。
                    # 这两个标记让 agent 能直接看出「排版规则会在这里断开」。
                    marked = []
                    for line, is_page_end in zip(lines, breaks):
                        tag = "[断]" if line[-1] in md_layout.TERMINATORS else "[续]"
                        if is_page_end:
                            tag += "[页末]"
                        marked.append("%s %s" % (tag, line))
                    (dest / "src.txt").write_text("\n".join(marked) + "\n",
                                                 encoding="utf-8")
                    meta["src_lines"] = len(lines)
                    meta["src_breaks"] = sum(1 for l in lines
                                             if l[-1] in md_layout.TERMINATORS)
            except Exception as e:
                meta["src_error"] = str(e)
    else:
        meta["source_pdf"] = None
        meta["src_error"] = "未找到同 stem 的 PDF"

    # 段落索引表：把 MD 的第 N 段映射到 src.txt 的行号区间。
    # agent 只需查表就知道「MD 第 N 段 = 源文件第 a~b 行」。
    para_map = []
    if src_path and src_path.is_file() and with_src and "src_lines" in meta:
        try:
            para_map = build_para_map(md_text, src_path)
            (dest / "para_map.json").write_text(
                json.dumps(para_map, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            meta["para_map_error"] = str(e)
    meta["paras_indexed"] = len(para_map)

    (dest / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest, meta


def main():
    ap = argparse.ArgumentParser(description="导出排版语义复查比对材料")
    ap.add_argument("--name", action="append", default=[],
                    help="MD 文件名（可重复）")
    ap.add_argument("--names", default="", help="逗号分隔的 MD 文件名")
    ap.add_argument("--out-dir", default="/tmp/chaguan_review", help="导出目录")
    ap.add_argument("--no-src", action="store_true", help="不导出源 PDF 物理行")
    args = ap.parse_args()

    names = list(args.name)
    names += [n.strip() for n in args.names.split(",") if n.strip()]
    if not names:
        print("[FAIL] 请用 --name 或 --names 指定 MD 文件")
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for n in names:
        try:
            dest, meta = export(n, out_dir, with_src=not args.no_src)
        except SystemExit as e:
            print(str(e))
            return 2
        print("[OK] %s -> %s" % (n, dest))
        print("     正文字符=%d 段落=%d 源PDF=%s"
              % (meta["body_chars"], meta["paras"],
                 meta.get("source_pdf") or meta.get("src_error", "-")))

    return 0


if __name__ == "__main__":
    sys.exit(main())
