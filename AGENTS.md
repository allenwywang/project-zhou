# AGENTS.md — 茶馆杂谈文件同步项目

本文件为 AI 编程代理提供项目背景知识，读者对项目一无所知。**事实以代码为准**，本文须与代码现状同步。

> **体量预算**：Codex 项目指令链按 32KiB 合并截断（本文件 26.9KB + 全局 `~/.codex/AGENTS.md` 5.1KB ≈ 32.0KB，余量 <1KB）。**新增内容前先删等量的旧内容**，否则末尾 §9 红线会被静默截断。

---

## 1. 项目概述

**目的**：从坚果云（Jianguoyun）共享页读取蓝奏云（Lanzou Cloud）下载参数，批量下载 → 解压 → PDF 伪装识别 → 转 Markdown → 归档。约每半月人工触发一次，服务于个人历史学习资料整理。

**核心痛点**（决定了很多看似"怪异"的设计）：
- 蓝奏云下载 PDF 时把扩展名伪装成 `.exe`（文件头实际是 `%PDF-`），以绕过安全扫描。
- 坚果云对同一 IP 累计 3 次密码错误就封禁 30 分钟～数小时。
- 源页下载参数分三列（JM / python / WP），同一日期在多列重复，最新条目永远在最后一列。

**运行环境**：硬编码 macOS 路径，仅在本机 `/Users/allenwywang/...` 下工作。隐含前提：`chrome` 通道、Homebrew `7z`、本机**只有 `python3`**（没有 `python` 命令）。

---

## 2. 目录与文件清单

```
project-zhou/
├── .claude/CLAUDE.md           # Claude 入口指针，不承载事实；冲突以本文为准
├── scripts/
│   ├── sync.py                 # 【主推】一键主控，跑完 9 步
│   ├── pdf_to_md.py            # PDF → Markdown（light/medium/full）+ 内建排版门禁（§4.5）
│   ├── md_layout.py            # 排版规则纯函数（转换器侧实现，§4.5）
│   ├── test_md_layout.py       # 排版回归测试：双份一致性 + fail-close 门禁（§6）
│   ├── naming.py               # JM 命名唯一事实源（§4.7）
│   ├── audit_dates.py          # 日期/编号审计（同步后跑，非 0 退出需处理）
│   ├── archive_pdfs.py         # PDF 归档：只进资料库（§4.7）
│   ├── backup_to_external.py   # 资料库 → 外置盘增量备份，手动（§4.8）
│   ├── wechat_client_fetch.py / mp_req_logger.py   # 公众号管线（skill doc-ingest）：凭据捕获/列表
│   ├── wechat_archive.py / trim_promo_tail.py / final_report.py / dedup_against_kb.py  # 公众号正文抓取/引流清洗/对账
│   └── 归档 skill：~/.claude/skills/doc-ingest/（核心技能，统管两管线；详见其 SKILL.md）
│   ├── fetch_jianguoyun.py     # 抓页旧版（密码硬编码 0403，与现役不符）
│   ├── parse_html.py / download.py / extract.py   # 解析/下载/解压旧版，分步调试用
├── data/jianguoyun_page.html   # 坚果云页快照（运行时生成，gitignore）
├── assets/jianguoyun.png       # 抓取时的全页截图（gitignore）
├── progress.json               # 同步进度（唯一状态源）
├── 茶馆杂谈文件同步/            # 下载产物（gitignore）：*.pdf / *.exe / *.zip / <uuid>
└── 周老师茶馆历史文档/          # 【项目资料库】PDF 分类归档目标（§4.7）；671MB 且是唯一副本，gitignore 不入仓
```

**对外输出**（不在仓库内）：
- Markdown + `_qc_report.json` → `/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/JM系列/`（常量 `MARKDOWN_DIR`；2026-11-18 起独立子目录，与「公众号直采/」平行）。**只放 `.md` 不放 PDF**，**只收 JM 系列**（python/外篇/WP 只归档资料库），文件名 `YY.MM月-JMxxx-标题`（§4.7）。
- PDF 归档副本 → 仓库内 `周老师茶馆历史文档/`；外置盘备份 → `/Volumes/My PSSD/文档资料/project-zhou`（对应资料库根目录，**不是仓库镜像**，§4.8）。

**依赖**：无 `pyproject.toml` / `requirements.txt`，靠脚本 `import` 自描述：`playwright`（配本机 Chrome）、`pdfplumber`、`PyMuPDF`（`fitz`）、`7z`（Homebrew `p7zip`）。

---

## 3. 运行时架构

```
坚果云 (jianguoyun.com) ─登录页─▶ HTML 快照 ─解析▶ 条目列表
                                                      │
蓝奏云 (lanzoui.com)  ◀─逐条 Playwright 下载──────────┘
      ▼
本地 DOWNLOAD_DIR (茶馆杂谈文件同步/)
      ├─ extract_archives()  ──7-zip──▶ 子文件落同目录
      ├─ rename_exe_to_pdf() ─读头 magic──▶ .exe → .pdf
      ├─ PdfConverter.convert_batch() ─pdfplumber + fitz─▶ MARKDOWN_DIR/JM系列 (*.md, 仅 JM)
      └─ archive_pdfs() ─copy2─▶ 周老师茶馆历史文档/（按发布年入年度目录，新命名，增量）
                          【单目的地：知识库不收 PDF】
```

---

## 4. 关键约定（修改前必读）

### 4.1 条目行格式

所有输入源（坚果云 HTML、本地 txt）同一种文本格式：
```
<4位日期>更新：<名称>：<file_id>[  密码：<pwd>]
```
例：`0526更新：JM1066 从冻省展开（1）：iW1o63qioede  密码：1066`

- file_id 字符类**包含 `/`**：坚果云 HTML 偶发在 file_id 前加脏字符 `/`，解析后 `lstrip('/')` 清理，前缀再容错 `\/?`。
- **名称可以含半角冒号**（如 `JM:1074`）：正则用贪婪 `.+` + 行尾 `$` 锚定 + MULTILINE，配合 file_id 必须以 `i` 开头且 ≥9 字符，让引擎停在正确的 file_id 上。
- 起点过滤用 `>=`（**不是** `>`）：`find_last_date_line()` 取该日期在所有出现中**行号最大**的那一个作为起点，保证"上一日当天最右列"那条不漏。

### 4.2 进度锚点（同步状态机）

`progress.json` 是唯一的同步状态：`last_sync_date`（4 位月日，下次同步的左边界）、`last_sync_full_date`、`last_sync_range`、`last_sync_count`、`total_downloaded`、`history[]`（字段固定，下游人工复盘依赖）。
**首次运行**必须由用户输入初始 `last_date`（如 `0624`），之后 `sync.py` 自动接管。

**下载失败不推进锚点**（2026-11-12）：`dl_failed > 0` 时 `last_sync_date` / `last_sync_full_date` / `last_sync_range` / `last_sync_count` 保持原值，只累计 `total_downloaded`，并在 `history[]` 追加一条带 `note` 的记录（字段名不变）。下次运行由 §4.6 预检只重试失败条目。

### 4.3 密码边界

- 坚果云页密码：`psw0528`（`sync.py` 顶部 `PASSWORD`）。**最多重试 3 次**（`MAX_PWD_ATTEMPTS = 3`），超过就 `raise` 停下来等用户介入，避免触发 IP 封禁延长。
- 蓝奏云分享页密码：从条目里解析，按条目传给对应下载请求。
- 压缩包密码：**文件名中的所有数字拼接**（如 `JM1056.zip` → `1056`）。逻辑在 `extract_password()`。

### 4.4 `.exe` 伪装 PDF 检测

文件头前 5 字节 == `b"%PDF-"` → 重命名为 `.pdf`（`rename_exe_to_pdf()`）；已存在同名 `.pdf` 时**跳过不覆盖**。

检查必须用 Python **`f.read(5)`**（`with open(f, "rb") as fh: fh.read(5)`，按需读入内存），**不要用 `head -c 5` 命令替代**；碰到 `.exe` 一律先这样判别，**绝不执行**（见 §7.2）。

### 4.5 文件名与 Markdown 头

- 输出 MD 文件名：**优先用 `namer(pdf_stem)` 的结果**（`YY.MM月-JMxxx-标题`，见 §4.7）；无 namer 或返回 None 时退回 `re.sub(r'[\\/:*?"<>|]', '', pdf_stem)` 的原名清理。
- MD 文件头固定（`<title>` = PDF stem，即新命名后的 stem）：
```
# <title>

> 来源：茶馆杂谈系列
> 原文件：<title>.pdf

---
```

**正文排版（2026-11-12 起，转换即排版）**：
- 规则在 `scripts/md_layout.py`（`format_markdown` / `verify` / `layout`）：行尾无终止标点则与下一行拼接，有终止标点则断段；空行密集（OCR/已排版型）时原空行即段落边界。
- `pdf_to_md.py::_convert_light` 在 `write_text()` **之前**调 `md_layout.layout()`。门禁四项（字符守恒 / 有 H1 / 无三连空行 / 物理行不得原样输出）**失败抛 `[LAYOUT-FAIL]` 不落盘**（fail-close）。
- 知识库侧另有 `scripts/format_chaguan_md.py`，两份规则由 `test_md_layout.py` 逐例比对，`RULE_VERSION` 必须一致；**改规则两侧同步 + bump 版本号**。
- `--no-format` 仅供诊断。增强标记（`##` / `>`）是人工语义判断，不纳入自动转换；无 JM 编号的早期文章每次同步会被重转覆盖（详见 §5.5）。
- **语义层面的复查判据（六类缺陷 / 硬红线 / 判定速查表）见 §5.5 指向的 skill**。

### 4.6 下载预检

`download_entries()` 先做 `[SKIP]` 存在性预检：复用 `_file_matches_short_id()` 短 ID 表匹配 `DOWNLOAD_DIR` 里已有的 `.pdf` / `.exe` / `.zip`，产物已存在的条目直接跳过、**不再启动浏览器**。这是边界日不重复下载的保障，不要绕过。

**下载实现**（2026-11-12）：单次点击 + context 级 `download` 监听（`context.on("page", ...)` 覆盖点击后打开的蓝奏云中转新页面），用 `page.wait_for_timeout()` 泵事件循环等待，事件到达即 `save_as`。**不要**恢复「原 page `expect_download` 空等 60s + 二次点击」的旧写法（对中转页链接必然失败，`Target page ... closed`），也**不要**用 `time.sleep` 等事件——Playwright 同步 API 只在调用其方法时泵事件，`time.sleep` 期间事件不投递，会产生「事件到了但文件没落盘」的假阳性。

### 4.7 存档分工：知识库只放 MD，PDF 只进资料库

`archive_pdfs(namer=None)` 把 `茶馆杂谈文件同步/*.pdf` 增量归档到项目资料库。**知识库 `MARKDOWN_DIR`（茶馆杂谈/JM系列/）只放 `.md`**（`pdf_to_md` 写），**不收 PDF**（2026-11-12 规则，此前并排的 94 个 PDF 已清空）。两侧同 stem 对应：`xx.md`（知识库）↔ `xx.pdf`（资料库）。命名由 `scripts/naming.py` 生成，`sync.py` 按条目日期传 `namer`。

**项目资料库 `周老师茶馆历史文档/`（PDF 唯一归属地）**：
- `JM\d...` → `历史学习资料-YYYY/`，**YYYY = 发布年**（由新命名 `YY.MM月-` 推出，不是当前年）；**`<=2020` 统一进 `历史学习资料-2020及以前`**。文件名与知识库**完全一致**（2026-11-12 起两侧同名，改名前资料库是 `JM273 你明知内涵但也不好办.pdf` 这类老格式）
- `python学习材料\d...` / `ptyhon学习材料\d...`（蓝奏云误拼变体）/ `外篇\d...` / `WP\d...` → `Python学习材料/`（沿用原名）
- 其他未识别前缀**不擅自分类**：仅做外部归档，并输出 `[WARN]` 等人工确认
- 判重按 **JM 编号跨全部年度目录**扫描，改日期换目录后不会重复入库

**JM 命名规则（`scripts/naming.py`，唯一事实源）**：
- 有编号：`YY.MM月-JM<编号>-<文章名>`，例 `25.07月-JM918-我们就是聪明一些`
- 无编号（早期文章）：`YY.MM月-JM早期文章-<文章名>`，例 `18.06月-JM早期文章-欢迎回家20210925`
- 编号不补零（`JM66` 而非 `JM066`）；标题保留原文，仅清文件系统非法字符
- `_file_matches_short_id()` 同时兼容下载原名 `JM1140 xxx` 与知识库新名 `26.10月-JM1140-xxx`
- 知识库双链由 Obsidian 自动维护（重命名走 `obsidian rename`）；`audit_lint.parse_tea_filename` 已兼容新旧两种文件名

**年月怎么定（`YY.MM`）**——**JM 编号顺序第一优先**，任何日期来源都不得让编号递增时年月倒退：

1. **坚果云条目日期**（首选）：`index` 的 `MMDD更新`。页面是**跨 5 年累计清单**，年份必须由 `build_entry_dates()` 从**最新一条倒推**，禁止「当前年 + 条目月份」直接拼（历史上因此把 JM1 推成 2021-01）。
2. **原批次年月**：仅当该批编号集中（剔除「迟到归档」——编号远离批次中位数的单条）。**`2021年01月_` 那 137 条是批量归档日，永不采信**。
3. **缺口按编号线性插值**，再全局强制单调。
4. **PDF `creationDate` 最不可靠**（是导出日），仅无其它来源时兜底。
5. **献词类特例**：新年献词记 `YY.12月`（标题年份是次年，`25.12月-…-2026年新年献词` 归 `历史学习资料-2025`）；春节贺词记春节所在月（2020 春节 1/25 → `20.01月`），文件名用「春节贺词」。

`scripts/audit_dates.py` 是这条规则的守门脚本：检查编号/年月倒挂、同编号多份、与坚果云不符、正文内嵌编号笔误。**同步后应跑一次，退出码非 0 即需处理**。注意「同编号、不同标题」= 两篇不同文章（如 JM143 别做投枪 / JM146 愚公移山），**不是重复**；只有同编号且正文逐字相同才算重复副本。

**通用约定**：目标目录已存在同名 `.pdf` **跳过不覆盖**（幂等）；不删 `DOWNLOAD_DIR` 源 PDF 与 `.zip`/`.exe` 残留；**归档只写 PDF，资料库不生成 `.md`**（既有 `.md`/`html`/`docx` 来自历史补档，非归档产物）；`(copied, skipped)` 是**单目的地**口径。sync 步骤 7 自动调用，也可 `python3 archive_pdfs.py` 补跑。

### 4.8 外置盘增量备份（手动执行）

`scripts/backup_to_external.py` 把**项目资料库**（**不是整个 Git 仓库**）增量同步到外置盘：
- 源：`/Users/allenwywang/allen个人项目/project-zhou/周老师茶馆历史文档`
- 备：`/Volumes/My PSSD/文档资料/project-zhou`（外置盘根目录对应本机资料库根目录）

**目录映射**（`DIR_MAP`，外置盘沿用旧命名，**不重命名目录**）：`历史学习资料-2020及以前`→`历史学习材料`、`历史学习资料-{2021,2022}`→`历史学习材料-{年}`、`历史学习资料项目`→`历史学习资料`、其余同名。

**忽略**：`.DS_Store` 与**所有以 `._` 开头**的 AppleDouble 元数据文件（exFAT 上 macOS 写文件时自动生成的伴随文件）。它们不是用户资料：不参与比对、不计入 extra、也不删除。

**行为约定**：
- SHA-256 逐文件比对（分块读）；缺失才 `copy2`，相同跳过，**不同只列异常绝不覆盖**；备份侧 extra **只报告绝不删除**（稳态 0）。
- 默认模式同步后**再复检一遍**，有缺失/差异则非零退出；`--check` 只读输出 missing / different / extra。
- **外置盘未挂载或备份根目录不存在 → 报错 exit 2**，**绝不自动创建根路径**、绝不静默写回内置盘。
- 用户挂载后手动运行，**无任何定时任务**；只用标准库，兼容 Python 3.9。状态标记 ASCII。

---

## 5. 构建与运行命令

### 5.1 一键同步（默认推荐）
```bash
cd scripts
python3 sync.py                  # 从 progress.json 的 last_sync_date 续跑
python3 sync.py 0624             # 首次运行 / 强制指定起点
python3 sync.py --headless       # 后台跑（隐藏浏览器窗口）
```
行为（9 步，与运行时 log 编号一致）：1 抓页（含密码重试与封禁保护）→ 2 解析 → 3 下载 → 4 解压 → 5 处理 `.exe` 伪装 → 6 转 MD（双引擎质检）→ 7 归档 PDF（只进资料库）→ 8 更新 progress.json → 9 完整性验证。

### 5.2 分步调试（适合失败时排查）
```bash
cd scripts
python3 fetch_jianguoyun.py      # 只跑抓页面（旧脚本，密码 0403 抓不到，仅做截屏/HTML 落盘）
python3 parse_html.py            # 只解析 data/jianguoyun_page.html
python3 download.py 0624         # 只下载（接受上次日期作为参数）
python3 extract.py               # 只解压茶馆杂谈文件同步/ 下的全部压缩包
python3 archive_pdfs.py          # 只归档 PDF（补跑历史或单独调试）
python3 archive_pdfs.py --dry-run # dry-run：只显示待拷贝列表
python3 pdf_to_md.py             # 默认 light 模式（转换即排版）
python3 pdf_to_md.py --no-format # 仅诊断：跳过排版，正常同步不要用
python3 pdf_to_md.py --auto      # 自动扫描 + 推荐模式
python3 pdf_to_md.py --mode light|medium|full
```
`medium` / `full` 当前降级到 light（预留接口，TODO 接入 multidoc-transfer-multimodal）。

### 5.3 显式依赖
```bash
pip install playwright pdfplumber PyMuPDF
brew install p7zip               # 7z 命令，需用于 .rar / .7z 以及 zip fallback
```
`playwright install chromium` 可选——现役用 `channel="chrome"` 绕过（见 §7.5）。

### 5.4 外置盘备份（手动，需先挂载外置盘）
```bash
cd scripts
python3 backup_to_external.py           # 增量同步 + 同步后校验（写入外置盘）
python3 backup_to_external.py --check   # 只读体检，不写入
```
退出码：`0` = 一致；`1` = 有 missing 或 different；`2` = 外置盘未挂载或备份根目录缺失。详见 §4.8。

---

## 5.5 定期同步的标准执行流程（项目级 Skill）

`.kimi-code/skills/chaguan-sync/` 是本项目**定期同步的标准流程入口**：7 阶段（预检 → 导出比对材料 → LLM 语义复查 → 修复门禁 → 规则修正 → 收尾报告）。用户说「同步一下」时自动加载。

三支脚本（需 `env -u PYTHONPATH /usr/bin/python3`）：`precheck.py` 机械预检（信号 `lead_orphaned` / `para_too_long` / `para_dangling`，**只报证据不下结论**，阈值用已验收的 1241 篇存量库反标定）；`export_review.py` 导出 `md.md` + 带 `[断]/[续]` 标记的 `src.txt` + `para_map.json`；`verify_fix.py` 修复门禁（字符守恒 / H1 / 无三连空行 / 再排版幂等 / 无占位残留，**全绿才能落盘**）。

修复两段 = 删掉中间空行、两段文本直接相连（写错会「再排版又拆开」→ 幂等门禁失败）。判据细节见 skill 的 `references/layout_review_rubric.md`。

---

## 6. 测试与质检

**没有正式的 pytest / unittest 测试目录**（`scripts/test_md_layout.py` 是独立回归脚本，非框架测试）。质检以三种形态存在：

1. **PDF → Markdown 双引擎交叉质检**（`_compare_pages`，`pdfplumber` + `PyMuPDF` 逐页比字符数）：`diff_ratio > 0.15` → `warn`；一侧无文本、纯图片页 → `error`；含图且文本 <50 字符 → `warn`；末页一致判空且其余页有内容 → `ok`，中间空白页仍 `warn`。结果落 `_qc_report.json`。**历史补档仍有警告，不能声称全库 QC 无警告。**
2. **离线复跑**——`progress.json` 充当"测试 fixture"。每次同步后增量记录历史，回看 `total_downloaded` / `history[].count` 判断当次稳态。
3. **排版回归测试**（2026-11-12 起）：`test_md_layout.py` 比对 project-zhou 与知识库两份规则实现的输出、门禁结论与 `RULE_VERSION`，并验证存量已排版文件幂等；含排版被跳过 / 掉字 / 缺 H1 / 连续空行四类负例。改 `md_layout.py` 或知识库侧 `format_chaguan_md.py` 后必跑，退出码非 0 不得同步。

**修改脚本时的最低验证**：
```bash
cd scripts
python3 -c "import extract, parse_html, fetch_jianguoyun, download, pdf_to_md, archive_pdfs, naming, audit_dates, sync, md_layout"
python3 test_md_layout.py                          # 排版回归：双份一致性 + fail-close 门禁（改规则必跑）
python3 pdf_to_md.py --auto <small_test_dir>      # 走一遍整条转换
```

---

## 7. 安全与合规要点

> 不是 web 服务项目，但有几个不容退让的边界，**任何修改都不能破坏**。

### 7.1 坚果云密码封禁护栏
`sync.py` 内置 `MAX_PWD_ATTEMPTS = 3`。超过必须 `raise` 让用户介入，**不要悄悄绕过**——改成无限重试会触发 30 分钟～数小时的 IP 封禁，对其它浏览器使用都有影响。

### 7.2 不要直接运行 .exe
`茶馆杂谈文件同步/` 里出现的 `.exe` 全部是 PDF 伪装。`rename_exe_to_pdf()` 之外**绝对不要**对这些文件做 `subprocess.run([...])` 之类。代码里碰到 `.exe` 时一律先 `read(5) == b"%PDF-"` 判别。

### 7.3 状态标记用 ASCII
旧版 Windows GBK 下 Unicode 符号（`✓` `⚠`）会崩。所有状态标记一律 `[OK]` / `[FAIL]` / `[WARN]`，**不要回退到 Unicode**，即便当前是 macOS。

### 7.4 路径硬编码
`/Users/allenwywang/...` 是单人项目本机化设计，**不要为了"通用化"擅自抽参数**。确要改时至少同步更新 `sync.py`、`pdf_to_md.py`、`download.py`、`extract.py` 的同一常量。

### 7.5 Playwright → 本机 Chrome
`channel="chrome"` 是已知选择（国内拉 chromium 太慢）。改回默认写法前先确认网络可达。

### 7.6 AI 会话里跑脚本必须先清 PYTHONPATH
WorkBuddy / CodeBuddy 等宿主会通过 `PYTHONPATH` 注入 `sitecustomize.py`，它 patch 了 `os.mkdir` / `Path.mkdir`：对**已存在**的目录不遵守 `exist_ok=True`，伪报 `FileExistsError`（步骤 1 的 `mkdir assets` 必踩）。同时宿主默认 `python3` 常是自带的 3.13，缺 `playwright` / `pdfplumber` / `fitz`。

在 AI 会话里统一用 `env -u PYTHONPATH /usr/bin/python3 sync.py`。本机 `/usr/bin/python3` 是 3.9.6 且依赖齐全；用户自己终端不需要这层包装。这是**执行环境差异，不是代码 bug**——不要改 `mkdir` 调用。

---

## 8. 常见调试指引

同步 / 转换 / 复查 / 审计 / 备份各阶段的故障定位（含坚果云封禁、蓝奏云中转页下载失败、
`.exe` 未改名、`[LAYOUT-FAIL]`、预检误报、`verify_fix` 报错、备份 exit 2 等），
**统一见 skill 的 `.kimi-code/skills/chaguan-sync/references/troubleshooting.md`**。
该文档附带存量库标定基线（段落长度分布、各信号命中率），改阈值前必读。

---

## 9. 修改时的红线

- **不要改动** file_id 正则 `r'^(\d{4}更新)[：:](.+)[：:]\s*(\/?i[a-zA-Z0-9/]{8,})(?:[：:\s]*密码[：:]([a-zA-Z0-9]+))?\s*$'` 中的 file_id 字符类 `[a-zA-Z0-9/]`——保留 `/` 是为了兼容历史脏字符前缀。`i` 前缀是 lanzou ID 的硬约定（10+ 字符）；允许前面的 `\/?` 和 `[：:\s]*密码` 是容错。
- **不要把** `find_last_date_line` 里 `max(...) by line_no` 改成单纯按出现位置——多列数据下会重复抓旧列。
- **不要把** `>= start_line` 改回 `> start_line`——后者会漏掉"上次日期当天最后一列"那条。
- **不要删除** `renamed = rename_exe_to_pdf()` 这一步——`pdf_to_md.py.convert_batch()` 只 glob `*.pdf`，没有它就少掉一批。
- **不要**绕过 `download_entries()` 的 `[SKIP]` 存在性预检（§4.6）。
- **不要移除** `channel="chrome"`——见 §7.5。
- **不要**在 `progress.json.history` 的 entry 里增删字段名——下游人工复盘依赖稳定 schema。
- **不要**绕过 `_file_matches_short_id()` 的前缀表（`{"JM": ["JM"], "WP": ["外篇","WP"], "python": ["python学习材料","ptyhon学习材料"]}`）——WP 和 python 的真实下载文件名跟条目名不一致，验证靠这张表对应。`ptyhon学习材料` 是 python904 误拼变体（蓝奏云偶发返回的文件名拼写错误）。
- **不要把** `archive_pdfs()` 改成覆盖已存在的同名 `.pdf`——存档是只追加（首次拷贝保留），覆盖会破坏存档的历史真相。
- **不要**把 PDF 放进知识库 `MARKDOWN_DIR`——知识库只放 `.md`，PDF 一律进项目资料库年度目录；MD 里的 `> 原文件：xxx.pdf` 行只是溯源记录，不代表 PDF 在知识库里。
- **不要改动** `archive_pdfs()` 的项目资料库分类规则（`classify_project_dest()`）：JM → `历史学习资料-<发布年>`（`<=2020` 进 `历史学习资料-2020及以前`），python/ptyhon/外篇/WP → `Python学习材料`；**未识别前缀不要擅自归类**，保留外部归档 + `[WARN]` 等人工确认。
- **不要**在归档流程里往项目资料库 `周老师茶馆历史文档/` 写 `.md`——MD 只在外部 MARKDOWN_DIR 生成。
- **不要把** `archive_pdfs()` 改回双目的地（知识库 + 资料库）——知识库只放 `.md`，PDF 只进资料库；`(copied, skipped)` 是**单目的地**口径，不要再按「所有目的地合计」解释（2026-11-12 前的旧口径已废）。
- **不要**让 `backup_to_external.py` 覆盖备份侧内容不同的同名文件——只列异常、不覆盖，与 §4.4 不覆盖原则一致。
- **不要**让 `backup_to_external.py` 删除备份侧的额外文件——只报告、不删除。
- **不要**在 `backup_to_external.py` 里自动创建备份根目录——外置盘未挂载必须报错退出（exit 2），绝不能静默退回到内置盘写入。
- **不要**给 `backup_to_external.py` 挂 launchd / cron 定时任务——用户明确要求挂载后手动执行。
- **不要改动** `backup_to_external.py` 的 `DIR_MAP` 目录映射——外置盘沿用旧目录命名，映射表是两侧对上的约定。
- **不要**把 JM 文件名改回 `YYYY年MM月_JMxxx 标题` 或 `JMxxx 标题`——知识库已统一为 `YY.MM月-JMxxx-标题`，`scripts/naming.py` 是唯一事实源（含 `JM早期文章` 无编号分支）。
- **不要**让 python / 外篇 / WP 重新进知识库 `MARKDOWN_DIR`——它们只归档项目资料库（2026-11-12 起）。
- **不要**移除 `pdf_to_md.py::_convert_light` 里的 `md_layout.layout()` 调用、门禁判断或 `md_content == raw_md` 断言，也不要把 `do_format` 默认值改成 `False`——这是 2026-11-12 全库排版成果不回归的唯一防线；`--no-format` 只能用于诊断。

---

## 10. 版本/状态速览

- 主推入口 `scripts/sync.py`；Markdown 只用 `light`（双引擎），`medium`/`full` 是预留接口。
- **排版**：1241 篇存量 MD 已于 2026-11-12 全量排版完成；此后转换即排版（§4.5）。
- **编号完整性（2026-11-12 复核）**：C++ 正篇 1–221（含 2–38 合订本）、C++ 外篇 1–9、**JM 1–1148**、Python 1–925（含 22-32 合订本）、Python 外篇 1–348，**两边 0 缺号**。知识库 1233 个 `.md`（缺 JM5 的 md）；资料库 1234 个 PDF（含 `20.01月-JM5-社区浅谈.pdf`，内容与 `春节贺词` 逐字相同，属错标编号副本）。**全库体检必须展开合订本编号范围**，否则 Python 23–32 会被误报缺号。
- 归档：**单目的地**（只进项目资料库，增量不覆盖、幂等；知识库只放 MD），规则见 §4.7。
- **外置盘备份**：2026-11-01 初始化的 identical 数字已过期（11-12 资料库重命名 + 按年归位）。下次挂载后先 `--check` 再增量同步；手动执行，**不建定时任务**。
- 历史补档（含从其他目录并入的无编号 JM 资料）部分 Markdown 仍带纯图片页 / 文本差异 QC 警告，**原版 PDF 存档完整**——属已知情况，不是数据缺陷。

---

## 11. 完整性验证

`sync.py` 步骤 9 的 `verify_completeness()`：在 last_date ~ latest_date 范围内逐条检查。

- **5 状态**：`ok`（PDF+MD）/ `needs_convert`（有 PDF 无 MD）/ `needs_unzip`（zip 未解压）/ `needs_rename`（.exe 未改名）/ `missing`（都没有）。
- **匹配**：`_file_matches_short_id()` 把短 ID（`JM1066`/`WP330`/`python873`）映射到产物真实前缀（`外篇330`/`python学习材料873` 等）。
- **断号**：`_detect_sequence_gaps()` 查 JM / WP / python学习材料 三系列连续性。**每次同步都要查。**
- **增量口径**：首次已全量覆盖；此后只查 `last_date` 锚点（含边界日前序条目）到 `latest_date` 的新增编号是否连续，**不重复扫全库**。C++ 已完结，不参与常规检查。
- **报告落盘**：`data/completeness_report.json`（字段含 `by_status` / `missing` / `sequence_gaps`）。

**补跑历史遗漏**：`verify_completeness(entries,'起','止')` 打 `missing` → `download_entries([...])` 补下 → `extract_archives()` + `rename_exe_to_pdf()` + `pdf_to_md.py --mode light` → 复跑确认 0 缺失。
