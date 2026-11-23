#!/usr/bin/env python3
"""Content-based deduplication for zlsdcg posts against the existing KB.

Only high-confidence duplicate evidence skips an article. Different-content
same-title articles remain candidates and are explicitly reported.
"""
import collections
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from zlsdcg_index_kb import normalize_title, to_plain_text


def compare_plain(value):
    # Preserve JM's intentional #annotation lines; only a valid Markdown
    # heading marker (# followed by a space) is formatting, not body text.
    return re.sub(r"\s+", "", to_plain_text(value)).casefold()


ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
ACCOUNT = "周先生的茶馆四代目"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def similarity(left, right):
    # Corpus texts are short articles; full comparison is used for auditability.
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def main():
    posts = read_jsonl(WORK / "prepared.jsonl")
    index = json.loads((WORK / "kb_index.json").read_text(encoding="utf-8"))
    kb = index["markdown"]
    for item in posts:
        item["normalized_title"] = normalize_title(item["title"])
        item["plain"] = compare_plain(item["markdown"])
        item["plain_sha256"] = hashlib.sha256(item["plain"].encode()).hexdigest()
        item["shingle_set"] = set(digest(item["plain"][i:i + 8])
                                   for i in range(max(1, len(item["plain"]) - 7)))
    for item in kb:
        item["plain"] = compare_plain(item["body"])
        item["plain_sha256"] = hashlib.sha256(item["plain"].encode()).hexdigest()
        # Must hash exactly the same normalized text as the website side;
        # cached raw shingles include layout-only Markdown differences.
        item["shingle_set"] = set(digest(item["plain"][i:i + 8])
                                   for i in range(max(1, len(item["plain"]) - 7)))

    by_title = collections.defaultdict(list)
    by_body = collections.defaultdict(list)
    by_source = {}
    inverted = collections.defaultdict(list)
    for item in kb:
        by_title[item["normalized_title"]].append(item)
        by_body[item["plain_sha256"]].append(item)
        source = item["frontmatter"].get("source")
        if source:
            by_source[source] = item
        for shingle in item["shingle_set"]:
            inverted[shingle].append(item)

    results = []
    title_groups = collections.defaultdict(list)
    body_groups = collections.defaultdict(list)
    for post in posts:
        title_groups[post["normalized_title"]].append(post)
        body_groups[post["plain_sha256"]].append(post)
    for post in posts:
        same_title = title_groups[post["normalized_title"]]
        same_body = body_groups[post["plain_sha256"]]
        exact = by_body.get(post["plain_sha256"], [])
        candidates = set()
        for shingle in post["shingle_set"]:
            candidates.update(id(item) for item in inverted.get(shingle, []))
        # Cap only broad boilerplate collisions; every title/body hit is exact.
        best = []
        for item in kb:
            if id(item) not in candidates:
                continue
            union = post["shingle_set"] | item["shingle_set"]
            jaccard = len(post["shingle_set"] & item["shingle_set"]) / max(1, len(union))
            if jaccard < 0.18:
                continue
            containment = (len(post["shingle_set"] & item["shingle_set"]) /
                           max(1, min(len(post["shingle_set"]), len(item["shingle_set"]))))
            ratio = similarity(post["plain"], item["plain"]) if max(jaccard, containment) >= 0.60 else 0
            best.append((max(jaccard, containment), jaccard, containment, ratio, item))
        best.sort(key=lambda row: row[0], reverse=True)
        near = best[0] if best else None
        title_matches = by_title.get(post["normalized_title"], [])
        title_same_body = [item for item in title_matches if item["plain_sha256"] == post["plain_sha256"]]
        source_hit = by_source.get(post["link"]) or by_source.get(post["link"].replace("http://", "https://"))
        duplicate = bool(exact or title_same_body or source_hit)
        status = "duplicate_exact" if duplicate else "candidate_new"
        if not duplicate and near and near[0] >= 0.98 and near[3] >= 0.985:
            status = "review_near_duplicate"
        if title_matches and not title_same_body and status == "candidate_new":
            status = "review_same_title"
        if len(same_title) > 1 and status == "candidate_new":
            status = "review_site_same_title"
        if not post["plain"]:
            status = "review_empty_body"
        row = {key: post[key] for key in
               ("id", "title", "date", "modified", "link", "slug", "text_length",
                "text_sha256", "plain_sha256", "normalized_title", "trimmed", "image_urls")}
        row.update({"status": status,
                    "site_same_title_ids": [p["id"] for p in same_title if p["id"] != post["id"]],
                    "site_exact_body_ids": [p["id"] for p in same_body if p["id"] != post["id"]],
                    "kb_exact_body": [item["path"] for item in exact],
                    "kb_title_matches": [{"path": item["path"],
                                           "body_sha256": item["plain_sha256"],
                                           "body_similarity": similarity(post["plain"], item["plain"])}
                                          for item in title_matches],
                    "nearest": ({"path": near[4]["path"], "jaccard": near[1],
                                  "containment": near[2], "body_similarity": near[3]} if near else None)})
        results.append(row)
    write_jsonl(WORK / "comparison_results.jsonl", results)
    counts = collections.Counter(row["status"] for row in results)
    summary = {"site_posts": len(posts), "kb_articles": len(kb), "status_counts": counts,
               "unique_site_titles": len(title_groups), "unique_site_bodies": len(body_groups),
               "review_same_title": [row for row in results if row["status"] == "review_same_title"],
               "review_site_same_title": [row for row in results if row["status"] == "review_site_same_title"],
               "review_near_duplicate": [row for row in results if row["status"] == "review_near_duplicate"]}
    (WORK / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "review_same_title": len(summary["review_same_title"]),
                      "review_site_same_title": len(summary["review_site_same_title"]),
                      "review_near_duplicate": len(summary["review_near_duplicate"])},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
