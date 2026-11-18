"""
PDF 存档 - 把 DOWNLOAD_DIR 的 PDF 增量归档到项目资料库（唯一 PDF 目的地）。

分工（用户规则，2026-11-12）：
  **知识库只放 MD，PDF 只归档到资料库。** 两边靠同一个 stem 对应。

归档目的地：项目资料库 周老师茶馆历史文档/（分类归档，只存 PDF）
     - JM 系列          -> 历史学习资料-YYYY（YYYY = **发布年**，由新命名
                           ``YY.MM月-...`` 推出；<=2020 进 历史学习资料-2020及以前），
                           文件名与知识库中的 .md 完全一致
     - python学习材料 / ptyhon学习材料（蓝奏云误拼变体）
       / 外篇 / WP 系列 -> Python学习材料/（沿用原名）
     - 其他未识别前缀不擅自分类：输出 [WARN] 等人工确认，不落盘。

独立用法：
    python3 archive_pdfs.py            # 增量归档（已存在同名 .pdf 或同编号跳过）
    python3 archive_pdfs.py --dry-run  # 只显示，不复制

被 sync.py 自动调用：sync 流水线的"步骤7"会调用 archive_pdfs()。

返回值口径：archive_pdfs() 返回 (copied, skipped)，为所有目的地合计（现在只有一个
目的地，即拷贝数与跳过数）。sync.py 只做日志展示，不解析构成。

约定（与 §4.4 rename_exe_to_pdf 一致）：
    - 已存在同名 .pdf 跳过不覆盖，保持幂等
    - 不动 DOWNLOAD_DIR 里的源 PDF（仍然是工作区）
    - 不删 .zip / .exe 残留
    - 资料库不生成 .md；.md 只由 pdf_to_md 写到知识库
"""

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import naming  # 茶馆杂谈 JM 命名规则（唯一事实源）

# ── 配置（与 sync.py 顶部常量保持一致）────────────────────
PROJECT_ROOT    = Path(__file__).parent.parent
DOWNLOAD_DIR    = Path("/Users/allenwywang/allen个人项目/project-zhou/茶馆杂谈文件同步")
LIBRARY_ROOT    = PROJECT_ROOT / "周老师茶馆历史文档"
# 历史学习知识库（独立 Obsidian 库，与 project-zhou 同级目录；
# 2026-11-06 从 周老师茶馆历史文档/历史学习资料项目/ 迁出到这个位置）
HISTORY_KB_ROOT = PROJECT_ROOT.parent / "历史学习资料"
MARKDOWN_DIR    = HISTORY_KB_ROOT / "历史学习" / "raw" / "articles" / "茶馆杂谈" / "JM系列"

# 项目资料库分类：文件名（去扩展名）前缀 -> 目标子目录
# python 系列含 ptyhon 误拼变体（蓝奏云偶发返回，见 sync.py._file_matches_short_id）
_SERIES_PREFIXES = ("JM", "python学习材料", "ptyhon学习材料", "外篇", "WP")
_SERIES_PAT = re.compile(rf"^({'|'.join(_SERIES_PREFIXES)})\d+")

# 年份分档：<=2020 统一进这个目录（沿用既有目录口径，不新建 2018/2019）
LEGACY_YEAR_DIR = "历史学习资料-2020及以前"
YEAR_DIR_PAT = re.compile(r"^历史学习资料-(?:\d{4}|2020及以前)$")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def classify_project_dest(filename: str, year: Optional[int] = None) -> Optional[Path]:
    """
    按文件名把 PDF 分到项目资料库的目标子目录；未识别系列返回 None。

    - JM\d...                  -> 历史学习资料-<发布年>；<=2020 统一进
                                  「历史学习资料-2020及以前」（沿用既有目录口径）
    - python学习材料\d... / ptyhon学习材料\d... / 外篇\d... / WP\d...
                               -> Python学习材料

    year 由新命名 ``YY.MM月-...`` 推出（发布年）；缺省时退回当前年。
    """
    stem = Path(filename).stem
    is_jm = naming.is_jm_series(stem)
    if not (is_jm or _SERIES_PAT.match(stem)):
        return None
    if is_jm:
        y = year or naming.year_of(stem) or datetime.now().year
        return LIBRARY_ROOT / (LEGACY_YEAR_DIR if y <= 2020 else f"历史学习资料-{y}")
    return LIBRARY_ROOT / "Python学习材料"


def _copy_incremental(src: Path, dest_dir: Path, dry_run: bool, verbose: bool,
                      label: str, counters: list[int], dest_name: Optional[str] = None):
    """增量拷贝单个文件到 dest_dir；counters = [copied, skipped] 原地累加。

    dest_name 用于知识库的新命名（``YY.MM月-JMxxx-标题.pdf``）；省略则沿用源文件名
    （项目资料库保持原名，不受命名规则影响）。
    """
    name = dest_name or src.name
    dest = dest_dir / name
    if dest.exists():
        counters[1] += 1
        return
    if dry_run:
        log(f"  [DRY] 待拷贝({label}): {name}")
        counters[0] += 1
        return
    shutil.copy2(src, dest)
    counters[0] += 1
    if verbose:
        log(f"  [OK] 已归档({label}): {name}")


def archive_pdfs(dry_run: bool = False, verbose: bool = True,
                 namer=None) -> tuple[int, int]:
    """
    把 DOWNLOAD_DIR 里的 .pdf 增量归档到**项目资料库**（2026-11-12 起唯一目的地）：
      - JM 系列：文件名用 ``YY.MM月-JMxxx-标题.pdf``，按**发布年**落进
        ``历史学习资料-YYYY``（<=2020 统一进 ``历史学习资料-2020及以前``）
      - python / 外篇 / WP：``Python学习材料/``，沿用原名
      - 未识别前缀：仅 [WARN]，不擅自归类

    **历史学习知识库只放 MD，不放 PDF**（用户规则，2026-11-12）：PDF 一律进资料库，
    知识库的 ``MARKDOWN_DIR`` 由 ``pdf_to_md`` 只写 ``.md``。
    namer(pdf_stem) -> 新 stem 由 sync.py 按条目日期提供；缺省或返回 None 时沿用原名。
    按 JM 编号跨全部年度目录预扫判重，避免同一篇被重复入库。

    返回 (copied, skipped)，为所有目的地合计。
    """
    if not LIBRARY_ROOT.is_dir():
        raise SystemExit(f"[FAIL] 项目资料库不存在: {LIBRARY_ROOT}")

    # 项目资料库跨年度目录的 JM 编号（重命名后可能换目录，必须跨目录判重）
    existing_lib_jm = set()
    for d in LIBRARY_ROOT.iterdir():
        if not d.is_dir() or not YEAR_DIR_PAT.match(d.name):
            continue
        for p in d.glob("*.pdf"):
            num = naming.extract_jm_num(p.stem)
            if num is not None:
                existing_lib_jm.add(num)

    counters = [0, 0]  # copied, skipped
    for pdf in sorted(DOWNLOAD_DIR.glob("*.pdf")):
        jm_num = naming.extract_jm_num(pdf.stem)
        new_stem = namer(pdf.stem) if (namer and jm_num is not None) else None
        dest_name = (new_stem + pdf.suffix) if new_stem else None

        project_dir = classify_project_dest(pdf.name,
                                           year=naming.year_of(new_stem) if new_stem else None)
        if project_dir is None:
            log(f"  [WARN] 未识别系列，未归档: {pdf.name}")
            continue
        if jm_num is not None and jm_num in existing_lib_jm:
            counters[1] += 1
            continue
        project_dir.mkdir(parents=True, exist_ok=True)
        _copy_incremental(pdf, project_dir, dry_run, verbose,
                          f"项目资料库/{project_dir.name}", counters, dest_name=dest_name)
    return counters[0], counters[1]


def main():
    parser = argparse.ArgumentParser(
        description="归档 PDF 到项目资料库（分类归档；知识库只放 MD）")
    parser.add_argument("--dry-run", action="store_true", help="只显示待拷贝列表，不实际复制")
    args = parser.parse_args()

    log(f"DOWNLOAD_DIR: {DOWNLOAD_DIR}")
    log(f"LIBRARY_ROOT: {LIBRARY_ROOT}")
    copied, skipped = archive_pdfs(dry_run=args.dry_run)
    log(f"\n归档完成: 拷贝 {copied} 个, 跳过 {skipped} 个已存在")

    if copied == 0 and skipped == 0:
        log("(DOWNLOAD_DIR 里没有 .pdf 文件)")


if __name__ == "__main__":
    main()
