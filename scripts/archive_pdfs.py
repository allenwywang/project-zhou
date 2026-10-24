"""
双格式存档 - 把 DOWNLOAD_DIR 的 PDF 增量拷贝到 MARKDOWN_DIR。

设计目标：MD 在 MARKDOWN_DIR 日常使用，原版 PDF 在同一目录作为存档
（保留原文版式 / 字体 / 图片，方便回溯；MD 转 PDF 排版会损失）。

独立用法：
    python3 archive_pdfs.py            # 增量拷贝（已存在同名 .pdf 跳过）
    python3 archive_pdfs.py --dry-run  # 只显示，不复制

被 sync.py 自动调用：sync 流水线的"步骤7/9"会调用 archive_pdfs()。

约定（与 §4.4 rename_exe_to_pdf 一致）：
    - 已存在同名 .pdf 跳过不覆盖，保持幂等
    - 不动 DOWNLOAD_DIR 里的源 PDF（仍然是工作区）
    - 不删 .zip / .exe 残留
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ── 配置（与 sync.py 顶部常量保持一致）────────────────────
PROJECT_ROOT    = Path(__file__).parent.parent
DOWNLOAD_DIR    = Path("/Users/allenwywang/allen个人项目/project-zhou/茶馆杂谈文件同步")
MARKDOWN_DIR    = Path("/Users/allenwywang/历史学习资料/历史学习/raw/articles/茶馆杂谈")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def archive_pdfs(dry_run: bool = False, verbose: bool = True) -> tuple[int, int]:
    """
    把 DOWNLOAD_DIR 里所有 .pdf 增量拷贝到 MARKDOWN_DIR。

    返回 (copied, skipped)。
    """
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for pdf in sorted(DOWNLOAD_DIR.glob("*.pdf")):
        dest = MARKDOWN_DIR / pdf.name
        if dest.exists():
            skipped += 1
            continue
        if dry_run:
            log(f"  [DRY] 待拷贝: {pdf.name}")
            copied += 1
            continue
        shutil.copy2(pdf, dest)
        copied += 1
        if verbose:
            log(f"  [OK] 已归档: {pdf.name}")
    return copied, skipped


def main():
    parser = argparse.ArgumentParser(description="归档 PDF 到 MARKDOWN_DIR（双格式存档）")
    parser.add_argument("--dry-run", action="store_true", help="只显示待拷贝列表，不实际复制")
    args = parser.parse_args()

    log(f"DOWNLOAD_DIR: {DOWNLOAD_DIR}")
    log(f"MARKDOWN_DIR: {MARKDOWN_DIR}")
    copied, skipped = archive_pdfs(dry_run=args.dry_run)
    log(f"\n归档完成: 拷贝 {copied} 个, 跳过 {skipped} 个已存在")

    if copied == 0 and skipped == 0:
        log("(DOWNLOAD_DIR 里没有 .pdf 文件)")


if __name__ == "__main__":
    main()