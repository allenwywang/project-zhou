"""
PDF → Markdown 转换器（支持多重量档）

用法：
    cd scripts
    python3 pdf_to_md.py                    # 默认 light 模式（转换即排版）
    python3 pdf_to_md.py --mode light       # 显式指定轻量模式
    python3 pdf_to_md.py --mode medium      # 中等模式（预留接口）
    python3 pdf_to_md.py --mode full        # 完整模式（预留接口）
    python3 pdf_to_md.py --auto             # 自动检测并推荐模式
    python3 pdf_to_md.py --no-format        # 调试用：跳过排版（正常同步不要用）

模式说明：
    light   — 双引擎文本提取（pdfplumber + PyMuPDF），适合纯文字PDF
    medium  — 文本提取 + 基础视觉检查（图表/表格识别），适合图文混合
    full    — multidoc 全5层深度分析，适合复杂方案/PPT深度还原

排版（2026-11-12 起内建，见 AGENTS.md §4.5）：
    PDF 文本层按「页面物理行」导出，直接落盘会得到全篇无空行的硬切文本。
    本转换器在 write_text 之前调用 md_layout.layout() 还原逻辑自然段，
    并通过字符守恒 / 标题 / 空行 / 硬换行率下降四重校验；校验不通过
    抛异常且不落盘（fail-close），避免无排版或掉字的 MD 进入知识库。
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import naming  # 茶馆杂谈 JM 命名规则（唯一事实源）
import md_layout  # 转换即排版：纯规则模块，与知识库侧由 test_md_layout.py 对齐

try:
    import pdfplumber
    import fitz  # PyMuPDF
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请安装: pip install pdfplumber PyMuPDF")
    raise SystemExit(1)

# ── 配置（Mac 本地适配）──────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
DOWNLOAD_DIR = Path("/Users/allenwywang/allen个人项目/project-zhou/茶馆杂谈文件同步")
# 历史学习知识库（独立 Obsidian 库，与 project-zhou 同级目录；
# 2026-11-06 从 周老师茶馆历史文档/历史学习资料项目/ 迁出到这个位置）
HISTORY_KB_ROOT = PROJECT_ROOT.parent / "历史学习资料"
OUTPUT_DIR   = HISTORY_KB_ROOT / "历史学习" / "raw" / "articles" / "茶馆杂谈" / "JM系列"
QC_REPORT    = OUTPUT_DIR / "_qc_report.json"

# 转换范围：只转 JM 系列。python学习材料 / ptyhon学习材料 / 外篇 / WP 照常下载与归档，
# 但不做 PDF -> Markdown 转换。判定统一走 naming.is_jm_series()（新命名
# "YY.MM月-JM123-标题" / "YY.MM月-JM早期文章-标题" 与旧名都认）。

# 质检阈值
CHAR_DIFF_THRESHOLD = 0.15
MIN_CHARS_PER_PAGE  = 10
# ─────────────────────────────────────────────────────────


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '', name).strip()


class PdfConverter:
    """
    PDF → Markdown 转换器（支持 light / medium / full 三档）
    """
    MODES = ["light", "medium", "full"]

    def __init__(self, mode: str = "light", do_format: bool = True):
        if mode not in self.MODES:
            raise ValueError(f"不支持的模式: {mode}，可选: {self.MODES}")
        self.mode = mode
        # 转换即排版；--no-format 仅用于诊断，正常同步一律保持 True
        self.do_format = do_format

    # ═══════════════════════════════════════════════════════
    #  公共接口
    # ═══════════════════════════════════════════════════════

    def convert(self, pdf_path: Path, output_dir: Optional[Path] = None,
                namer=None) -> tuple[Path, dict]:
        """
        转换单个PDF，返回 (md_path, qc_result)

        output_dir 为 MD 落盘目录；省略则用模块级 OUTPUT_DIR。
        namer(pdf_stem) -> 新 MD stem（``YY.MM月-JMxxx-标题``）；省略/None 时用原名。
        """
        if self.mode == "light":
            return self._convert_light(pdf_path, output_dir, namer)
        elif self.mode == "medium":
            return self._convert_medium(pdf_path, output_dir, namer)
        elif self.mode == "full":
            return self._convert_full(pdf_path, output_dir, namer)

    def convert_batch(self, pdf_dir: Path, output_dir: Path,
                      only_jm: bool = True, namer=None) -> dict:
        """
        批量转换目录下PDF，返回汇总报告。

        only_jm=True（默认）：只转换 JM 系列。python学习材料 / ptyhon学习材料 /
        外篇 / WP 系列仍会被下载和归档，但不生成 Markdown。
        """
        all_pdfs = sorted(pdf_dir.glob("*.pdf"))
        if not all_pdfs:
            return {"error": f"目录中没有PDF文件: {pdf_dir}"}
        # 防御：知识库根缺失时报错，避免 mkdir 静默建出空目录
        if not HISTORY_KB_ROOT.is_dir():
            return {"error": f"历史学习知识库不存在: {HISTORY_KB_ROOT}"}

        pdf_files = [p for p in all_pdfs if naming.is_jm_series(p.stem)] if only_jm else all_pdfs
        skipped_non_jm = len(all_pdfs) - len(pdf_files)
        if skipped_non_jm:
            print(f"[SKIP] 非 JM 系列 {skipped_non_jm} 个，不做 MD 转换（仍已归档）")
        if not pdf_files:
            print("[INFO] 没有可转换的 JM 系列 PDF，跳过")
            return {
                "mode": self.mode,
                "stats": {"total": 0, "passed": 0, "warn": 0, "failed": 0,
                          "skipped": 0, "skipped_non_jm": skipped_non_jm,
                          "layout_ok": 0},
                "details": [],
            }

        output_dir.mkdir(parents=True, exist_ok=True)

        # 按 JM 编号预扫已存在的 MD（新命名不带 JM 前缀，不能用文件名直接比对），
        # 已转换过的历史文件直接跳过，避免每次同步重复生成一份。
        existing_nums = set()
        for p in output_dir.glob("*.md"):
            num = naming.extract_jm_num(p.stem)
            if num is not None:
                existing_nums.add(num)

        results = []
        stats = {"total": 0, "passed": 0, "warn": 0, "failed": 0, "skipped": 0,
                 "skipped_non_jm": skipped_non_jm, "skipped_exists": 0,
                 "layout_ok": 0}

        for idx, pdf_path in enumerate(pdf_files, 1):
            print(f"[{idx:>3}/{len(pdf_files)}] {pdf_path.name}")
            stats["total"] += 1

            # 该 JM 编号已存在于知识库（新命名）→ 跳过，避免重复转换
            jm_num = naming.extract_jm_num(pdf_path.stem)
            if jm_num is not None and jm_num in existing_nums:
                stats["skipped_exists"] += 1
                continue

            # 自动检测：如果非 light 模式且文件是纯文字，降级提示
            if self.mode in ("medium", "full"):
                is_pure_text = self._detect_pure_text(pdf_path)
                if is_pure_text:
                    print(f"  [INFO] 检测到纯文字PDF，light模式已足够")
                    print(f"         当前模式: {self.mode}，建议用 light 以节省资源")
                    stats["skipped"] += 1
                    continue

            try:
                md_path, qc = self.convert(pdf_path, output_dir, namer)
                results.append(qc)
                if qc.get("layout", {}).get("ok") is True:
                    stats["layout_ok"] += 1

                if qc.get("has_error"):
                    print(f"  [QC-ERROR] 发现严重差异！")
                    stats["failed"] += 1
                elif qc.get("has_warn"):
                    print(f"  [QC-WARN] 有轻微差异")
                    stats["warn"] += 1
                else:
                    print(f"  [OK] 质检通过 -> {md_path.name}")
                    stats["passed"] += 1

            except Exception as e:
                print(f"  [FAIL] {e}")
                stats["failed"] += 1
                results.append({"file": pdf_path.name, "error": str(e)})

        summary = {
            "mode": self.mode,
            "rule_version": md_layout.RULE_VERSION,
            "stats": stats,
            "details": results,
        }
        # 质检报告跟输出目录走（与 MD 同目录），不再写死模块级 QC_REPORT
        qc_path = (output_dir or OUTPUT_DIR) / "_qc_report.json"
        qc_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    # ═══════════════════════════════════════════════════════
    #  模式：light（双引擎文本提取）
    # ═══════════════════════════════════════════════════════

    def _convert_light(self, pdf_path: Path, output_dir: Optional[Path] = None,
                       namer=None) -> tuple[Path, dict]:
        """轻量模式：双引擎文本提取 + 交叉验证 + 内建排版"""
        title = pdf_path.stem.strip()
        md_stem = namer(pdf_path.stem) if namer else None
        md_filename = (md_stem or sanitize_filename(title)) + ".md"
        md_path = (output_dir or OUTPUT_DIR) / md_filename

        # 双引擎提取
        pl_pages, pl_total = self._extract_pdfplumber(pdf_path)
        fitz_pages, fitz_total, image_counts = self._extract_fitz(pdf_path)

        # 逐页质检
        page_qc = self._compare_pages(pl_pages, fitz_pages, image_counts)
        has_error = any(p["status"] == "error" for p in page_qc)
        has_warn = any(p["status"] == "warn" for p in page_qc)

        # 选择更完整的引擎输出
        final_pages = []
        for i in range(max(len(pl_pages), len(fitz_pages))):
            pl_text = pl_pages[i] if i < len(pl_pages) else ""
            fitz_text = fitz_pages[i] if i < len(fitz_pages) else ""
            pl_len = len(pl_text.strip())
            fitz_len = len(fitz_text.strip())
            final_pages.append(fitz_text if fitz_len > pl_len * 1.2 else pl_text)

        # 生成原始（物理行）MD → 排版 → 门禁校验 → 才落盘
        raw_md = self._pages_to_markdown(title, final_pages)
        if self.do_format:
            md_content, layout = md_layout.layout(raw_md, md_filename)
            if not layout["ok"]:
                # fail-close：绝不把未排版或掉字的 MD 写进知识库
                raise RuntimeError(
                    "[LAYOUT-FAIL] %s: %s" % (md_filename, "; ".join(layout["reasons"])))
            # 物理行输入必然会被重排；完全一致说明排版链路被绕过。
            # 例外：源 PDF 无文本层（正文为空）时 MD 只有头部，排版无事可做，
            # 交回既有 QC 的「纯图片页」error 处理，不在这里误杀。
            if md_content == raw_md and layout.get("src_chars", 0) > 0:
                raise RuntimeError(
                    "[LAYOUT-FAIL] %s: 排版未生效（输出与物理行原文一致）" % md_filename)
            if layout.get("src_chars", 0) == 0:
                print("  [WARN] 正文为空（源 PDF 无文本层），排版跳过生效检查")
            print("  [OK] 排版校验通过: %d 段, 硬换行 %.2f -> %.2f"
                  % (layout["paras"], layout["raw_hard_ratio"],
                     layout["formatted_hard_ratio"]))
        else:
            md_content = raw_md
            layout = {"ok": None, "skipped": True,
                      "rule_version": md_layout.RULE_VERSION}
            print("  [WARN] --no-format：跳过排版（仅调试用）")
        md_path.write_text(md_content, encoding="utf-8")

        qc = {
            "file": pdf_path.name,
            "mode": "light",
            "pages": len(final_pages),
            "total_images": sum(image_counts),
            "pl_total_chars": pl_total,
            "fitz_total_chars": fitz_total,
            "final_total_chars": len(raw_md),
            "formatted_total_chars": len(md_content),
            "layout": layout,
            "has_error": has_error,
            "has_warn": has_warn,
            "page_qc": page_qc,
        }
        return md_path, qc

    # ═══════════════════════════════════════════════════════
    #  模式：medium（预留接口）
    # ═══════════════════════════════════════════════════════

    def _convert_medium(self, pdf_path: Path, output_dir: Optional[Path] = None,
                        namer=None) -> tuple[Path, dict]:
        """
        中等模式：文本提取 + 基础视觉检查（图表/表格识别）
        预留接口 — 未来接入 multidoc 文本通道 + 图表/表格还原
        """
        # TODO: 接入 multidoc 的文本通道 + 基础视觉层（Layer 1 + Layer 4 轻量版）
        # 当前降级到 light 并提示
        print(f"  [INFO] medium 模式预留中，当前降级到 light")
        md_path, qc = self._convert_light(pdf_path, output_dir, namer)
        qc["mode"] = "medium (fallback to light)"
        return md_path, qc

    # ═══════════════════════════════════════════════════════
    #  模式：full（预留接口）
    # ═══════════════════════════════════════════════════════

    def _convert_full(self, pdf_path: Path, output_dir: Optional[Path] = None,
                      namer=None) -> tuple[Path, dict]:
        """
        完整模式：multidoc 全5层深度分析
        预留接口 — 未来接入 multidoc-transfer-multimodal 技能
        """
        # TODO: 调用 multidoc-transfer-multimodal 技能进行深度分析
        # 当前降级到 light 并提示
        print(f"  [INFO] full 模式预留中，当前降级到 light")
        md_path, qc = self._convert_light(pdf_path, output_dir, namer)
        qc["mode"] = "full (fallback to light)"
        return md_path, qc

    # ═══════════════════════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════════════════════

    def _extract_pdfplumber(self, pdf_path: Path) -> tuple[list[str], int]:
        pages = []
        total = 0
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text)
                total += len(text.strip())
        return pages, total

    def _extract_fitz(self, pdf_path: Path) -> tuple[list[str], int, list[int]]:
        pages = []
        total = 0
        image_counts = []
        doc = fitz.open(str(pdf_path))
        for page in doc:
            text = page.get_text()
            pages.append(text)
            total += len(text.strip())
            image_counts.append(len(page.get_images()))
        doc.close()
        return pages, total, image_counts

    def _compare_pages(self, pl_pages, fitz_pages, image_counts) -> list[dict]:
        max_pages = max(len(pl_pages), len(fitz_pages))
        results = []
        for i in range(max_pages):
            pl_text = pl_pages[i] if i < len(pl_pages) else ""
            fitz_text = fitz_pages[i] if i < len(fitz_pages) else ""
            img_count = image_counts[i] if i < len(image_counts) else 0
            pl_chars = len(pl_text.strip())
            fitz_chars = len(fitz_text.strip())
            char_diff = abs(pl_chars - fitz_chars)
            avg_chars = (pl_chars + fitz_chars) / 2 if (pl_chars + fitz_chars) > 0 else 1
            diff_ratio = char_diff / avg_chars

            status = "ok"
            issues = []

            if img_count > 0 and avg_chars < 50:
                status = "warn"
                issues.append(f"检测到图文混合页: 含{img_count}张图片, 文本仅{int(avg_chars)}字符")
            if i >= len(pl_pages) or i >= len(fitz_pages):
                status = "error"
                issues.append("页数不一致")
            elif pl_chars == 0 and fitz_chars == 0 and img_count == 0:
                # 2026-10-24 精细化：源 PDF 自带的空白尾页（实证 python874 第 3 页：
                # 双引擎一致判空、无图片、仅背景线条）属良性，不算漏提。
                # 仅当空白页位于末页且其余页有内容时降级；中间空白页仍 warn。
                others_have_text = any(
                    len((pl_pages[j] if j < len(pl_pages) else "").strip()) > 0
                    or len((fitz_pages[j] if j < len(fitz_pages) else "").strip()) > 0
                    for j in range(max_pages)
                    if j != i
                )
                if i == max_pages - 1 and others_have_text:
                    issues.append("末页空白（源 PDF 自带，双引擎一致判空，视为良性）")
                else:
                    status = "warn"
                    issues.append("空白页（无文本无图片）")
            elif pl_chars == 0 and fitz_chars == 0 and img_count > 0:
                status = "error"
                issues.append(f"纯图片页: 含{img_count}张图片但无文本层（需要OCR或多维度分析）")
            elif pl_chars == 0 and fitz_chars > MIN_CHARS_PER_PAGE:
                status = "error"
                issues.append(f"pdfplumber漏提: fitz有{fitz_chars}字符")
            elif fitz_chars == 0 and pl_chars > MIN_CHARS_PER_PAGE:
                status = "error"
                issues.append(f"fitz漏提: pdfplumber有{pl_chars}字符")
            elif diff_ratio > CHAR_DIFF_THRESHOLD and avg_chars > MIN_CHARS_PER_PAGE:
                status = "warn"
                issues.append(f"字符数差异: pdfplumber={pl_chars}, fitz={fitz_chars}, 差异率={diff_ratio:.1%}")

            results.append({
                "page": i + 1,
                "pl_chars": pl_chars,
                "fitz_chars": fitz_chars,
                "img_count": img_count,
                "diff_ratio": round(diff_ratio, 3),
                "status": status,
                "issues": issues,
            })
        return results

    def _pages_to_markdown(self, title: str, pages: list[str]) -> str:
        """生成原始物理行 MD（排版在调用方 _convert_light 里做，此函数保持原样）。"""
        md_lines = [
            f"# {title}",
            "",
            f"> 来源：茶馆杂谈系列",
            f"> 原文件：{title}.pdf",
            "",
            "---",
            "",
        ]
        for text in pages:
            if not text.strip():
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                md_lines.append("\n".join(lines))
                md_lines.append("")
        return "\n".join(md_lines)

    def _detect_pure_text(self, pdf_path: Path) -> bool:
        """快速检测是否为纯文字PDF（用于auto模式和中/全模式降级判断）"""
        doc = fitz.open(str(pdf_path))
        total_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        return total_images == 0


# ═══════════════════════════════════════════════════════════
#  自动检测模式：分析目录后推荐最佳模式
# ═══════════════════════════════════════════════════════════

def auto_detect_mode(pdf_dir: Path) -> str:
    """扫描目录，根据文件类型分布推荐转换模式"""
    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        return "light"

    pure_text = 0
    mixed = 0
    image_only = 0

    for pdf_path in pdf_files[:20]:  # 抽样检测前20个
        doc = fitz.open(str(pdf_path))
        for page in doc:
            img_count = len(page.get_images())
            text_len = len(page.get_text().strip())
            if img_count > 0 and text_len < 50:
                image_only += 1
            elif img_count > 0:
                mixed += 1
            else:
                pure_text += 1
        doc.close()

    total = pure_text + mixed + image_only
    if total == 0:
        return "light"

    print(f"\n[分析] 目录内容分析（抽样 {min(20, len(pdf_files))} 个文件）:")
    print(f"   纯文字页: {pure_text}")
    print(f"   图文混合页: {mixed}")
    print(f"   纯图片页: {image_only}")

    if image_only > 0:
        print(f"\n[WARN] 检测到纯图片/扫描页，建议用 full 模式（需OCR或视觉分析）")
        return "full"
    elif mixed > 0:
        print(f"\n[WARN] 检测到图文混合内容，建议用 medium 模式")
        return "medium"
    else:
        print(f"\n[OK] 全部为纯文字内容，light 模式足够")
        return "light"


# ═══════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PDF → Markdown 转换器")
    parser.add_argument("--mode", choices=PdfConverter.MODES, default="light",
                        help="转换模式: light(轻量)/medium(中等)/full(完整)")
    parser.add_argument("--auto", action="store_true",
                        help="自动检测目录内容并推荐模式")
    parser.add_argument("--input", type=Path, default=DOWNLOAD_DIR,
                        help="输入PDF目录")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="输出Markdown目录")
    parser.add_argument("--no-format", action="store_true",
                        help="调试用：跳过内建排版（正常同步不要用，会退回无排版 MD）")
    args = parser.parse_args()

    mode = args.mode
    if args.auto:
        mode = auto_detect_mode(args.input)
        print(f"\n[推荐] 模式: {mode}\n")

    print(f"转换模式: {mode}")
    print(f"排版规则: {'关闭(调试)' if args.no_format else md_layout.RULE_VERSION}")
    print(f"输入目录: {args.input}")
    print(f"输出目录: {args.output}\n")

    converter = PdfConverter(mode=mode, do_format=not args.no_format)
    summary = converter.convert_batch(args.input, args.output)

    print(f"\n{'=' * 50}")
    print("转换完成")
    print(f"{'=' * 50}")
    stats = summary.get("stats", {})
    print(f"总文件数: {stats.get('total', 0)}")
    print(f"通过    : {stats.get('passed', 0)}")
    print(f"警告    : {stats.get('warn', 0)}")
    print(f"失败    : {stats.get('failed', 0)}")
    print(f"排版通过: {stats.get('layout_ok', 0)}")
    if stats.get("skipped"):
        print(f"跳过    : {stats['skipped']} (模式过重，建议用 light)")
    print(f"\n质检报告: {args.output / '_qc_report.json'}")


if __name__ == "__main__":
    main()
