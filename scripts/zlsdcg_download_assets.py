#!/usr/bin/env python3
"""Download only images for approved site posts, atomically and idempotently."""
import argparse
import concurrent.futures
import hashlib
import imghdr
import json
import mimetypes
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
KB = Path("/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采")
STAGING = WORK / "staging"
LIMIT = 20 * 1024 * 1024


def approved_items():
    path = WORK / "publish_manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_url(url):
    """Resolve the former hostname and encode paths without losing the source key."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return url
    if parsed.hostname == "zhoulaoshidechaguan.com":
        parsed = parsed._replace(scheme="https", netloc="zlsdcg.com")
    if parsed.hostname == "youwuqiong.top" and parsed.path == "/wp-admin/img.php":
        embedded = urllib.parse.parse_qs(parsed.query).get("imgUrl", [""])[0]
        if embedded.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(embedded)
    parts = urllib.parse.urlsplit(urllib.parse.urlunparse(parsed))
    return urllib.parse.urlunsplit(parts._replace(
        path=urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%")))


def download(url, pool):
    original = url
    if not url or url.startswith("data:"):
        return original, None, "embedded"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return original, None, "unsupported_scheme"
    url = canonical_url(url)
    filename = hashlib.sha256(url.encode()).hexdigest()[:20]
    existing = sorted(path for path in pool.glob(filename + ".*")
                      if path.is_file() and not path.name.endswith(".tmp"))
    if existing and existing[0].stat().st_size:
        return original, existing[0].name, "existing"
    error = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://zlsdcg.com/"})
            with urllib.request.urlopen(request, timeout=45) as response:
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
                if content_type == "application/octet-stream":
                    content_type = mimetypes.guess_type(urllib.parse.urlsplit(url).path)[0] or content_type
                if not content_type.startswith("image/"):
                    return original, None, "not_image:" + content_type
                blob = response.read(LIMIT + 1)
            if not blob or len(blob) > LIMIT:
                return original, None, "empty_or_oversize"
            if content_type == "image/svg+xml":
                return original, None, "svg_not_supported"
            detected = imghdr.what(None, blob)
            if not detected:
                return original, None, "invalid_or_unrecognized_image"
            extension = mimetypes.guess_extension(content_type) or "." + detected
            if extension == ".jpe":
                extension = ".jpg"
            name = filename + extension
            # URL shards overlap only with the original full-list worker. Give
            # each process its own temp file so one cannot rename another's temp.
            temporary = pool / (name + f".{os.getpid()}.{threading.get_ident()}.tmp")
            temporary.write_bytes(blob)
            os.replace(temporary, pool / name)
            return original, name, "downloaded"
        except Exception as exc:
            error = str(exc)
            time.sleep(1 + attempt)
    return original, None, "failed:" + (error or "unknown")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    items = approved_items()
    if not items:
        print("[OK] 输入清单尚未生成")
        return 0
    (STAGING / "_attachments").mkdir(parents=True, exist_ok=True)
    jobs = {}
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for item in items:
            md_path = STAGING / (item["stem"] + ".md")
            text = md_path.read_text(encoding="utf-8")
            urls = set(re.findall(r"!\[[^]]*\]\((https?://[^)\s]+)\)", text))
            for url in urls:
                if url not in jobs:
                    jobs[url] = executor.submit(download, url, STAGING / "_attachments")
        mapping = {}
        for url, job in jobs.items():
            _, local, status = job.result()
            mapping[url] = {"local": local, "status": status}
            if not local:
                failures.append({"url": url, "status": status})
        for item in items:
            md_path = STAGING / (item["stem"] + ".md")
            text = md_path.read_text(encoding="utf-8")
            for url, result in mapping.items():
                if result["local"]:
                    text = text.replace("](" + url + ")", "](_attachments/" + result["local"] + ")")
            md_path.write_text(text, encoding="utf-8")
    (WORK / "asset_results.json").write_text(json.dumps(
        {"unique_images": len(jobs), "mapping": mapping, "failures": failures},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"unique images {len(jobs)}; failed {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
