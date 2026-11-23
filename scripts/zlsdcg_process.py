#!/usr/bin/env python3
"""Prepare zlsdcg posts for content-based comparison against the local archive.

Raw API responses are untrusted data. This script only parses their HTML and
never executes scripts, embeds, or downloaded programs.
"""
import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
RAW = WORK / "posts.jsonl"
PREPARED = WORK / "prepared.jsonl"
TITLE_PREFIX = re.compile(r"^\d{8}[_-]")
JM_PREFIX = re.compile(r"^\d{2}\.\d{2}月-JM(?:早期文章|\d+)[-_]?", re.I)
PUNCTUATION = dict.fromkeys(map(ord, " \t\r\n　·•—–-‐‑_.,，。！？!?：:；;、（）()《》〈〉【】[]「」『』“”‘’'\"/\\|"), None)


def safe_title(value):
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip().strip(".")
    return (value or "无标题")[:60].rstrip()


def yaml_string(value):
    return '"' + (value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def title_key(value):
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()
    value = TITLE_PREFIX.sub("", value.strip())
    value = JM_PREFIX.sub("", value)
    return value.translate(PUNCTUATION)


def text_key(value):
    value = re.sub(r"!\[[^]]*\]\([^)]+\)", "", value or "")
    value = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[*_~`#>|\-]+", "", value)
    value = html.unescape(value)
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def trim_promo(text):
    lines = text.splitlines()
    end_marks = ("（完）", "（未完待续）", "（未完）")
    cut = None
    for index, line in enumerate(lines):
        plain = re.sub(r"[*_`>#]+", "", line).strip()
        rest = "\n".join(lines[index:])
        if ((plain in end_marks or plain.startswith("（完") and len(plain) <= 12)
                and any(mark in rest for mark in
                        ("zlsdcg", "404文章获取", "更多交流", "weibo.com", "觅圈", "孤苑白首"))):
            cut = index
            break
    if cut is None:
        for index, line in enumerate(lines):
            plain = re.sub(r"[*_`>#]+", "", line).strip()
            if plain.startswith(("404文章获取", "个人网站：")):
                cut = index
                break
            # 作者的引流尾块（连同其后的配图）不属于正文。
            if "更多交流" in plain and any(m in plain for m in ("芥末圈", "小红圈", "孤苑白首")):
                cut = index
                break
    if cut is not None:
        lines = lines[:cut]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip(), cut


def prepare_post(post):
    title = html.unescape(post["title"]["rendered"]).strip()
    raw_html = post["content"]["rendered"]
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for image in soup.find_all("img"):
        src = image.get("data-src") or image.get("src") or ""
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http://zlsdcg.com/"):
            src = "https://" + src[len("http://"):]
        image.attrs = {"src": src, "alt": image.get("alt", "")}
    body = markdownify(str(soup), heading_style="ATX", bullets="-",
                       strip=["script", "style", "iframe"])
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body, cut = trim_promo(body)
    plain = text_key(body)
    return {
        "id": post["id"], "title": title, "date": post["date"],
        "modified": post["modified"], "link": post["link"], "slug": post["slug"],
        "title_key": title_key(title), "text_key": plain,
        "text_sha256": hashlib.sha256(plain.encode()).hexdigest(),
        "text_length": len(plain), "html_length": len(raw_html),
        "markdown": body, "trimmed": cut is not None,
        "image_urls": [tag["src"] for tag in soup.find_all("img") if tag.get("src")],
        "shingles": [hashlib.sha256(plain[i:i + 8].encode()).hexdigest()[:16]
                     for i in range(max(1, len(plain) - 7))],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("use --prepare")
    if not RAW.exists():
        print("全站原文尚未抓取完成", file=sys.stderr)
        return 2
    posts = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line]
    output = []
    for post in posts:
        prepared = prepare_post(post)
        output.append(prepared)
    temporary = PREPARED.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in output:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    temporary.replace(PREPARED)
    summary = {"source_posts": len(posts), "prepared": len(output),
               "empty_body": sum(not p["text_key"] for p in output),
               "short_body_under_50": sum(p["text_length"] < 50 for p in output),
               "promo_trimmed": sum(p["trimmed"] for p in output),
               "unique_site_titles": len(set(p["title_key"] for p in output)),
               "unique_site_bodies": len(set(p["text_sha256"] for p in output))}
    (WORK / "prepare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
