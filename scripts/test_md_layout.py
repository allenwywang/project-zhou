#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排版规则回归测试：双份实现一致性 + fail-close 门禁。

用法（AI 会话按 AGENTS.md §7.6 清 PYTHONPATH）：
    cd scripts && env -u PYTHONPATH /usr/bin/python3 test_md_layout.py
退出码 0 = 全通过；1 = 有失败。状态标记一律 ASCII（§7.3）。

覆盖：
 1. project-zhou 与历史学习知识库两份实现的 RULE_VERSION / 输出逐字一致
 2. 黄金样本：物理行 -> 自然段、门禁、字符守恒、硬换行率下降、幂等
 3. 知识库现有已排版文件幂等（证明新规则不会改变存量成果）
 4. 门禁负例：排版被跳过 / 掉字 / 缺 H1 / 连续空行
"""
import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent
ALLEN_PROJECTS = SCRIPTS.parent.parent
KB_SCRIPTS = ALLEN_PROJECTS / "历史学习资料" / "历史学习" / "scripts"
KB_RAW = ALLEN_PROJECTS / "历史学习资料" / "历史学习" / "raw" / "articles" / "茶馆杂谈"

sys.path.insert(0, str(SCRIPTS))
import md_layout

_spec = importlib.util.spec_from_file_location(
    "kb_format", KB_SCRIPTS / "format_chaguan_md.py")
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)

FAILS = []
TOTAL = 0


def check(label, cond, extra=""):
    global TOTAL
    TOTAL += 1
    print("%s %s%s" % ("[OK]" if cond else "[FAIL]", label,
                       (" | " + extra) if extra else ""))
    if not cond:
        FAILS.append(label)


# ── 1. 规则版本一致 ────────────────────────────────────────
check("RULE_VERSION 两侧一致",
      md_layout.RULE_VERSION == kb.RULE_VERSION,
      "pz=%s kb=%s" % (md_layout.RULE_VERSION, kb.RULE_VERSION))

# ── 2. 黄金样本 ────────────────────────────────────────────
GOLDEN = [
    {
        "name": "26.10月-JM1141-秦楚之争（63）.md",
        "raw": """# JM1141 秦楚之争（63）

> 来源：茶馆杂谈系列
> 原文件：26.10月-JM1141-秦楚之争（63）.pdf

---

当然一旦进展到郡县制，一个必然要谈的问题是，如果流官和当地的贵族——很多是
土官，有冲突了咋办？到底听谁的？
最直接的问题是：谁厉害谁兵强马壮听谁的。但你是当地贵族你不一定有国君能打，
但如果所有的贵族反对国君，国君也坐不稳。
秦始皇因为嫪毐之类的因素，不信任宗室，因此直接一竿子插到底搞了几乎全盘的郡
县制，可是陈胜吴广起义之后，你惊奇的发现绝大部分郡县的官员并没有努力效忠，
真真拼死抵抗的，一个章邯不说了，一个是李斯的儿子李由，那换你你也会嘀咕，平
时我用流官还好，但是出事了，你们这帮基于客卿身份、靠拿工资的、权力是我赋予
的人，到底靠得住靠不住呢？

这个问题呢在后世西方经济学家拿出一个说法叫科斯定理，就是产权明晰那一套。但
是你如果按照这个推导下去，那就还是得分封，地盘是你的你才会卖力气嘛，积极性
嘛。你看，这样下去，不就两头堵了吗？
""",
    },
    {
        "name": "21.02月-JM151-刘禅投降事出有因.md",
        "raw": """JM151 刘禅投降事出有因
今天继续讲点圈里能说的吧。
三国里，邓艾偷渡阴平后，刘禅被谯周劝说投降这事情，一直让很多人痛心疾首。
现实是，姜维在剑阁已经把钟会耗到没耐心想撤了，阎宇已经带着江州军星夜驰援，南中还
有霍戈戳着。事实上并没有到不可挽回的地步。
古以来，无寄他国为天子者也，今若入吴，固当臣服。且政理不殊，则
大能吞小，此数之自然也。由此言之，则魏能并吴，吴不能并魏明矣。
""",
    },
    {
        "name": "25.09月-JM945-秦楚之争（15）.md",
        "raw": """# JM945 秦楚之争（15）

> 来源：茶馆杂谈系列

---

先讲结论：秦朝的失败不在制度，而在人事。

我们前文说过，项羽和刘邦在秦制楚制上大方向一致，但细节有偏差。哪怕刘邦做皇帝后还是基于现实，先是封了异性王，后来自己搭上一条命把异性王都干死了还是搞了白马之盟。

所以这个郡县制到最后其实就变成了君权是不是必须神圣不可侵犯这个议题了。
""",
    },
    {
        "name": "19.10月-JM早期文章-时间的玫瑰.md",
        "raw": """时间的玫瑰

> 原文件：19.10月-JM早期文章-时间的玫瑰.pdf（在项目资料库）
> 说明：图片版长截图，OCR 提取，准确率约 90%

周老师的茶

有阵子没聊驴乌了

如今，我说一句还是我先见之明，你们有意见吗 7

谁鞠成 谁反对?         钨 周老师的茶馆

我全网最早说她就是二五姐。出处 : 8月5日的《退场机制》
""",
    },
    {
        "name": "26.08月-JM1108-从冻省展开（31）.md",
        "raw": """# JM1108 从冻省展开（31）

> 来源：茶馆杂谈系列
> 原文件：26.08月-JM1108-从冻省展开（31）.pdf
---

JM1108 从冻省展开（31）
921大地震的细节，大家可以自行百度，反正非常惨烈，上千人罹难。那么一个现实
的问题是，这些年极端气候多了，突发事件多了，老马上台后又搞了六都，城乡不均
衡更严重了，但却缺乏这样一个议事协调机构，于是乎很多事情没人管了。
""",
    },
    {
        # 边界：源 PDF 无文本层时 MD 只有头部，排版无事可做，门禁不得误杀
        "name": "20.10月-JM早期文章-管猫.md",
        "raw": """# 管猫

> 来源：茶馆杂谈系列
> 原文件：管猫.pdf

---
""",
    },
]

for i, case in enumerate(GOLDEN, 1):
    name, raw = case["name"], case["raw"]
    a = md_layout.format_markdown(raw, name)
    b = kb.format_text(raw, name)
    rep = md_layout.verify(raw, a, name)
    check("样本%d 双份输出一致" % i, a == b)
    check("样本%d 门禁通过" % i, rep["ok"], "; ".join(rep["reasons"]))
    check("样本%d 字符守恒" % i, rep["conserved"])
    check("样本%d 硬换行下降或本已达标" % i,
          rep["raw_hard_ratio"] <= 0.25
          or rep["formatted_hard_ratio"] < rep["raw_hard_ratio"],
          "%.2f -> %.2f" % (rep["raw_hard_ratio"], rep["formatted_hard_ratio"]))
    check("样本%d 两侧门禁结论一致" % i,
          rep["ok"] == kb.verify_text(raw, b, name)["ok"])
    check("样本%d 转换器侧幂等" % i, md_layout.format_markdown(a, name) == a)
    check("样本%d 知识库侧幂等" % i, kb.format_text(b, name) == b)

# ── 3. 存量已排版文件幂等 ──────────────────────────────────
EXISTING = [
    "26.10月-JM1141-秦楚之争（63）.md",
    "21.02月-JM151-刘禅投降事出有因.md",
    "25.06月-JM908-能力问题（下）.md",
    "19.10月-JM早期文章-时间的玫瑰.md",
    "20.07月-JM早期文章-陈孔立先生，我来告诉你章念驰错在哪.md",
]
for name in EXISTING:
    p = KB_RAW / name
    if not p.is_file():
        check("存量幂等 " + name[:22], False, "文件不存在")
        continue
    t = p.read_text(encoding="utf-8")
    a = md_layout.format_markdown(t, name)
    b = kb.format_text(t, name)
    check("存量幂等 " + name[:22], a == t and b == t,
          "pz=%s kb=%s" % ("same" if a == t else "DIFF", "same" if b == t else "DIFF"))

# ── 4. 门禁负例 ────────────────────────────────────────────
raw0, name0 = GOLDEN[0]["raw"], GOLDEN[0]["name"]
good = md_layout.format_markdown(raw0, name0)
check("负例 排版被跳过应拒绝", md_layout.verify(raw0, raw0, name0)["ok"] is False)
check("负例 掉字应拒绝",
      md_layout.verify(raw0, good.replace("科斯定理", "科斯"), name0)["conserved"] is False)
check("负例 缺 H1 应拒绝",
      md_layout.verify(raw0, "\n".join(good.split("\n")[1:]), name0)["heading_ok"] is False)
check("负例 连续空行应拒绝",
      md_layout.verify(raw0, good.replace("\n\n", "\n\n\n", 1), name0)["no_double_blank"] is False)
check("负例 知识库侧同样拒绝", kb.verify_text(raw0, raw0, name0)["ok"] is False)
check("负例 两侧门禁结论一致",
      md_layout.verify(raw0, raw0, name0)["ok"] == kb.verify_text(raw0, raw0, name0)["ok"])

print("\n%s 共 %d 项，失败 %d 项" % (
    "[OK] 全部通过" if not FAILS else "[FAIL] 存在失败", TOTAL, len(FAILS)))
if FAILS:
    for f in FAILS:
        print("  [FAIL] " + f)
sys.exit(1 if FAILS else 0)
