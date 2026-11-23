#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排版机械预检：把「需要 LLM 语义判断」的候选文件筛出来。

用途
----
`md_layout.py` 的门禁只验证「字符守恒 / 有 H1 / 无三连空行 / 物理行不得原样输出」
这四条**机械**性质。段落切得对不对、语义是否被割裂，脚本判不了。
本脚本在机械层面把明显有问题的文件筛出来，缩小 agent 需要逐篇读的范围。

阈值标定（重要）
----------------
阈值不是拍脑袋定的，而是用**已验收的存量库**（1241 篇 2026-11-12 全量排版成果）
反标定出来的：任何在存量库上大量触发的规则，都是误报，必须调宽或删除。
存量库统计口径：
    段落数 26163 / 文件 1241
    段落长度  p50=51  p75=81  p90=118  p95=145  p99=204  max=726
    末尾无终止标点的段落 368 段 (1.41%)
    超过 300 字的段落 25 段 (2.0% 文件)；超过 400 字 6 段 (0.5% 文件)
    段内出现「。+汉字」的段落：99.8% 文件命中 → 完全是中文常态，**不可用作信号**
    H1 与文件名推导标题不一致 42 篇 (3.4%) → 全是 JM06/JM6、日期后缀等良性差异，**不可用作信号**

主信号（真正会害的缺陷）：**引导句被孤立成半句**。
排版规则把行尾有终止标点的行断开，而「：」「；」都在 TERMINATORS 里，于是
「综上所述：」这种引导句会被截断成一个独立段落，正文另起一段——读者看到的是
一个悬空的冒号。这是最典型、也最容易被 LLM 判定并修复的排版错误。

辅助信号：超长段（疑似多段被合并）、无终止标点的短段（疑似被切断的残句）。

判定项
------
  1. lead_orphaned    段末是引导标点（：；，、）且下一段存在 → 引导句被孤立，疑似半句断段
  2. para_too_long    单段超过 --max-para-chars（默认 400）→ 疑似多个自然段被合并成一坨
  3. para_dangling    单段长度 < --min-para-chars（默认 30）且末尾非终止标点 → 疑似被切断的残句
  4. structure        缺 H1 / 三连空行 / 空正文（与 md_layout 门禁对齐）

用法
----
    cd /Users/allenwywang/allen个人项目/project-zhou
    env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/precheck.py
    env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/precheck.py \
        --names "26.10月-JM1141-xxx.md,26.10月-JM1142-yyy.md"

默认范围：**本次同步新增的 MD**（由 _qc_report.json 的本次转换产物反查）。
--all 强制全库扫描（用于存量体检）。

输出
----
- 人类可读检查报告（stdout）
- --json-out <路径>：JSON 清单，供 agent 消费

退出码
------
0 = 没有待查文件
1 = 有待查文件（需 agent 语义复查）
2 = 参数/环境错误
"""
import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import md_layout  # noqa: E402  排版规则唯一事实源
import naming    # noqa: E402

HISTORY_KB_ROOT = PROJECT_ROOT.parent / "历史学习资料"
MARKDOWN_DIR = HISTORY_KB_ROOT / "历史学习" / "raw" / "articles" / "茶馆杂谈"
# 蓝奏云管线产出的 MD 与质检报告都在 JM系列/ 子目录（2026-11-18 起）；
# 父目录那份是历史遗留的旧档，不能当本次转换清单用。
JM_MD_DIR = MARKDOWN_DIR / "JM系列"
QC_REPORT = JM_MD_DIR / "_qc_report.json"

TERMINATORS = md_layout.TERMINATORS
META_RE = md_layout.META_RE

# 默认阈值（标定值，见模块 docstring）
DEFAULT_MAX_PARA = 400
DEFAULT_MIN_PARA = 30

# 引导标点：出现在段末时，说明该段是「引导句」，后面本该紧跟正文。
# 排版规则会把它们当终止标点断开，导致引导句被孤立（悬空冒号）。
LEAD_MARKS = set("：:；;，,、")

# 列举项特征：段首是序号（1. / 一、 / 第一）或「数字+单位」式列举
LIST_HEAD_RE = re.compile(r"^[0-9０-９]+[、.．)）]|^[一二三四五六七八九十]+[、.．]|^第[0-9一二三四五六七八九十]+[个位条项]")


def body_paragraphs(text):
    """提取正文段落：剔除 H1/标题/分隔线/元数据引用行。"""
    out = []
    for raw in text.split("\n"):
        s = raw.strip()
        if not s or s == "---":
            continue
        if s.startswith("# "):
            continue
        if s.startswith("## "):
            s = s[3:]
        elif s.startswith("### "):
            s = s[4:]
        if s.startswith("> "):
            body = s[2:]
            # 元数据行（> 来源 / > 原文件 / > 说明 …）不是正文段落
            if META_RE.match(s):
                continue
            s = body
        out.append(s)
    return out


def resolve_scope(md_dir, names):
    """确定待查文件范围。"""
    if names:
        found = [md_dir / n for n in names if (md_dir / n).is_file()]
        missing = [n for n in names if not (md_dir / n).is_file()]
        if missing:
            print("[WARN] 指定文件不存在: %s" % ", ".join(missing))
        return found, "显式指定"

    if QC_REPORT.is_file():
        try:
            qc = json.loads(QC_REPORT.read_text(encoding="utf-8"))
            files = []
            for d in qc.get("details", []):
                f = d.get("file")
                if not f:
                    continue
                cand = md_dir / (Path(f).stem + ".md")
                if cand.is_file():
                    files.append(cand)
                    continue
                num = naming.extract_jm_num(f)
                if num is None:
                    continue
                for p in md_dir.glob("*.md"):
                    if naming.extract_jm_num(p.stem) == num:
                        files.append(p)
                        break
            if files:
                return files, "_qc_report.json 本次转换产物"
        except Exception as e:
            print("[WARN] 读 _qc_report.json 失败: %s" % e)

    return sorted(md_dir.glob("*.md")), "全库扫描（未找到本次转换清单）"


def analyze(path, max_para=DEFAULT_MAX_PARA, min_para=DEFAULT_MIN_PARA):
    """对单个 MD 文件做机械预检，返回 findings 列表 [(类别, 代码, 说明)]。"""
    findings = []
    text = path.read_text(encoding="utf-8")

    if not text.startswith("# "):
        findings.append(("structure", "missing_h1", "缺少 H1 标题"))
    if "\n\n\n" in text:
        findings.append(("structure", "triple_blank", "存在连续空行"))

    paras = body_paragraphs(text)
    if not paras:
        findings.append(("structure", "empty_body", "正文为空（可能是纯图片 PDF）"))

    for idx, p in enumerate(paras, 1):
        if len(p) > max_para:
            findings.append(("segmentation", "para_too_long",
                             "第%d段超长(%d字>%d)，疑似多个自然段被合并成一段：%s…"
                             % (idx, len(p), max_para, p[:40])))
        if p and len(p) < min_para and p[-1] not in TERMINATORS:
            findings.append(("segmentation", "para_dangling",
                             "第%d段仅%d字且末尾无终止标点(%s)，疑似被切断的残句：%s"
                             % (idx, len(p), p[-1], p)))
        # 引导句被孤立：段末是引导标点，但下一段已经另起。
        # 排除「引导句后接列举项」——那是作者本来的结构（总—分列表），
        # 不是排版错误。存量库实测：299 处引导句中仅 10 处属于列举项。
        if idx < len(paras) and p and p[-1] in LEAD_MARKS:
            nxt = paras[idx]
        # 引导句被孤立：段末是引导标点，但下一段已经另起。
        # 这里只报「证据」，不下「结论」——是缺陷还是作者本来的总—分结构，
        # 必须由 LLM 对照 src.txt 判断。存量库实测：300 处引导句里，
        # 既有「引导句 + 正文」（真缺陷），也有「引导句 + 列举列表」（正常结构），
        # 两者在机械层面无法可靠区分（列表项可能以人名开头，不带序号）。
        if idx < len(paras) and p and p[-1] in LEAD_MARKS:
            nxt = paras[idx]
            kind = "列举项" if LIST_HEAD_RE.match(nxt) else "普通段落"
            run = []
            j = idx
            while j < len(paras) and len(paras[j]) <= 40:
                run.append(paras[j])
                j += 1
            consistent = (len(run) > 1 and
                          max(len(x) for x in run) - min(len(x) for x in run) <= 12)
            findings.append(("segmentation", "lead_orphaned",
                             "第%d段以引导标点「%s」结尾却被断成独立段；下一段是%s"
                             "（后连续 %d 段较短，形态%s）→ 需对照 src.txt 判断是"
                             "「引导句被孤立」还是「总—分列表」：%s"
                             % (idx, p[-1], kind, len(run),
                                "高度一致" if consistent else "分散",
                                p[-40:])))

    return findings


def main():
    ap = argparse.ArgumentParser(description="茶馆杂谈 MD 排版机械预检")
    ap.add_argument("--md-dir", default=str(JM_MD_DIR), help="知识库茶馆杂谈 JM系列 MD 目录")
    ap.add_argument("--names", default="", help="逗号分隔的 MD 文件名（显式指定范围）")
    ap.add_argument("--max-para-chars", type=int, default=DEFAULT_MAX_PARA,
                    help="单段长度上限（默认 400）")
    ap.add_argument("--min-para-chars", type=int, default=DEFAULT_MIN_PARA,
                    help="单段长度下限（默认 30）")
    ap.add_argument("--json-out", default="", help="JSON 清单输出路径")
    ap.add_argument("--all", action="store_true", help="强制全库扫描")
    args = ap.parse_args()

    md_dir = Path(args.md_dir)
    if not md_dir.is_dir():
        print("[FAIL] MD 目录不存在: %s" % md_dir)
        return 2

    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if args.all:
        files = sorted(md_dir.glob("*.md"))
        scope = "全库扫描（--all 强制）"
    else:
        files, scope = resolve_scope(md_dir, names)

    if not files:
        print("[INFO] 没有待查文件")
        return 0

    print("=" * 60)
    print("排版机械预检")
    print("=" * 60)
    print("范围来源: %s" % scope)
    print("文件数  : %d" % len(files))
    print("规则版本: %s" % md_layout.RULE_VERSION)
    print("阈值    : 段长>%d 报警 / 段长<%d 且无终止标点 报警"
          % (args.max_para_chars, args.min_para_chars))
    print()

    flagged = []
    for p in files:
        try:
            findings = analyze(p, args.max_para_chars, args.min_para_chars)
        except Exception as e:
            findings = [("error", "read_fail", str(e))]
        if findings:
            flagged.append({"file": p.name, "path": str(p), "findings": findings})

    if not flagged:
        print("[OK] %d 个文件全部通过机械检查，无需语义复查" % len(files))
    else:
        print("[WARN] %d/%d 个文件需要语义复查：" % (len(flagged), len(files)))
        for item in flagged:
            print()
            print("--- %s" % item["file"])
            for cat, code, msg in item["findings"]:
                print("    [%s/%s] %s" % (cat, code, msg))

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "scope": scope,
            "rule_version": md_layout.RULE_VERSION,
            "thresholds": {"max_para_chars": args.max_para_chars,
                           "min_para_chars": args.min_para_chars},
            "checked": len(files),
            "flagged": flagged,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print("JSON 清单: %s" % out)

    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
