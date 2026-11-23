#!/usr/bin/env python3
"""Merge image shards, retry failures, localize MD, and produce a blocking audit."""
import hashlib
import imghdr
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zlsdcg_download_assets import canonical_url, download

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "zlsdcg_archive"
STAGING = WORK / "staging"
POOL = STAGING / "_attachments"
IMAGE_RE = re.compile(r"!\[[^]]*\]\(([^)]+)\)")


def local_name(url, pool=POOL):
    """Return a valid existing canonical image, independent of worker status logs."""
    canonical = canonical_url(url)
    prefix = hashlib.sha256(canonical.encode()).hexdigest()[:20]
    candidates = sorted(path for path in pool.glob(prefix + ".*")
                        if path.is_file() and not path.name.endswith(".tmp"))
    if len(candidates) > 1:
        raise RuntimeError(f"multiple canonical attachment files: {url}")
    if not candidates:
        return None, "missing"
    path = candidates[0]
    kind = imghdr.what(path)
    if not path.stat().st_size or not kind:
        return None, "invalid_or_unrecognized_image"
    return path.name, "localized"


def main():
    manifest = json.loads((WORK / "publish_manifest.json").read_text(encoding="utf-8"))
    recovery = json.loads((WORK / "blob_media_recovery.json").read_text(encoding="utf-8"))["recovery"]
    POOL.mkdir(parents=True, exist_ok=True)
    # Make recovery explicit in the staged MD before discovering all references.
    for item in manifest:
        path = STAGING / (item["stem"] + ".md")
        text = path.read_text(encoding="utf-8")
        for blob, source in recovery.items():
            text = text.replace("](" + blob + ")", "](" + source + ")")
        path.write_text(text, encoding="utf-8")

    urls = set()
    for item in manifest:
        text = (STAGING / (item["stem"] + ".md")).read_text(encoding="utf-8")
        urls.update(IMAGE_RE.findall(text))
    mapping = {}
    failures = []
    for number, url in enumerate(sorted(urls), 1):
        if not url.startswith(("http://", "https://")):
            mapping[url] = {"local": None, "status": "unsupported_scheme"}
            failures.append({"url": url, "status": "unsupported_scheme"})
            continue
        local, status = local_name(url)
        if not local:
            original, local, status = download(url, POOL)
            if local:
                local, status = local_name(url)
        mapping[url] = {"local": local, "status": status,
                        "canonical_url": canonical_url(url)}
        if not local:
            failures.append({"url": url, "status": status})
        if number % 500 == 0:
            print(f"checked {number}/{len(urls)}; failures {len(failures)}", flush=True)

    # A rerun may encounter already-localized references; leave those untouched.
    for item in manifest:
        path = STAGING / (item["stem"] + ".md")
        text = path.read_text(encoding="utf-8")
        for url, result in mapping.items():
            if result["local"]:
                text = text.replace("](" + url + ")", "](_attachments/" + result["local"] + ")")
        path.write_text(text, encoding="utf-8")

    temporary_files = [str(path) for path in POOL.glob("*.tmp")]
    payload = {"unique_images": len(urls), "mapping": mapping, "failures": failures,
               "recovered_blob_images": recovery, "temporary_files": temporary_files}
    temporary = WORK / "asset_results.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(WORK / "asset_results.json")
    print(json.dumps({"unique_images": len(urls), "failures": len(failures),
                      "temporary_files": len(temporary_files)}, ensure_ascii=False, indent=2))
    return 1 if failures or temporary_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
