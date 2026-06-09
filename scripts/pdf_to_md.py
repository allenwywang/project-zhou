"""
PDF → Markdown 转换器（支持多重量档）

用法：
    cd scripts
    python pdf_to_md.py                    # 默认 light 模式
    python pdf_to_md.py --mode light       # 显式指定轻量模式
    python pdf_to_md.py --mode medium      # 中等模式（预留接口）
    python pdf_to_md.py --mode full        # 完整模式（预留接口）
    python pdf_to_md.py --auto             # 自动检测并推荐模式

模式说明：
    light   — 双引擎文本提取（pdfplumber + PyMuPDF），适合纯文字PDF
    medium  — 文本提取 + 基础视觉检查（图表/表格识别），适合图文混合
    full    — multidoc 全5层深度分析，适合复杂方案/PPT深度还原
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
    import fitz  # PyMuPDF
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请安装: pip install pdfplumber PyMuPDF")
    raise SystemExit(1)

# ── 配置（Mac 本地适配）──────────────────────────────────
DOWNLOAD_DIR = Path("/Users/allenwywang/allen个人项目/project-zhou/茶馆杂谈文件同步")
OUTPUT_DIR   = Path("/Users/allenwywang/历史学习资料/历史学习/raw/articles/茶馆杂谈")
QC_REPORT    = OUTPUT_DIR / "_qc_report.json"

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

    def __init__(self, mode: str = "light"):
        if mode not in self.MODES:
            raise ValueError(f"不支持的模式: {mode}，可选: {self.MODES}")
        self.mode = mode

    # ═══════════════════════════════════════════════════════
    #  公共接口
    # ═══════════════════════════════════════════════════════

    def convert(self, pdf_path: Path) -> tuple[Path, dict]:
        """
        转换单个PDF，返回 (md_path, qc_result)
        """
        if self.mode == "light":
            return self._convert_light(pdf_path)
        elif self.mode == "medium":
            return self._convert_medium(pdf_path)
        elif self.mode == "full":
            return self._convert_full(pdf_path)

    def convert_batch(self, pdf_dir: Path, output_dir: Path) -> dict:
        """
        批量转换目录下所有PDF，返回汇总报告
        """
        pdf_files = sorted(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            return {"error": f"目录中没有PDF文件: {pdf_dir}"}

        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        stats = {"total": 0, "passed": 0, "warn": 0, "failed": 0, "skipped": 0}

        for idx, pdf_path in enumerate(pdf_files, 1):
            print(f"[{idx:>3}/{len(pdf_files)}] {pdf_path.name}")
            stats["total"] += 1

            # 自动检测：如果非 light 模式且文件是纯文字，降级提示
            if self.mode in ("medium", "full"):
                is_pure_text = self._detect_pure_text(pdf_path)
                if is_pure_text:
                    print(f"  [INFO] 检测到纯文字PDF，light模式已足够")
                    print(f"         当前模式: {self.mode}，建议用 light 以节省资源")
                    stats["skipped"] += 1
                    continue

            try:
                md_path, qc = self.convert(pdf_path)
                results.append(qc)

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
            "stats": stats,
            "details": results,
        }
        QC_REPORT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    # ═══════════════════════════════════════════════════════
    #  模式：light（双引擎文本提取）
    # ═══════════════════════════════════════════════════════

    def _convert_light(self, pdf_path: Path) -> tuple[Path, dict]:
        """轻量模式：双引擎文本提取 + 交叉验证"""
        title = pdf_path.stem.strip()
        md_filename = sanitize_filename(title) + ".md"
        md_path = OUTPUT_DIR / md_filename

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

        # 保存 Markdown
        md_content = self._pages_to_markdown(title, final_pages)
        md_path.write_text(md_content, encoding="utf-8")

        qc = {
            "file": pdf_path.name,
            "mode": "light",
            "pages": len(final_pages),
            "total_images": sum(image_counts),
            "pl_total_chars": pl_total,
            "fitz_total_chars": fitz_total,
            "final_total_chars": len(md_content),
            "has_error": has_error,
            "has_warn": has_warn,
            "page_qc": page_qc,
        }
        return md_path, qc

    # ═══════════════════════════════════════════════════════
    #  模式：medium（预留接口）
    # ═══════════════════════════════════════════════════════

    def _convert_medium(self, pdf_path: Path) -> tuple[Path, dict]:
        """
        中等模式：文本提取 + 基础视觉检查（图表/表格识别）
        预留接口 — 未来接入 multidoc 文本通道 + 图表/表格还原
        """
        # TODO: 接入 multidoc 的文本通道 + 基础视觉层（Layer 1 + Layer 4 轻量版）
        # 当前降级到 light 并提示
        print(f"  [INFO] medium 模式预留中，当前降级到 light")
        md_path, qc = self._convert_light(pdf_path)
        qc["mode"] = "medium (fallback to light)"
        return md_path, qc

    # ═══════════════════════════════════════════════════════
    #  模式：full（预留接口）
    # ═══════════════════════════════════════════════════════

    def _convert_full(self, pdf_path: Path) -> tuple[Path, dict]:
        """
        完整模式：multidoc 全5层深度分析
        预留接口 — 未来接入 multidoc-transfer-multimodal 技能
        """
        # TODO: 调用 multidoc-transfer-multimodal 技能进行深度分析
        # 当前降级到 light 并提示
        print(f"  [INFO] full 模式预留中，当前降级到 light")
        md_path, qc = self._convert_light(pdf_path)
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
    args = parser.parse_args()

    mode = args.mode
    if args.auto:
        mode = auto_detect_mode(args.input)
        print(f"\n[推荐] 模式: {mode}\n")

    print(f"转换模式: {mode}")
    print(f"输入目录: {args.input}")
    print(f"输出目录: {args.output}\n")

    converter = PdfConverter(mode=mode)
    summary = converter.convert_batch(args.input, args.output)

    print(f"\n{'=' * 50}")
    print("转换完成")
    print(f"{'=' * 50}")
    stats = summary.get("stats", {})
    print(f"总文件数: {stats.get('total', 0)}")
    print(f"通过    : {stats.get('passed', 0)}")
    print(f"警告    : {stats.get('warn', 0)}")
    print(f"失败    : {stats.get('failed', 0)}")
    if stats.get("skipped"):
        print(f"跳过    : {stats['skipped']} (模式过重，建议用 light)")
    print(f"\n质检报告: {QC_REPORT}")


if __name__ == "__main__":
    main()
