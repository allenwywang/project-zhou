#!/usr/bin/env python3
"""Build token-efficient semantic review batches from comparison evidence."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def diff_summary(web, local):
    a = re.sub(r"\s+", "", web)
    b = re.sub(r"\s+", "", local)
    matcher = SequenceMatcher(None, b, a, autojunk=False)
    chunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        chunks.append({"change": tag, "kb_context": b[max(0, i1-80):min(len(b), i2+80)],
                       "web_context": a[max(0, j1-80):min(len(a), j2+80)]})
    return chunks[:24]


def main():
    rows = load(WORK / "comparison_results.jsonl")
    posts = {item["id"]: item for item in load(WORK / "prepared.jsonl")}
    index = json.loads((WORK / "kb_index.json").read_text(encoding="utf-8"))
    kb = {item["path"]: item for item in index["markdown"]}
    review = [row for row in rows if row["status"] != "duplicate_exact"
              and (row["status"] != "candidate_new"
                   or row["nearest"] and row["nearest"]["body_similarity"] >= .90
                   or row["site_exact_body_ids"])]
    batches = []
    for start in range(0, len(review), 25):
        payload = []
        for row in review[start:start+25]:
            post = posts[row["id"]]
            entry = {"id": row["id"], "title": row["title"], "date": row["date"],
                     "status": row["status"], "site_exact_body_ids": row["site_exact_body_ids"],
                     "site_same_title_ids": row["site_same_title_ids"],
                     "web_text_length": len(post["text_key"]), "web_images": len(post["image_urls"]),
                     "web_preview": post["markdown"][:1200] if not row["kb_title_matches"] and not row["nearest"] else "",
                     "web_tail": post["markdown"][-500:] if not row["kb_title_matches"] and not row["nearest"] else "",
                     "matches": []}
            paths = [match["path"] for match in row["kb_title_matches"]]
            if row["nearest"]:
                paths.append(row["nearest"]["path"])
            for path in dict.fromkeys(paths):
                local = kb.get(path)
                if not local:
                    continue
                entry["matches"].append({
                    "path": path, "normalized_text_equal": row["plain_sha256"] == local["plain_sha256"],
                    "similarity": row["nearest"]["body_similarity"] if row["nearest"] and row["nearest"]["path"] == path else None,
                    "differences": diff_summary(post["markdown"], local["body"])})
            payload.append(entry)
        batches.append(payload)
    output = WORK / "semantic_batches"
    output.mkdir(exist_ok=True)
    for old in output.glob("*.json"):
        old.unlink()
    for i, payload in enumerate(batches, 1):
        (output / f"batch-{i:03d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        template = (WORK / "workers" / "review-template.md").read_text(encoding="utf-8")
        task = template + (f"\n本次输入：data/zlsdcg_archive/semantic_batches/batch-{i:03d}.json\n"
                           f"唯一允许写入结果：data/zlsdcg_archive/review_decisions/semantic-{i:03d}.json\n"
                           f"共 {len(payload)} 项。每项都有结果。差异字段只列差异上下文，"
                           "相同长正文不在输入重复展开；normalized_text_equal 表示比较口径正文完全一致。"
                           "differences 含新增/删除的上下文，按是否实质内容差异判断。\n")
        (WORK / "workers" / f"semantic-{i:03d}-task.md").write_text(task, encoding="utf-8")
    print(json.dumps({"review_total": len(review), "batches": len(batches)}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
