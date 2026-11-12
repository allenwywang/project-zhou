---
name: chaguan-sync
description: 茶馆杂谈文件定期同步的标准执行流程（坚果云→蓝奏云→下载→解压→PDF伪装识别→Markdown转换即排版→归档→完整性验证），并对本次新增的 Markdown 做 LLM 语义排版复查。当用户说「同步茶馆」「跑一次同步」「更新茶馆杂谈」「定期同步」「同步下资料库」「检查排版」或要求执行 project-zhou 的 sync.py 流程时使用本 skill。
type: prompt
whenToUse: 用户要执行茶馆杂谈项目的定期同步（新文章下载入库），或要求复查已转换 Markdown 的排版质量。典型触发：「同步一下」「跑同步」「更新资料库」「茶馆杂谈同步」「检查下新文章排版」。
---

# 茶馆杂谈定期同步

本 skill 把「脚本流水线 + LLM 语义排版复查」固化成一条可重复执行的流程。

**项目根目录**：`/Users/allenwywang/allen个人项目/project-zhou`
**唯一事实源**：项目根 `AGENTS.md`（目录、命令、正则红线、调试指引）。本 skill 只描述**执行顺序与判断标准**，冲突时以 AGENTS.md 为准。

## 铁律（违反即本次同步作废）

1. **AI 会话里跑脚本必须清 PYTHONPATH**：
   ```bash
   cd /Users/allenwywang/allen个人项目/project-zhou/scripts
   env -u PYTHONPATH /usr/bin/python3 sync.py
   ```
   宿主的 `sitecustomize.py` 会让 `mkdir` 伪报 `FileExistsError`，且默认 `python3` 缺 playwright/pdfplumber/fitz。（AGENTS.md §7.6）
2. **不要运行任何 `.exe`**。`茶馆杂谈文件同步/` 里的 `.exe` 全是 PDF 伪装，一律先 `read(5) == b"%PDF-"` 判别。（§7.2）
3. **不覆盖已归档的 PDF**。`archive_pdfs()` 是只追加的。（§4.7）
4. **状态标记用 ASCII**（`[OK]`/`[FAIL]`/`[WARN]`），不用 Unicode 符号。（§7.3）
5. **知识库只放 `.md`，PDF 只进项目资料库**。不要往 `MARKDOWN_DIR` 放 PDF。（§4.7）

## 执行流程

### 阶段 0：执行前检查

```bash
cd /Users/allenwywang/allen个人项目/project-zhou
env -u PYTHONPATH /usr/bin/python3 -c "import extract, parse_html, fetch_jianguoyun, download, pdf_to_md, archive_pdfs, naming, audit_dates, sync, md_layout"
```

导入失败说明依赖缺失，先 `pip install playwright pdfplumber PyMuPDF`（Python 3.9 环境）。

**规则漂移检查**（改过 `md_layout.py` 或知识库侧 `format_chaguan_md.py` 时必须跑）：

```bash
cd scripts && env -u PYTHONPATH /usr/bin/python3 test_md_layout.py
```

退出码非 0 → 停止，先修规则漂移。

### 阶段 1：跑同步流水线（9 步）

```bash
cd /Users/allenwywang/allen个人项目/project-zhou/scripts
env -u PYTHONPATH /usr/bin/python3 sync.py            # 从 progress.json 续跑
env -u PYTHONPATH /usr/bin/python3 sync.py --headless # 后台跑
env -u PYTHONPATH /usr/bin/python3 sync.py 0624       # 强制指定起点（补跑用）
```

脚本按顺序完成：抓取坚果云 → 解析条目 → 下载 → 解压 → `.exe` 改名 → PDF→MD（**转换即排版**，内建 fail-close 门禁）→ 归档 PDF → 写 `progress.json` → 完整性验证。

**关注这几处输出**：

| 输出 | 含义 | 若异常 |
|---|---|---|
| `下载完成: 成功 N, 失败 M` | M>0 时进度锚点**不推进**，下次只重试失败条目 | 查蓝奏云分享页；不要手工改 `progress.json` |
| `排版门禁: N 个通过` | N 少于转换成功数 → 有文件排版校验失败**未落盘** | 查日志里的 `[LAYOUT-FAIL]` |
| `完整性验证` 的 `sequence_gaps` | 编号断号 | 补跑缺失条目（见 AGENTS.md §11） |
| `needs_convert` / `missing` | 有 PDF 没 MD / 什么都没有 | 补跑 `pdf_to_md.py --auto` |

### 阶段 2：日期/编号审计

```bash
cd scripts && env -u PYTHONPATH /usr/bin/python3 audit_dates.py
```

退出码非 0 → 有编号/年月倒挂、同编号多份等问题，需处理后再继续。（AGENTS.md §4.7）

### 阶段 3：机械预检（筛选需复查的文件）

```bash
cd /Users/allenwywang/allen个人项目/project-zhou
env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/precheck.py \
    --json-out /tmp/chaguan_precheck.json
```

默认范围 = 本次同步新增的 MD（由 `_qc_report.json` 反查）。退出码 1 表示有待查文件。

**预检只做机械筛选，不做语义判断**，三个信号：

| 信号 | 含义 | 存量库命中率 |
|---|---|---|
| `lead_orphaned` | 段末是引导标点（`：；，、`）且下一段独立 → **引导句可能被孤立** | 127/1241 (10.2%)，共 300 处 |
| `para_too_long` | 单段 > 400 字 → 疑似多段被合并 | 6/1241 (0.5%) |
| `para_dangling` | 单段 < 30 字且末尾非终止标点 → 疑似被切断的残句 | 137/1241 (11.0%) |

**预检只报证据，不下结论**：`lead_orphaned` 同时可能是「引导句被孤立」（真缺陷）
和「引导句 + 列举列表」（作者本来的结构）。列举项不一定以序号开头（可能以人名开头），
机械层面无法可靠区分——**必须由你对照 `src.txt` 与上下文判断**。

阈值是**用已验收的 1241 篇存量库反标定**的（存量库总命中率 10.9%）。
不要随意放宽/收紧——改动前先在存量库上验证误报率。

### 阶段 4：LLM 语义复查

**先读 `${KIMI_SKILL_DIR}/references/layout_review_rubric.md`**——它定义了「排版正确」的标准、四类典型缺陷、修复的机械形态，以及不能动的硬红线。

对每个待查文件：

```bash
env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/export_review.py \
    --name "<MD 文件名>" --out-dir /tmp/chaguan_review
```

导出：
- `md.md` —— 待检对象
- `src.txt` —— 源 PDF 物理行，每行带 `[断]`/`[续]`/`[页末]` 标记，**直接标出排版规则会在哪里断开**
- `para_map.json` —— MD 段落序号 → 源物理行区间
- `meta.json` —— 元信息

**判断必须对照 `src.txt`**：只看排版后的 MD 无法区分「被错误切开」和「本来就是两个短段」。

**修复的机械形态**（做错会导致修复「不稳定」）：
- 合并两段 = **删掉中间空行**，两段文本直接相连（`A：\n\nB。` → `A：B。`）
- 拆分一段 = 在中间**插入空行**

判定与修复：
- 判定是缺陷 → 在 `/tmp/chaguan_review/<stem>/md.fixed.md` 上改（**不要直接改知识库文件**）
- 判定正常 → 不动
- 存疑 → 倾向于不动

### 阶段 5：修复回归门禁

```bash
env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/verify_fix.py \
    --before /tmp/chaguan_review/<stem>/md.md \
    --after  /tmp/chaguan_review/<stem>/md.fixed.md
```

四道门禁，全绿才能落盘：
1. **正文字符守恒** —— 与修复前完全一致（只允许改段落边界，不许改字）
2. **有 H1 / 无连续空行 / 正文非空**
3. **再次排版幂等** —— 重排后不变，说明分段已稳定
4. **无残留占位标记**

任一项失败 → 放弃该篇修复，记录原因，**不要强行落盘**。

全绿后覆盖知识库文件：

```bash
cp /tmp/chaguan_review/<stem>/md.fixed.md \
   "/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/<stem>.md"
```

### 阶段 6：修规则（仅当问题跨多文件同模式复现）

单个文件的怪段落 → 就地修 MD。
**多个文件以同一模式出错** → 那是排版规则的缺陷，需要改规则，且必须：

1. 同步改 `scripts/md_layout.py` **和** `历史学习资料/历史学习/scripts/format_chaguan_md.py`
2. 两边同时 bump `RULE_VERSION`
3. 跑 `scripts/test_md_layout.py`，退出码非 0 不得继续
4. 跑 `.kimi-code/skills/chaguan-sync/scripts/precheck.py --all` 对比存量库命中率，确认没引入新误报

### 阶段 7：收尾报告

向用户报告：本次同步条目数、下载成功/失败、排版门禁通过数、**语义复查发现的问题数与修复数**、日期审计结果、断号情况。

发现的问题如果**属于规则缺陷**，明确指出并给出改规则的建议——这是提升下次同步质量的关键，不要只报告「已修复」。

## 已知陷阱

- **源 PDF 里没有段落信息**。实测：PDF 文本层几乎无空行（0.19%）、无缩进，全是左对齐硬折。
  排版规则完全靠「行尾标点」推断段落。**不要**以为源 PDF 的空行能当段落边界。
- **`：` `；` 在 `TERMINATORS` 里** → 引导句（如「综上所述：」）会被断成悬空独立段落。
  这是最常见的待查形态（存量库 10.2% / 300 处），但**约一成是作者本来的「引导+列举列表」，不是缺陷**。
- **94 篇早期文章无 JM 编号**（`JM早期文章`）→ `convert_batch` 的「按 JM 编号跳过已存在」对它们**不生效**，每次同步都会被重转**覆盖**，人工修复会被抹掉。复查发现某篇早期文章被覆盖，要说明这一点。
- **知识库 MD 里的姓名已替换为占位符**（如 `{{PERSON_xxxx}}`），源 PDF 里是**原文姓名**——**不要**把 PDF 文本写回 MD，只用 MD 自身字符序列做守恒基线。
- **部分早期文章是图片版**（无文本层），MD 来自历史 OCR 批处理。此时 `src.txt` 会写明「无可用源物理行」，判据更弱，存疑时倾向于不动。
- **`_qc_report.json` 记的是 PDF 原名**，MD 用的是新命名（`YY.MM月-JMxxx-标题`），脚本已按 JM 编号回查。
- **进度锚点**：下载失败时 `last_sync_date` 不推进，只累计 `total_downloaded` 并在 `history[]` 追加带 `note` 的记录。`history[]` 的**字段名固定**，不要增删。（§4.2、§9）
- **外置盘备份是手动步骤**，不挂载就报错退出，不要自动创建目录，不要挂定时任务。（§4.8）

## 配套参考

- `${KIMI_SKILL_DIR}/references/layout_review_rubric.md` —— 排版语义复查准则（四类缺陷 + 硬红线 + 判定速查表）
- `${KIMI_SKILL_DIR}/references/troubleshooting.md` —— 常见故障与定位
- 项目 `AGENTS.md` —— 目录结构、命令清单、修改红线、调试指引
