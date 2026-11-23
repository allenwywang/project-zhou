#!/usr/bin/env python3
"""Export compact, evidence-bearing review batches for independent agents."""
import json
import re
from difflib import unified_diff
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def snippets(web, local):
    a = [re.sub(r"\s+", "", line) for line in web["markdown"].splitlines() if line.strip()]
    b = [re.sub(r"\s+", "", line) for line in local["body"].splitlines() if line.strip()]
    diff = list(unified_diff(b, a, fromfile="知识库", tofile="网站", n=1))
    return "\n".join(diff[:120])


def main():
    results = read_jsonl(WORK / "comparison_results.jsonl")
    posts = {item["id"]: item for item in read_jsonl(WORK / "prepared.jsonl")}
    index = json.loads((WORK / "kb_index.json").read_text(encoding="utf-8"))
    kb = {item["path"]: item for item in index["markdown"]}
    review = [row for row in results if row["status"].startswith("review_")
              or row["nearest"] and row["nearest"]["body_similarity"] >= 0.90
              or row["site_exact_body_ids"]]
    # Near matches are grouped by evidence; title-only conflicts do not need
    # expensive semantic calls unless their content has substantive overlap.
    near = [row for row in review if row["status"] == "review_near_duplicate"]
    other = [row for row in review if row["status"] != "review_near_duplicate"]
    ordered = near + other
    output = WORK / "review_batches"
    output.mkdir(exist_ok=True)
    manifest = []
    for number in range(0, len(ordered), 30):
        batch = ordered[number:number + 30]
        payload = []
        for row in batch:
            item = {"id": row["id"], "title": row["title"], "date": row["date"],
                    "link": row["link"], "status": row["status"],
                    "site_same_title_ids": row["site_same_title_ids"],
                    "site_exact_body_ids": row["site_exact_body_ids"],
                    "web_markdown": posts[row["id"]]["markdown"],
                    "web_length": len(posts[row["id"]]["text_key"]),
                    "kb_title_matches": row["kb_title_matches"], "nearest": row["nearest"]}
            paths = [match["path"] for match in row["kb_title_matches"]]
            if row["nearest"]:
                paths.append(row["nearest"]["path"])
            item["local_matches"] = [{"path": path, "filename": Path(path).name,
                                      "body": kb[path]["body"], "diff": snippets(posts[row["id"]], kb[path])}
                                     for path in dict.fromkeys(paths) if path in kb]
            payload.append(item)
        path = output / f"batch-{number // 30 + 1:03d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"path": str(path), "count": len(payload),
                         "ids": [row["id"] for row in batch]})
    (WORK / "review_manifest.json").write_text(
        json.dumps({"total": len(ordered), "batches": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({"total": len(ordered), "batches": len(manifest),
                      "near": len(near), "other": len(other)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
