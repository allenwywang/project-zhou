#!/usr/bin/env python3
"""Stage and publish only reviewed new zlsdcg articles; never overwrite the KB."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zlsdcg_process import safe_title, yaml_string

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
KB = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
STAGING = WORK / "staging"
ACCOUNT = "周先生的茶馆四代目"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.stage == args.publish:
        parser.error("choose exactly one of --stage or --publish")
    review_path = WORK / "review_decisions.json"
    if not review_path.exists():
        print("复核决定尚未生成，不能发布")
        return 2
    decisions = json.loads(review_path.read_text(encoding="utf-8"))
    approved = {int(key) for key, value in decisions.items() if value["decision"] == "new"}
    prepared = {item["id"]: item for item in read_jsonl(WORK / "prepared.jsonl")}
    comparison = {item["id"]: item for item in read_jsonl(WORK / "comparison_results.jsonl")}
    if not approved:
        print("没有批准入库的新文章")
        return 0
    used_stems = {path.stem for path in KB.glob("*.md")}
    manifest = []
    if args.publish:
        manifest = json.loads((WORK / "publish_manifest.json").read_text(encoding="utf-8"))
        if {item["id"] for item in manifest} != approved:
            raise RuntimeError("existing staging manifest differs from approved decisions")
    for post_id in sorted(approved):
        if args.publish:
            continue
        post = prepared[post_id]
        if post_id not in comparison or not post["markdown"].strip():
            raise RuntimeError(f"cannot publish missing/empty article {post_id}")
        base = f"{post['date'][:10].replace('-', '')}_{safe_title(post['title'])}"
        stem = base
        if stem in used_stems or any(item["stem"] == stem for item in manifest):
            stem = f"{base}_wp{post_id}"
        frontmatter = "\n".join([
            "---", f"title: {yaml_string(post['title'])}",
            f"author: {yaml_string('周老师')}",
            f"date: {yaml_string(post['date'][:16].replace('T', ' '))}",
            f"source: {yaml_string(post['link'])}",
            f"account: {yaml_string(ACCOUNT)}",
            f"wordpress_id: \"{post_id}\"",
            "---"])
        text = frontmatter + "\n\n# " + post["title"] + "\n\n"
        if post["markdown"].strip():
            text += post["markdown"].strip()
        elif post["image_urls"]:
            text += "[本文正文为图片，以下保留原始图片内容。]\n\n" + "\n\n".join(
                "![](" + url + ")" for url in post["image_urls"])
        else:
            raise RuntimeError(f"article has neither text nor images: {post_id}")
        text += "\n"
        target = STAGING / (stem + ".md")
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"staging conflict: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        manifest.append({"id": post_id, "title": post["title"], "date": post["date"],
                         "link": post["link"], "stem": stem, "year": post["date"][:4],
                         "staging_md": str(target), "text_sha256": comparison[post_id]["plain_sha256"]})
    temporary = WORK / "publish_manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(WORK / "publish_manifest.json")
    print(f"staged {len(manifest)} articles")
    if args.publish:
        asset_path = WORK / "asset_results.json"
        if not asset_path.exists():
            print("图片尚未下载并验收，禁止发布")
            return 2
        assets = json.loads(asset_path.read_text(encoding="utf-8"))
        if assets.get("failures"):
            print("存在未下载图片，禁止发布；缺失将记录在报告中")
            return 2
        check = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "zlsdcg_verify.py"), "--pre-publish"],
            cwd=str(ROOT), check=False)
        if check.returncode:
            print("暂存验收未通过，禁止发布；详见 prepublish_verification.json")
            return 2
        published = []
        for item in manifest:
            source = Path(item["staging_md"])
            destination = KB / (item["stem"] + ".md")
            if destination.exists():
                if destination.read_bytes() != source.read_bytes():
                    raise RuntimeError(f"target conflict, no overwrite: {destination}")
                item["publish_status"] = "existing_identical"
            else:
                # exclusive creation prevents accidental replacement on rerun
                with destination.open("x", encoding="utf-8") as handle:
                    handle.write(source.read_text(encoding="utf-8"))
                item["publish_status"] = "created"
            item["knowledge_path"] = str(destination)
            published.append(item)
        for file in (STAGING / "_attachments").glob("*"):
            if file.is_file():
                (KB / "_attachments").mkdir(exist_ok=True)
                target = KB / "_attachments" / file.name
                if target.exists() and target.read_bytes() != file.read_bytes():
                    raise RuntimeError(f"attachment hash collision: {target}")
                if not target.exists():
                    shutil.copy2(file, target)
        (WORK / "publish_md_results.json").write_text(
            json.dumps(published, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"published {sum(item['publish_status']=='created' for item in published)} articles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
