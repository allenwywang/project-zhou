#!/usr/bin/env python3
"""Merge independent review decisions and stage only evidence-backed new posts."""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
KB = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
EXCLUDE_FILE = ROOT / "scripts" / "zlsdcg_exclude.json"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def excluded_rules():
    """排除清单：title 命中关键词的文章不纳入知识库（如独立系列，暂不收录）。"""
    if not EXCLUDE_FILE.is_file():
        return []
    try:
        data = json.loads(EXCLUDE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [rule for rule in data.get("rules", []) if rule.get("keyword")]


def published_articles():
    """知识库中已归档文章的标识索引：wordpress_id 与来源链接 -> 文件路径。"""
    mapping = {}
    for path in KB.glob("*.md"):
        try:
            head = path.read_text(encoding="utf-8")[:600]
        except OSError:
            continue
        identifier = re.search(r'^wordpress_id:\s*"?(\d+)"?\s*$', head, re.M)
        if identifier:
            mapping.setdefault(identifier.group(1), str(path))
        source = re.search(r'^source:\s*"([^"]+)"\s*$', head, re.M)
        if source:
            mapping.setdefault(source.group(1), str(path))
    return mapping


def main():
    results = read_jsonl(WORK / "comparison_results.jsonl")
    decisions = {}
    incomplete = []
    expected = {}
    for batch in sorted((WORK / "semantic_batches").glob("batch-*.json")):
        number = batch.stem.split("-")[-1]
        expected[WORK / "review_decisions" / f"semantic-{number}.json"] = {
            row["id"] for row in json.loads(batch.read_text(encoding="utf-8"))}
    for path in sorted(expected):
        if not path.is_file():
            incomplete.append(f"missing decision file: {path.name}")
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            incomplete.append(f"{path}: {exc}")
            continue
        ids = [row.get("id") for row in rows if isinstance(row, dict)]
        if len(ids) != len(set(ids)) or set(ids) != expected[path]:
            incomplete.append(f"{path}: output IDs do not exactly match its batch")
            continue
        for row in rows:
            if row.get("decision") not in ("new", "duplicate", "uncertain"):
                incomplete.append(f"{path}: invalid decision {row.get('id')}")
                continue
            if row.get("decision") == "duplicate" and not row.get("evidence_path"):
                incomplete.append(f"{path}: duplicate lacks evidence {row.get('id')}")
                continue
            decisions[int(row["id"])] = row
    # comparison_results uses the authoritative text normalization. These hashes
    # supersede the older preview field cached in kb_index.json.
    exact_kb = {row["id"]: row["kb_exact_body"][0] for row in results
                if row["status"] == "duplicate_exact" and row["kb_exact_body"]}
    for post_id, path in exact_kb.items():
        decisions[post_id] = {"id": post_id, "decision": "duplicate",
                              "confidence": 1.0, "evidence_path": path,
                              "reason": "统一正文规范化后SHA-256完全一致，机械判重"}
    # 排除清单优先：命中关键词的文章一律不入库（否则用户手工删掉的文章会被重新发布）。
    excluded = 0
    for row in results:
        for rule in excluded_rules():
            if rule["keyword"] in (row.get("title") or ""):
                decisions[row["id"]] = {"id": row["id"], "decision": "duplicate",
                                        "confidence": 1.0,
                                        "evidence_path": "excluded:" + rule["keyword"],
                                        "reason": "按排除清单不纳入知识库：" + rule.get("reason", "")}
                excluded += 1
                break
    # 增量重跑：文章已在知识库（同一 wordpress_id 或同一来源链接）即视为已归档，
    # 不再重复发布。机械判重兜不住两种情况——纯图片/空正文文章无从比对，
    # 以及知识库副本被脱敏改写（姓名占位）导致正文哈希不再相等。
    published = published_articles()
    archived = 0
    for row in results:
        if row["id"] in decisions and decisions[row["id"]]["decision"] == "duplicate":
            continue
        evidence = published.get(str(row["id"])) or published.get(row["link"])
        if not evidence:
            continue
        decisions[row["id"]] = {"id": row["id"], "decision": "duplicate",
                                "confidence": 1.0, "evidence_path": evidence,
                                "reason": "同一 wordpress_id/来源链接已在知识库归档（增量重跑不重复发布）"}
        archived += 1
    review_ids = {row["id"] for row in results if row["status"] != "candidate_new"
                  or row["nearest"] and row["nearest"]["body_similarity"] >= 0.90
                  or row["site_exact_body_ids"]}
    for post_id in review_ids:
        row = decisions.get(post_id)
        if row is None:
            incomplete.append(f"missing reviewed decision: {post_id}")
    # Default for unreviewed candidates is new: no KB near match or exact match.
    for row in results:
        # 已有判定的（机械判重、已归档）不被默认值覆盖。
        if row["id"] not in review_ids and row["id"] not in decisions:
            decisions[row["id"]] = {"id": row["id"], "decision": "new",
                                     "confidence": 1.0, "evidence_path": "",
                                     "reason": "标题、正文均无知识库命中，且站内无重复ID"}
    # A site-exact group retains the oldest ID; all other IDs are copies.
    groups = {}
    for row in results:
        if row["site_exact_body_ids"]:
            ids = tuple(sorted([row["id"]] + row["site_exact_body_ids"]))
            groups[ids] = row["date"]
    for ids in sorted(groups):
        keeper = ids[0]
        for post_id in ids[1:]:
            decisions[post_id] = {"id": post_id, "decision": "duplicate",
                                   "confidence": 1.0, "evidence_path": f"site:{keeper}",
                                   "reason": "站内正文完全重复，保留最早文章ID"}
    # Preserve variants containing meaningful added/deleted content. An empty
    # text fingerprint is not evidence of a media-only article being a copy.
    index = {item["path"]: item for item in
             json.loads((WORK / "kb_index.json").read_text())["markdown"]}
    for row in results:
        if not row["kb_exact_body"]:
            continue
        valid_paths = []
        for path in row["kb_exact_body"]:
            if index[path]["body"].strip():
                valid_paths.append(path)
        if row["status"] == "duplicate_exact" and valid_paths:
            decisions[row["id"]].update({"evidence_path": valid_paths[0],
                                         "reason": "统一正文规范化后SHA-256完全一致，机械判重"})
        elif row["status"] == "review_empty_body" and not valid_paths:
            # 已归档判定（同一 wordpress_id/来源链接）优先，不把它翻回“新增”。
            if decisions[row["id"]]["decision"] != "duplicate":
                decisions[row["id"]] = {"id": row["id"], "decision": "new",
                                        "confidence": 1.0, "evidence_path": "",
                                        "reason": "纯图片正文，旧空文本稿不构成重复证据"}
    if incomplete:
        (WORK / "review_incomplete.json").write_text(
            json.dumps(incomplete, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"复核尚未完整：{len(incomplete)} 项；禁止发布")
        return 2
    # Never auto-accept low-confidence or uncertain decisions as duplicates.
    uncertain = [row for row in decisions.values()
                 if row["decision"] == "uncertain"]
    if uncertain:
        print(f"仍有 {len(uncertain)} 篇无法确认，按新增候选保留并单列")
        for row in uncertain:
            row["decision"] = "new"
            row["reason"] = "复核无法确认已有正文，保守保留；" + row.get("reason", "")
    output = {str(key): decisions[key] for key in sorted(decisions)}
    (WORK / "review_decisions.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = collections.Counter(row["decision"] for row in decisions.values())
    (WORK / "review_summary.json").write_text(json.dumps(
        {"total": len(decisions), "counts": counts,
         "uncertain_kept_new": [row["id"] for row in uncertain]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({"total": len(decisions), "counts": counts,
                      "already_archived": archived, "excluded": excluded,
                      "uncertain_kept_new": len(uncertain)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
