"""茶馆杂谈日期/编号一致性审计（只读，可随时跑）。

检查项：
  1. 编号顺序 vs 年月顺序：编号递增时年月不得倒退（以编号为第一优先级）
  2. 同编号多份：同一 JM 编号存在多个不同文件名
  3. 与坚果云条目日期不一致（覆盖 JM236 起的区间）
  4. 正文内嵌 ``JMxxx`` 与文件名编号不一致
  5. 早期文章（无编号）月份越界

用法：
    cd scripts && env -u PYTHONPATH /usr/bin/python3 audit_dates.py
    python3 audit_dates.py --kb /path/to/茶馆杂谈
退出码：0 全通过；1 有问题。
"""
import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import naming as N
import sync

DEFAULT_KB = sync.MARKDOWN_DIR
EMBED_RE = re.compile(r"^\s*JM\s*0*(\d+)\b", re.M)


def mi(y, m):
    return y * 12 + (m - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=str(DEFAULT_KB))
    ap.add_argument("--page", default=str(sync.PROJECT_ROOT / "data" / "jianguoyun_page.html"))
    args = ap.parse_args()

    kb = Path(args.kb)
    if not kb.is_dir():
        print(f"[FAIL] 知识库目录不存在: {kb}")
        return 1

    files = [p for p in kb.iterdir() if p.is_file() and p.suffix in (".md", ".pdf")]
    numbered, early, legacy = collections.defaultdict(list), [], []
    for p in files:
        if not N.is_new_style(p.stem):
            legacy.append(p)
            continue
        d = N.parse_legacy(p.stem)
        if d["jm_num"] is None:
            early.append((p, d["year"], d["month"]))
        else:
            numbered[d["jm_num"]].append((p, d["year"], d["month"]))

    problems = 0
    print(f"知识库: {kb}")
    print(f"文件 {len(files)} | 有编号 {sum(len(v) for v in numbered.values())} | "
          f"早期文章 {len(early)} | 非新格式 {len(legacy)}")

    # 1) 单调性
    rows = []
    for n, g in numbered.items():
        for p, y, m in g:
            rows.append((n, y, m, p.name))
    rows.sort()
    inv = [(rows[i - 1], rows[i]) for i in range(1, len(rows))
           if mi(rows[i][1], rows[i][2]) < mi(rows[i - 1][1], rows[i - 1][2])]
    print(f"\n[1] 编号顺序 vs 年月顺序: {'PASS' if not inv else f'FAIL {len(inv)} 处'}")
    for a, b in inv[:10]:
        print(f"    JM{a[0]} {a[1]}-{a[2]:02d} > JM{b[0]} {b[1]}-{b[2]:02d}  ({a[3][:30]})")
    problems += len(inv)

    # 2) 同编号多份（不同 stem）
    dup = {n: sorted({p.stem for p, _, _ in g}) for n, g in numbered.items() if len({p.stem for p, _, _ in g}) > 1}
    print(f"\n[2] 同编号多份: {'PASS' if not dup else f'{len(dup)} 个编号'}")
    for n, stems in list(dup.items())[:10]:
        print(f"    JM{n}: {stems}")
    problems += len(dup)

    # 3) 与坚果云不一致
    page = Path(args.page)
    if page.exists():
        entries = sync.parse_all_entries_from_html(page)
        dates = sync.build_entry_dates(entries)
        truth = {}
        for i, e in enumerate(entries):
            n = N.extract_jm_num(e["name"])
            d = dates.get(i)
            if n is not None and d and n not in truth:
                truth[n] = d[:2]
        bad = []
        for n, g in numbered.items():
            if n not in truth:
                continue
            ym = {(y, m) for _, y, m in g}
            if len(ym) == 1 and ym.pop() != truth[n]:
                bad.append((n, truth[n], g[0][1], g[0][2]))
        print(f"\n[3] 与坚果云条目日期一致: {'PASS' if not bad else f'{len(bad)} 处不符'}")
        for n, t, y, m in bad[:10]:
            print(f"    JM{n}: 命名 {y}-{m:02d} / 坚果云 {t[0]}-{t[1]:02d}")
        problems += len(bad)
    else:
        print("\n[3] 跳过：无坚果云页面存档")

    # 4) 正文内嵌编号
    mism = []
    for p in files:
        if p.suffix != ".md":
            continue
        n = N.extract_jm_num(p.stem)
        if n is None:
            continue
        m = EMBED_RE.search(p.read_text(encoding="utf-8", errors="replace")[:300])
        if m and int(m.group(1)) != n:
            mism.append((p.name, int(m.group(1)), n))
    print(f"\n[4] 正文编号 vs 文件名编号: {'PASS' if not mism else f'{len(mism)} 处笔误'}")
    for name, inner, outer in mism[:10]:
        print(f"    文件 JM{outer} / 正文 JM{inner}: {name[:46]}")
    problems += len(mism)

    # 5) 早期文章月份
    bad_early = [(p.name, y, m) for p, y, m in early if not (2018 <= y <= 2027 and 1 <= m <= 12)]
    print(f"\n[5] 早期文章月份合法: {'PASS' if not bad_early else f'FAIL {len(bad_early)}'}")
    for x in bad_early[:5]:
        print("    ", x)
    problems += len(bad_early)

    if legacy:
        print(f"\n[注] 非新格式文件 {len(legacy)} 个（需人工确认）:")
        for p in legacy[:8]:
            print("    ", p.name)

    print(f"\n=== 合计问题 {problems} 项 ===")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
