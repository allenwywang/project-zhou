#!/usr/bin/env python3
"""Fetch all public zlsdcg.com posts from the WordPress REST API.

Stores immutable page responses and a merged JSONL index. No scripts from
fetched content are executed; downloaded data is treated as untrusted input.
"""
import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
PAGES = WORK / "raw_pages"
API = "https://zlsdcg.com/wp-json/wp/v2/posts"
FIELDS = "id,date,modified,link,slug,title,content"
UA = "Mozilla/5.0 (compatible; personal-archive/1.0)"


def get_json(url, attempts=5):
    error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response), response.headers
        except Exception as exc:
            error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed after {attempts} attempts: {url}: {error}")


def fetch_page(page, per_page):
    dest = PAGES / f"page-{page:04d}.json"
    if dest.exists():
        data = json.loads(dest.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and len(data) <= per_page:
            return page, len(data)
    url = f"{API}?per_page={per_page}&page={page}&_fields={FIELDS}"
    data, headers = get_json(url)
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"invalid or empty page {page}")
    ids = [post["id"] for post in data]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"duplicate ids on page {page}")
    temporary = dest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(dest)
    return page, len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--per-page", type=int, default=100)
    args = parser.parse_args()
    PAGES.mkdir(parents=True, exist_ok=True)
    _, headers = get_json(f"{API}?per_page=1&_fields=id")
    total = int(headers["X-WP-Total"])
    pages = (total + args.per_page - 1) // args.per_page
    print(f"API reports {total} posts, {pages} pages", flush=True)
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch_page, page, args.per_page): page
                for page in range(1, pages + 1)}
        for job in concurrent.futures.as_completed(jobs):
            page = jobs[job]
            try:
                _, count = job.result()
                print(f"[OK] page {page}/{pages}: {count}", flush=True)
            except Exception as exc:
                failures.append({"page": page, "error": str(exc)})
                print(f"[FAIL] page {page}: {exc}", flush=True)
    if failures:
        (WORK / "fetch_failures.json").write_text(
            json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    posts = []
    for page in range(1, pages + 1):
        posts.extend(json.loads((PAGES / f"page-{page:04d}.json").read_text(encoding="utf-8")))
    ids = [post["id"] for post in posts]
    if len(posts) != total or len(set(ids)) != total:
        raise RuntimeError(f"count mismatch: expected {total}, got {len(posts)}, unique {len(set(ids))}")
    posts.sort(key=lambda post: (post["date"], post["id"]))
    output = WORK / "posts.jsonl"
    temporary = output.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for post in posts:
            handle.write(json.dumps(post, ensure_ascii=False) + "\n")
    temporary.replace(output)
    report = {"source": API, "expected_total": total, "fetched_total": len(posts),
              "unique_ids": len(set(ids)), "pages": pages,
              "oldest": posts[0]["date"], "newest": posts[-1]["date"],
              "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (WORK / "fetch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
