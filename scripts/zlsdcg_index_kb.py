#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 zlsdcg.com 全站文章比对去重构建现有内容索引（只读知识库/资料库）。

输出（全部写在项目 data/zlsdcg_archive/，绝不写回知识库）：
    data/zlsdcg_archive/kb_index.json          逐条索引（含原文正文，供离线比对）
    data/zlsdcg_archive/kb_index_summary.json  汇总统计与同名不同正文报告

索引范围：
    知识库 茶馆杂谈/JM系列/*.md、茶馆杂谈/公众号直采/*.md
    资料库 周老师的茶馆四代目/<年>/*.pdf（只取文件名、路径、日期，不读正文）

设计约定：
- 标题规范化只做“变形归一”，不删除标题中的实质数字/字母；
- 正文保留 frontmatter 之后的真实段落与链接文本，去掉 frontmatter 与首个 H1；
- 去重指纹计算前额外移除 markdown 语法、图片与 URL；
- 8-gram shingle 用 sha256 摘要；为控制索引体积，只保留摘要前
  ``SHINGLE_HEX_LEN`` 位（默认 16 位 hex，64 bit），足以做近似比对。
标准库实现，无第三方依赖。
"""

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "zlsdcg_archive"
INDEX_PATH = OUT_DIR / "kb_index.json"
SUMMARY_PATH = OUT_DIR / "kb_index_summary.json"
SCRIPT_PATH = Path(__file__).resolve()

KB_ROOT = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈")
MD_COLLECTIONS = [
    ("JM系列", KB_ROOT / "JM系列"),
    ("公众号直采", KB_ROOT / "公众号直采"),
]
PDF_ROOT = PROJECT_ROOT / "周老师茶馆历史文档" / "周先生的茶馆四代目"

SHINGLE_N = 8
SHINGLE_HEX_LEN = 16  # sha256 digest 截断长度（hex 字符）

# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_YAML_LINE_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.I)
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<https?://[^>]+>", re.I)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FENCE_RE = re.compile(r"^\s*(```|~~~).*?$", re.M)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_EMPHASIS_RE = re.compile(r"[*_~]{1,3}")
_MD_PREFIX_RE = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-+*]\s+|\d{1,3}[.)]\s+)", re.M)
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.M)

# 中文/全角标点 → ASCII 对应（NFKC 已处理大部分全角 ASCII 变体，这里补排版变体）
_PUNCT_MAP = {
    "。": ".", "、": ",", "，": ",", "；": ";", "：": ":", "！": "!", "？": "?",
    "（": "(", "）": ")", "【": "[", "】": "]", "《": "<", "》": ">",
    "「": '"', "」": '"', "『": '"', "』": '"', "“": '"', "”": '"', "‘": "'", "’": "'",
    "—": "-", "–": "-", "―": "-", "…": "...", "～": "~", "・": ".", "·": ".",
}
_PUNCT_TABLE = str.maketrans(_PUNCT_MAP)
_WS_RE = re.compile(r"\s+")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def split_frontmatter(text: str):
    """返回 (frontmatter dict, 正文)。仅解析简单 key: value 行。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        mm = _YAML_LINE_RE.match(line.strip())
        if not mm:
            continue
        key, val = mm.group(1), mm.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        meta[key] = val
    return meta, text[m.end():]


def strip_leading_h1(body: str) -> str:
    """去掉正文开头的首个 H1（文件名已承载标题，属重复标题）。"""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and re.match(r"^#\s+\S", lines[i]):
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return "\n".join(lines[i:])
    return body


def to_plain_text(md: str) -> str:
    """去 markdown 语法/图片/URL，保留真实段落与链接文本。"""
    s = _HTML_COMMENT_RE.sub("", md)
    s = _FENCE_RE.sub("", s)
    s = _IMG_RE.sub("", s)
    s = _LINK_RE.sub(r"\1", s)
    s = _AUTOLINK_RE.sub("", s)
    s = _URL_RE.sub("", s)
    s = _HTML_TAG_RE.sub("", s)
    s = _INLINE_CODE_RE.sub(r"\1", s)
    s = _TABLE_SEP_RE.sub("", s)
    s = _MD_PREFIX_RE.sub("", s)
    s = _EMPHASIS_RE.sub("", s)
    return s


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def norm_plain(s: str) -> str:
    """纯文本比较：去空白、大小写和 Markdown 行首标记。

    保留汉字、字母、数字和标点，避免把真正的修订抹成相同文章。
    """
    return _WS_RE.sub("", nfkc(s)).casefold()


def normalize_title(raw: str) -> str:
    """标题规范化：NFKC → 标点变体归一 → 去空白 → 去日期/JM 前缀 → 小写。

    只归一变体，不删除标题中的实质数字或字母。
    """
    s = nfkc(raw).translate(_PUNCT_TABLE)
    s = _WS_RE.sub("", s)
    # 先去掉带分隔符的完整日期，再处理 JM 前缀。不能先删 YY.MM，
    # 否则会把“月-JM…”中的真实文章编号残留在标题里。
    s = re.sub(r"^\d{4}[-.]?\d{2}[-.]?\d{2}[_-]?", "", s)
    s = re.sub(r"^\d{2}\.\d{1,2}月-", "", s)
    s = re.sub(r"^JM(?:早期文章|\d+)[-_]?", "", s, flags=re.I)
    return s.strip("-_ ").lower()


def shingles(text: str):
    """已规范化的纯文本 → 8-gram sha256 摘要集合（去重、稳定排序）。"""
    if len(text) <= SHINGLE_N:  # 含空正文：不足 8 字时整体作为单个 shingle
        return [sha256_text(text)[:SHINGLE_HEX_LEN]]
    return sorted({sha256_text(text[i:i + SHINGLE_N])[:SHINGLE_HEX_LEN]
                   for i in range(len(text) - SHINGLE_N + 1)})


def rel_or_str(p: Path) -> str:
    return str(p)


# ---------------------------------------------------------------------------
# 索引构建
# ---------------------------------------------------------------------------

def index_markdown(collection: str, directory: Path):
    records = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = split_frontmatter(text)
        body = strip_leading_h1(body)
        plain = to_plain_text(body)
        plain_norm = norm_plain(plain)
        stem = path.stem
        records.append({
            "kind": "md",
            "collection": collection,
            "path": rel_or_str(path),
            "filename": path.name,
            "frontmatter": {
                k: meta.get(k) for k in ("title", "date", "source") if k in meta
            },
            "derived_title": stem,
            "normalized_title": normalize_title(stem),
            "body": body,
            "body_sha256": sha256_text(body),
            "plain_sha256": sha256_text(plain_norm),
            "char_count": len(body),
            "plain_char_count": len(plain_norm),
            "shingle_count": 0,
            "shingles": [],
        })
        rec = records[-1]
        rec["shingles"] = shingles(plain_norm)
        rec["shingle_count"] = len(rec["shingles"])
    return records


def index_pdfs():
    records = []
    if not PDF_ROOT.is_dir():
        return records, []
    missing = []
    for year_dir in sorted(p for p in PDF_ROOT.iterdir() if p.is_dir()):
        year = int(year_dir.name) if year_dir.name.isdigit() else None
        for path in sorted(year_dir.glob("*.pdf")):
            stem = path.stem
            m = re.match(r"^(\d{4})(\d{2})(\d{2})_(.+)$", stem)
            if m:
                date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                title = m.group(4)
                y = int(m.group(1))
            else:
                date, title, y = None, stem, year
                missing.append(str(path))
            records.append({
                "kind": "pdf",
                "collection": year_dir.name,
                "path": rel_or_str(path),
                "filename": path.name,
                "date": date,
                "year": y,
                "derived_title": stem,
                "normalized_title": normalize_title(stem),
            })
    return records, missing


def find_same_name_diff_body(md_records):
    """同一规范化标题下出现不同正文 → 同名不同正文。"""
    groups = {}
    for r in md_records:
        groups.setdefault(r["normalized_title"], []).append(r)
    conflicts, same = [], 0
    for title, items in groups.items():
        if len(items) < 2:
            continue
        bodies = {r["body_sha256"] for r in items}
        plains = {r["plain_sha256"] for r in items}
        if len(bodies) > 1 or len(plains) > 1:
            conflicts.append({
                "normalized_title": title,
                "count": len(items),
                "distinct_body_sha256": len(bodies),
                "distinct_plain_sha256": len(plains),
                "files": [
                    {
                        "path": r["path"],
                        "filename": r["filename"],
                        "collection": r["collection"],
                        "body_sha256": r["body_sha256"],
                        "plain_sha256": r["plain_sha256"],
                    }
                    for r in items
                ],
            })
        else:
            same += 1
    conflicts.sort(key=lambda x: (-x["count"], x["normalized_title"]))
    return conflicts, same


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    md_records, per_collection = [], {}
    for name, directory in MD_COLLECTIONS:
        files = sorted(directory.glob("*.md")) if directory.is_dir() else []
        recs = index_markdown(name, directory)
        per_collection[name] = {
            "directory": str(directory),
            "files": len(files),
            "indexed": len(recs),
        }
        md_records.extend(recs)

    pdf_records, pdf_bad = index_pdfs()

    no_body = [r for r in md_records if not r["body"].strip()
               or r["plain_char_count"] == 0]
    conflicts, same_title_same_body = find_same_name_diff_body(md_records)

    index = {
        "generated_by": str(SCRIPT_PATH),
        "kb_root": str(KB_ROOT),
        "pdf_root": str(PDF_ROOT),
        "shingle": {"n": SHINGLE_N, "hash": "sha256", "hex_len": SHINGLE_HEX_LEN},
        "counts": {
            "md_total": len(md_records),
            "pdf_total": len(pdf_records),
            "md_no_body": len(no_body),
        },
        "markdown": md_records,
        "pdf": pdf_records,
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                          encoding="utf-8")

    summary = {
        "script": str(SCRIPT_PATH),
        "index_json": str(INDEX_PATH),
        "summary_json": str(SUMMARY_PATH),
        "collection_counts": per_collection,
        "md_total_indexed": len(md_records),
        "pdf_total_indexed": len(pdf_records),
        "md_without_body": {
            "count": len(no_body),
            "files": [{"collection": r["collection"], "filename": r["filename"],
                       "char_count": r["char_count"],
                       "plain_char_count": r["plain_char_count"]}
                      for r in no_body],
        },
        "pdf_without_yyyymmdd_name": {
            "count": len(pdf_bad),
            "files": pdf_bad,
        },
        "duplicate_titles": {
            "same_name_same_body_groups": same_title_same_body,
            "same_name_different_body_groups": len(conflicts),
            "has_same_name_different_body": bool(conflicts),
            "details": conflicts,
        },
        "notes": [
            "正文=去 frontmatter、去首个 H1 后的原文，保留段落与链接文本。",
            "plain_sha256 计算前已移除 markdown 语法、图片与 URL，并做 NFKC + 去空白。",
            f"shingles 为 8-gram 的 sha256 前 {SHINGLE_HEX_LEN} 位 hex（控制索引体积）。",
            "PDF 未读正文，仅取文件名/路径/日期。",
        ],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    print(f"[OK] index: {INDEX_PATH}")
    print(f"[OK] summary: {SUMMARY_PATH}")
    for name, c in per_collection.items():
        print(f"  {name}: files={c['files']} indexed={c['indexed']}")
    print(f"  PDF: indexed={len(pdf_records)} bad_name={len(pdf_bad)}")
    print(f"  md_without_body={len(no_body)}")
    print(f"  same_name_different_body_groups={len(conflicts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
