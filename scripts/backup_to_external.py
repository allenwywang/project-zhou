#!/usr/bin/env python3
"""手动增量备份：本机资料库 -> 外置盘。

用法（必须由用户挂载外置盘后手动执行）：
    python3 scripts/backup_to_external.py            # 增量同步 + 同步后校验
    python3 scripts/backup_to_external.py --check    # 只读体检，不写入

约定：
    - 外置盘未挂载或备份根目录不存在时直接报错退出，绝不自动创建根路径
    - 备份侧已存在且内容不同的文件只列异常，不覆盖
    - 备份侧多出的文件只报告，不删除
    - `.DS_Store` 与 `._` 前缀的 AppleDouble 元数据一律忽略，不参与比对、不计入 extra，也不删除
    - 只依赖标准库，兼容本机 Python 3.9
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

SOURCE = Path("/Users/allenwywang/allen个人项目/project-zhou/周老师茶馆历史文档")
BACKUP = Path("/Volumes/My PSSD/文档资料/project-zhou")
VOLUMES = Path("/Volumes")

# 外置盘沿用旧目录命名，不重命名目录
DIR_MAP = {
    "历史学习资料-2020及以前": "历史学习材料",
    "历史学习资料-2021": "历史学习材料-2021",
    "历史学习资料-2022": "历史学习材料-2022",
    "历史学习资料项目": "历史学习资料",
}

# Finder / AppleDouble 元数据，不是用户资料：不参与比对，也不计入 extra
DS_STORE_NAME = ".DS_Store"
APPLEDOUBLE_PREFIX = "._"

CHUNK_SIZE = 1024 * 1024
MAX_DETAIL = 50

EXIT_OK = 0
EXIT_DIFF = 1
EXIT_SETUP = 2


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_mount_point(backup):
    """备份路径位于 /Volumes 下时，返回它所属的外置盘挂载点。"""
    try:
        rel = backup.relative_to(VOLUMES)
    except ValueError:
        return None
    if len(rel.parts) >= 2:
        return VOLUMES / rel.parts[0]
    return VOLUMES


def map_rel(rel):
    """把源端相对路径按 DIR_MAP 映射到备份端命名。"""
    parts = list(rel.parts)
    if parts:
        parts[0] = DIR_MAP.get(parts[0], parts[0])
    return Path(*parts)


def scan(root):
    """扫描目录，返回 {相对路径: 绝对路径} 与被忽略的元数据计数。"""
    files = {}
    ignored = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == DS_STORE_NAME:
            ignored[DS_STORE_NAME] = ignored.get(DS_STORE_NAME, 0) + 1
            continue
        if path.name.startswith(APPLEDOUBLE_PREFIX):
            ignored[APPLEDOUBLE_PREFIX] = ignored.get(APPLEDOUBLE_PREFIX, 0) + 1
            continue
        files[path.relative_to(root)] = path
    return files, ignored


def report_list(label, marker, items):
    for item in items[:MAX_DETAIL]:
        print("{0} {1}: {2}".format(marker, label, item))
    if len(items) > MAX_DETAIL:
        print("{0} {1}: ... ({2} more, full list not printed)".format(
            marker, label, len(items) - MAX_DETAIL))


def print_summary(counts):
    print("")
    print("=== summary ===")
    for key in sorted(counts):
        print("{0:<12}: {1}".format(key, counts[key]))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Incremental backup of the local library to an external drive.")
    parser.add_argument("--check", action="store_true",
                        help="read-only inspection, no writes")
    parser.add_argument("--source", default=str(SOURCE),
                        help="source library root")
    parser.add_argument("--backup", default=str(BACKUP),
                        help="backup root on the external drive")
    args = parser.parse_args(argv)

    source = Path(args.source)
    backup = Path(args.backup)
    check_only = args.check

    print("mode      : {0}".format("check (read-only)" if check_only else "sync"))
    print("source    : {0}".format(source))
    print("backup    : {0}".format(backup))

    if not source.is_dir():
        print("[FAIL] source directory not found: {0}".format(source))
        return EXIT_SETUP

    if not backup.is_dir():
        mount_point = find_mount_point(backup)
        if mount_point is not None and not mount_point.is_dir():
            print("[FAIL] external drive is not mounted: {0} is absent".format(mount_point))
        else:
            print("[FAIL] backup root not found: {0}".format(backup))
        print("[FAIL] refusing to create the backup root automatically;"
              " mount the drive and prepare the folder by hand")
        return EXIT_SETUP

    src_files, src_ignored = scan(source)
    bak_files, bak_ignored = scan(backup)

    mapped = {}
    for rel, path in sorted(src_files.items()):
        target_rel = map_rel(rel)
        if target_rel in mapped:
            print("[WARN] source path collision after mapping: {0}".format(target_rel))
            continue
        mapped[target_rel] = path

    missing = []
    different = []
    copied = []
    skipped = 0

    for rel, src_path in sorted(mapped.items()):
        dst = backup / rel
        if not dst.exists():
            if check_only:
                missing.append(rel)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst)
            copied.append(rel)
            print("[OK] copied {0}".format(rel))
            continue
        if not dst.is_file():
            different.append(rel)
            print("[FAIL] destination is not a regular file (not overwritten): {0}".format(rel))
            continue
        if sha256(src_path) == sha256(dst):
            skipped += 1
        else:
            different.append(rel)
            print("[FAIL] different (not overwritten): {0}".format(rel))

    if not check_only:
        # 同步后复检：重新扫描并逐个比对 SHA-256，结果覆盖同步前的判定
        bak_files, bak_ignored = scan(backup)
        missing = []
        different = []
        for rel, src_path in sorted(mapped.items()):
            dst = backup / rel
            if not dst.exists():
                missing.append(rel)
            elif not dst.is_file():
                different.append(rel)
            elif sha256(src_path) != sha256(dst):
                different.append(rel)

    extra = sorted(rel for rel in bak_files if rel not in mapped)

    report_list("missing", "[FAIL]", missing)
    report_list("different", "[FAIL]", different)
    report_list("extra", "[WARN]", extra)

    counts = {
        "copied": len(copied),
        "skipped": skipped,
        "identical": skipped,
        "missing": len(missing),
        "different": len(different),
        "extra": len(extra),
        "ignored_ds_store": src_ignored.get(DS_STORE_NAME, 0)
        + bak_ignored.get(DS_STORE_NAME, 0),
        "ignored_apple_double": src_ignored.get(APPLEDOUBLE_PREFIX, 0)
        + bak_ignored.get(APPLEDOUBLE_PREFIX, 0),
    }
    print_summary(counts)

    if missing or different:
        print("[FAIL] backup is not in sync with the source library")
        return EXIT_DIFF
    print("[OK] backup verified")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
