#!/usr/bin/env python3
"""Download one disjoint URL shard; shared image pool is keyed by canonical URL."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zlsdcg_download_assets import download

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    urls = json.loads(Path(args.input).read_text(encoding="utf-8"))
    pool = WORK / "staging" / "_attachments"
    pool.mkdir(parents=True, exist_ok=True)
    output = Path(args.output)
    results = {}
    done = 0

    def save():
        temporary = output.with_name(output.name + ".tmp")
        ordered = [results[url] for url in urls if url in results]
        temporary.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(download, url, pool): url for url in urls}
        for job in concurrent.futures.as_completed(jobs):
            url = jobs[job]
            try:
                original, local, status = job.result()
            except Exception as exc:
                original, local, status = url, None, "failed:" + str(exc)
            results[url] = {"url": original, "local": local, "status": status}
            done += 1
            if done % 100 == 0:
                save()
                print(f"{Path(args.input).name}: {done}/{len(urls)}", flush=True)
    save()
    failures = sum(not item["local"] for item in results.values())
    print(f"{Path(args.input).name}: completed {len(results)}, failures {failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
