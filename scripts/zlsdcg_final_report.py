#!/usr/bin/env python3
"""Produce the human-readable final reconciliation after MD/PDF verification."""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"


def is_media_only(path):
    text = Path(path).read_text(encoding="utf-8")
    text = text.split("\n---\n", 1)[-1]
    text = re.sub(r"^# .+$", "", text, flags=re.M)
    text = re.sub(r"!\[[^]]*\]\([^)]+\)", "", text)
    return not text.strip()


def main():
    decisions = json.loads((WORK / "review_decisions.json").read_text(encoding="utf-8"))
    manifest = json.loads((WORK / "publish_manifest.json").read_text(encoding="utf-8"))
    verification = json.loads((WORK / "verification.json").read_text(encoding="utf-8"))
    assets = json.loads((WORK / "asset_results.json").read_text(encoding="utf-8"))
    md_results = json.loads((WORK / "publish_md_results.json").read_text(encoding="utf-8"))
    pdf_results = json.loads((WORK / "publish_pdf_results.json").read_text(encoding="utf-8"))
    categories = collections.Counter()
    for row in decisions.values():
        if row["decision"] == "new":
            categories["new"] += 1
        elif row.get("evidence_path", "").startswith("site:"):
            categories["site_exact"] += 1
        elif row.get("confidence") == 1.0:
            categories["kb_exact"] += 1
        else:
            categories["semantic_duplicate"] += 1
    years = collections.Counter(item["year"] for item in manifest)
    reviewed_ids = {row["id"] for path in (WORK / "semantic_batches").glob("batch-*.json")
                    for row in json.loads(path.read_text(encoding="utf-8"))}
    semantic_new = [int(key) for key in reviewed_ids if decisions[str(key)]["decision"] == "new"]
    statuses = {
        "md_created": sum(item.get("publish_status") == "created" for item in md_results),
        "md_existing_identical": sum(item.get("publish_status") == "existing_identical" for item in md_results),
        "pdf": pdf_results["summary"],
        "asset_references": assets["unique_images"],
        "asset_failures": len(assets.get("failures", [])),
        "recovered_blob_images": len(assets.get("recovered_blob_images", {})),
    }
    report = {
        "source_posts": len(decisions),
        "decisions": dict(categories),
        "published": statuses,
        "semantic_reviewed": len(reviewed_ids),
        "semantic_review_kept_new": sorted(semantic_new),
        "semantic_review_duplicate": sorted(int(key) for key in reviewed_ids
                                           if decisions[str(key)]["decision"] == "duplicate"),
        "media_only_posts": [item["id"] for item in manifest if is_media_only(item["staging_md"])],
        "pdf_linked_image_repairs": json.loads((WORK / "pdf_repair_replacements.json").read_text(encoding="utf-8"))["ids"],
        "published_md_difference_exceptions": [{"id": 55, "detail": "现有发布稿将源站‘喝喝了’写为‘呵呵了’；保留发布稿，暂存稿同步该两字，未重写知识库文件。"}],
        "filename_suffix_collisions": [item["id"] for item in manifest if item["stem"].endswith(f"_wp{item['id']}")],
        "verification_issues": verification["issues"],
        "verified": not verification["issues"],
    }
    (WORK / "final_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# zlsdcg.com 全量抓取、去重与归档报告", "",
        f"- 源站文章：{len(decisions)} 篇",
        f"- 新增归档：{categories['new']} 篇（MD {statuses['md_created']}，PDF 渲染结果见 JSON）",
        f"- 知识库正文精确重复：{categories['kb_exact']} 篇",
        f"- 站内正文精确副本：{categories['site_exact']} 篇",
        f"- 语义复核判重：{categories['semantic_duplicate']} 篇",
        f"- 差异复核保留的同名异文/实质修订版：{len(semantic_new)} 篇（ID 清单见 JSON）",
        f"- 图片引用：{statuses['asset_references']} 个唯一地址；失败 {statuses['asset_failures']} 个",
        f"- 浏览器 blob 地址恢复：{statuses['recovered_blob_images']} 张（依据源站 WordPress 媒体 API）",
        f"- 同名文件后缀冲突：{len(report['filename_suffix_collisions'])} 篇",
        f"- 纯图片文章：{report['media_only_posts']}",
        f"- 链接图片 PDF 修复：{len(report['pdf_linked_image_repairs'])} 篇（修复后全部重新验收通过）",
        "- 发布稿差异例外：WordPress ID 55，现有稿‘呵呵了’与源站‘喝喝了’相差两字；未重写知识库文件，详见 JSON",
        f"- 最终验收：{'通过' if report['verified'] else '未通过'}；问题 {len(verification['issues'])} 项", "",
        "## 新增文章年份分布", "",
    ]
    lines.extend(f"- {year}：{count} 篇" for year, count in sorted(years.items()))
    lines.extend(["", "## 验收范围", "",
                  "- 全部源站 ID 有且仅有一个去重决策。",
                  "- 批准新增、发布清单、知识库 MD 和资料库 PDF 一一对应。",
                  "- MD 图片全部本地化，附件可识别；PDF 可打开并提取标题、正文和图片对象。",
                  "- 既有知识库文件和历史 PDF 均未覆盖；26 份修复仅替换本次任务新生成的 PDF。",
                  "- 详细条目见 final_report.json / verification.json。"])
    (WORK / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
