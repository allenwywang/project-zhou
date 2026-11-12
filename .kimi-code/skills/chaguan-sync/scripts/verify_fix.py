#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复后的回归门禁：确认 agent 对 MD 的语义修复没有破坏排版不变量。

要守住的四条不变量（缺一不可）：
  1. char_conserved  正文字符序列与修复前**完全一致**（只允许增删空行/段落边界，
                      绝不允许改字、漏字、换字——这是知识库的第一红线）
  2. layout_ok       md_layout 自身的门禁通过（字符守恒 / 有 H1 / 无三连空行 /
                      物理行不得原样输出）
  3. idempotent      再次排版结果不变（说明分段已稳定，不会来回抖动）
  4. no_todo         不残留未处理的占位标记

用法
----
    cd /Users/allenwywang/allen个人项目/project-zhou
    env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/verify_fix.py \
        --before /tmp/chaguan_review/<stem>/md.md \
        --after  /tmp/chaguan_review/<stem>/md.fixed.md

退出码：0 = 全部通过；1 = 有失败项。
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import md_layout  # noqa: E402

FAILS = []


def check(label, cond, extra=""):
    print("%s %s%s" % ("[OK]" if cond else "[FAIL]", label,
                       (" | " + extra) if extra else ""))
    if not cond:
        FAILS.append(label)


def main():
    ap = argparse.ArgumentParser(description="排版修复回归门禁")
    ap.add_argument("--before", required=True, help="修复前的 MD")
    ap.add_argument("--after", required=True, help="修复后的 MD")
    args = ap.parse_args()

    before_p, after_p = Path(args.before), Path(args.after)
    if not before_p.is_file():
        print("[FAIL] 修复前文件不存在: %s" % before_p)
        return 2
    if not after_p.is_file():
        print("[FAIL] 修复后文件不存在: %s" % after_p)
        return 2

    before = before_p.read_text(encoding="utf-8")
    after = after_p.read_text(encoding="utf-8")
    name = after_p.name

    # 1. 字符守恒
    b_chars = md_layout.body_chars(before)
    a_chars = md_layout.body_chars(after)
    check("正文字符守恒", b_chars == a_chars,
          "before=%d after=%d" % (len(b_chars), len(a_chars)))
    if b_chars != a_chars:
        # 定位首个差异字符，便于排查
        for i, (x, y) in enumerate(zip(b_chars, a_chars)):
            if x != y:
                check("首个差异字符位置", False,
                      "index=%d before=%r after=%r" % (i, b_chars[i:i+20], a_chars[i:i+20]))
                break
        else:
            check("字符序列长度差异", False,
                  "长度不同 before=%d after=%d" % (len(b_chars), len(a_chars)))

    # 2. 结构检查（针对「已排版」文本）
    #    注意：不能用 md_layout.verify(before, after)——那条断言的前提是
    #    before 是 PDF 物理行、after 是排版结果。这里 before/after 都是已排版文本，
    #    正确判据是「after 自身结构合法 + 再排版不变（幂等）」。
    check("有 H1 标题", after.startswith("# "))
    check("无连续空行", "\n\n\n" not in after)
    check("正文非空", len(a_chars) > 0, "正文字符=%d" % len(a_chars))

    # 3. 幂等：再排版一次必须完全不变（说明分段已稳定，不会来回抖动）
    again = md_layout.format_markdown(after, name)
    check("再次排版幂等", again == after,
          "" if again == after else "重排后内容会变化，分段未稳定")

    # 4. 无残留占位
    leftovers = [t for t in ("TODO", "FIXME", "XXX", "待复查", "待确认")
                 if t in after]
    check("无残留占位标记", not leftovers, ", ".join(leftovers))

    # 段落统计（给人看）
    b_paras = sum(1 for l in before.split("\n")
                  if l.strip() and not l.startswith(("#", ">", "---")))
    a_paras = sum(1 for l in after.split("\n")
                  if l.strip() and not l.startswith(("#", ">", "---")))
    print()
    print("段落数: %d -> %d" % (b_paras, a_paras))

    if FAILS:
        print("\n[FAIL] %d 项未通过" % len(FAILS))
        for f in FAILS:
            print("  [FAIL] " + f)
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
