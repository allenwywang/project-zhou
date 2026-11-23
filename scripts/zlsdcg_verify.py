#!/usr/bin/env python3
"""Audit the complete zlsdcg import, with per-article MD/PDF correspondence."""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
KB = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
ARCHIVE = ROOT / "周老师茶馆历史文档" / "周先生的茶馆四代目"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre-publish", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((WORK / "publish_manifest.json").read_text(encoding="utf-8"))
    decisions = json.loads((WORK / "review_decisions.json").read_text(encoding="utf-8"))
    raw = [json.loads(line) for line in (WORK / "posts.jsonl").read_text(encoding="utf-8").splitlines() if line]
    issues = []
    fetch_report = json.loads((WORK / "fetch_report.json").read_text(encoding="utf-8"))
    if len({item["id"] for item in raw}) != fetch_report["fetched_total"]:
        issues.append("source ID count changed")
    if {int(key) for key in decisions} != {item["id"] for item in raw}:
        issues.append("review decision coverage is not all source posts")
    if len({item["id"] for item in manifest}) != len(manifest):
        issues.append("manifest duplicate IDs")
    if len({item["stem"] for item in manifest}) != len(manifest):
        issues.append("manifest duplicate stems")
    approved = {int(key) for key, value in decisions.items() if value["decision"] == "new"}
    if approved != {item["id"] for item in manifest}:
        issues.append("manifest IDs differ from approved new IDs")
    for item in manifest:
        md = Path(item["staging_md"])
        if not md.is_file() or md.stat().st_size < 150:
            issues.append(f"{item['id']}: staging MD absent/empty")
            continue
        text = md.read_text(encoding="utf-8")
        if "404文章获取" in text or "个人网站：zlsdcg" in text:
            issues.append(f"{item['id']}: promotional tail remains")
        image_refs = re.findall(r"!\[[^]]*\]\(([^)]+)\)", text)
        unique_image_content = set()
        for image in set(image_refs):
            path = md.parent / image
            if path.is_file():
                unique_image_content.add(hashlib.sha256(path.read_bytes()).hexdigest())
        for image in image_refs:
            if image.startswith("http") or not (md.parent / image).is_file():
                issues.append(f"{item['id']}: nonlocal/missing image {image}")
        pdf = ARCHIVE / item["year"] / (item["stem"] + ".pdf")
        if not args.pre_publish:
            kb_md = KB / (item["stem"] + ".md")
            if not kb_md.is_file():
                issues.append(f"{item['id']}: knowledge MD missing")
            elif kb_md.read_bytes() != md.read_bytes():
                issues.append(f"{item['id']}: published MD differs from staging")
            if not pdf.is_file() or pdf.stat().st_size < 1000 or pdf.read_bytes()[:5] != b"%PDF-":
                issues.append(f"{item['id']}: PDF missing/invalid")
                continue
            try:
                import fitz
                with fitz.open(str(pdf)) as document:
                    pages = document.page_count
                    extracted = "\n".join(page.get_text() for page in document)
                    embedded_images = {image[0] for page in document for image in page.get_images(full=True)}
                if pages < 1:
                    issues.append(f"{item['id']}: PDF has no pages")
                compact_text = re.sub(r"[^\w一-鿿]", "", extracted).casefold()
                title_key = re.sub(r"[^\w一-鿿]", "", item["title"]).casefold()
                if title_key[:12] not in compact_text:
                    issues.append(f"{item['id']}: PDF title not extractable")
                body_text = text.split("\n---\n", 1)[-1]
                body_text = re.sub(r"!?\[[^]]*\]\([^)]*\)", "", body_text)
                plain_length = len(re.sub(r"[#>*_`\-]|\s+", "", body_text))
                if plain_length >= 100 and len(compact_text) < 80:
                    issues.append(f"{item['id']}: PDF body text unexpectedly short")
                if len(embedded_images) != len(unique_image_content):
                    issues.append(f"{item['id']}: PDF image count mismatch "
                                  f"({len(embedded_images)}/{len(unique_image_content)} unique content images)")
            except Exception as exc:
                issues.append(f"{item['id']}: PDF cannot be opened/extracted: {exc}")
    report = {"source_total": len(raw), "approved_new": len(approved),
              "manifest": len(manifest), "issues": issues,
              "status_counts": collections.Counter(value["decision"] for value in decisions.values()),
              "pre_publish": args.pre_publish}
    (WORK / ("prepublish_verification.json" if args.pre_publish else "verification.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
