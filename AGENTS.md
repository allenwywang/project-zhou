# AGENTS.md — 茶馆杂谈文件同步项目

本文件为 AI 编程代理提供项目背景知识，读者对项目一无所知。**事实以代码为准**，本文须与代码现状同步。

> **体量预算**：Codex 项目指令链按 32KiB 合并截断（全局 ~5.2KB + 本文件 ≤27KB）。新增内容须同步压缩旧文，保证末尾 §9 红线不被静默截断；改完用 `wc -c AGENTS.md` 核对。

---

## 1. 项目概述

**目的**：归档茶馆内容到知识库 MD 与项目资料库 PDF。常规来源是坚果云共享页中的蓝奏云文件（约每半月人工触发），另有微信公众号与 zlsdcg.com 个人站管线。蓝奏云流程：下载 → 解压 → PDF 伪装识别 → 转 Markdown → 归档。

**核心痛点**（决定了很多看似"怪异"的设计）：
- 蓝奏云下载 PDF 时把扩展名伪装成 `.exe`（文件头实际是 `%PDF-`），以绕过安全扫描。
- 坚果云对同一 IP 累计 3 次密码错误就封禁 30 分钟～数小时。
- 源页下载参数分三列（JM / python / WP），同一日期在多列重复，最新条目永远在最后一列。

**运行环境**：硬编码 macOS 路径，仅在本机 `/Users/allenwywang/...` 下工作。隐含前提：`chrome` 通道、Homebrew `7z`、本机**只有 `python3`**（没有 `python` 命令）。

## 2. 目录与文件清单

```
project-zhou/
├── .claude/CLAUDE.md           # Claude 入口指针，不承载事实；冲突以本文为准
├── .claude/skills/doc-ingest/  # 【核心技能】统管三管线；公众号管线脚本在此（~/.claude/skills/doc-ingest 为其软链）
├── scripts/                    # sync.py（蓝奏云主控，§5.1）/ pdf_to_md.py+md_layout.py+test_md_layout.py（§4.5/§6）/
│                                # naming.py+audit_dates.py+archive_pdfs.py+backup_to_external.py（§4.7/§4.8）/
│                                # zlsdcg_*.py（个人站，§5.6/§5.7）
│                                # fetch_jianguoyun.py+parse_html.py+download.py+extract.py（旧版，分步调试用）
├── data/                       # 运行时数据（gitignore）：坚果云页快照、zlsdcg_archive/、wechat_archive/
├── progress.json               # 同步进度（唯一状态源，gitignore）
├── 茶馆杂谈文件同步/            # 下载产物（gitignore）：*.pdf / *.exe / *.zip / <uuid>
└── 周老师茶馆历史文档/          # 【项目资料库】PDF 归档目标（§4.7）；671MB 唯一副本，gitignore 不入仓
```

**对外输出**（不在仓库内）：
- Markdown + `_qc_report.json` → `/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/JM系列/`（常量 `MARKDOWN_DIR`；2026-11-18 起独立子目录，与「公众号直采/」平行）。**只放 `.md` 不放 PDF**，**只收 JM 系列**（python/外篇/WP 只归档资料库），文件名 `YY.MM月-JMxxx-标题`（§4.7）。
- PDF 归档副本 → 仓库内 `周老师茶馆历史文档/`；外置盘备份 → `/Volumes/My PSSD/文档资料/project-zhou`（对应资料库根目录，**不是仓库镜像**，§4.8）。
- 知识库 `茶馆杂谈/公众号直采/`（`YYYYMMDD_标题` 命名，PDF 同 stem 落资料库 `周先生的茶馆四代目/<年>/`）由**两条管线共用**：微信公众号直采（skill `doc-ingest`，source 为 `mp.weixin.qq.com`）与 zlsdcg 个人站（§5.6，source 为 `zlsdcg.com`）。两源常有同一篇文章，靠"目标文件已存在即跳过"去重，因此**统计该目录必须按 frontmatter `source` 分开数**，别拿总数套单管线等式。

**依赖**：无 `pyproject.toml` / `requirements.txt`，靠脚本 `import` 自描述：`playwright`（配本机 Chrome）、`pdfplumber`、`PyMuPDF`（`fitz`）、`7z`（Homebrew `p7zip`）。

---

## 3. 运行时架构

```
坚果云 ─登录页─▶ HTML 快照 ─解析─▶ 条目列表
                                   │
蓝奏云 ◀─逐条 Playwright 下载───────┘
   ▼
本地 DOWNLOAD_DIR (茶馆杂谈文件同步/)
      ├─ extract_archives()  ─7-zip─▶ 子文件落同目录
      ├─ rename_exe_to_pdf() ─读头 magic─▶ .exe → .pdf
      ├─ convert_batch() ─pdfplumber+fitz─▶ MARKDOWN_DIR/JM系列（*.md，仅 JM）
      └─ archive_pdfs() ─copy2─▶ 周老师茶馆历史文档/（按发布年入年度目录，增量不覆盖）
```

## 4. 关键约定（修改前必读）

### 4.1 条目行格式

所有输入源（坚果云 HTML、本地 txt）同一种格式：`<4位日期>更新：<名称>：<file_id>[  密码：<pwd>]`
（例 `0526更新：JM1066 从冻省展开（1）：iW1o63qioede  密码：1066`）

- file_id 字符类**包含 `/`**：坚果云 HTML 偶发在 file_id 前加脏字符 `/`，解析后 `lstrip('/')` 清理，前缀再容错 `\/?`。
- **名称可含半角冒号**（如 `JM:1074`）：正则用贪婪 `.+` + 行尾 `$` 锚定 + MULTILINE，配合 file_id 必须以 `i` 开头且 ≥9 字符，让引擎停在正确的 file_id 上。
- 起点过滤用 `>=`（**不是** `>`）：`find_last_date_line()` 取该日期在所有出现中**行号最大**的那一个作起点，保证"上一日当天最右列"那条不漏。

### 4.2 进度锚点（同步状态机）

`progress.json` 是唯一的同步状态：`last_sync_date`（4 位月日，下次同步的左边界）、`last_sync_full_date`、`last_sync_range`、`last_sync_count`、`total_downloaded`、`history[]`（字段固定，下游人工复盘依赖）。**首次运行**必须由用户输入初始 `last_date`（如 `0624`），之后 `sync.py` 自动接管。

**下载失败不推进锚点**（2026-11-12）：`dl_failed > 0` 时 `last_sync_date`/`last_sync_full_date`/`last_sync_range`/`last_sync_count` 保持原值，只累计 `total_downloaded`，并在 `history[]` 追加带 `note` 的记录（字段名不变）。下次运行由 §4.6 预检只重试失败条目。

### 4.3 密码边界

- 坚果云页密码：`psw0528`（`sync.py` 顶部 `PASSWORD`）。**最多重试 3 次**（`MAX_PWD_ATTEMPTS = 3`），超过就 `raise` 停下来等用户介入，避免触发 IP 封禁延长。
- 蓝奏云分享页密码：从条目里解析，按条目传给对应下载请求。
- 压缩包密码：**文件名中的所有数字拼接**（如 `JM1056.zip` → `1056`）。逻辑在 `extract_password()`。

### 4.4 `.exe` 伪装 PDF 检测

文件头前 5 字节 == `b"%PDF-"` → 重命名为 `.pdf`（`rename_exe_to_pdf()`）；已存在同名 `.pdf` 时**跳过不覆盖**。

检查必须用 Python **`f.read(5)`**（`with open(f, "rb") as fh: fh.read(5)`，按需读入内存），**不要用 `head -c 5` 命令替代**；碰到 `.exe` 一律先这样判别，**绝不执行**（见 §7.2）。

### 4.5 文件名与 Markdown 头

- 输出 MD 文件名**优先用 `namer(pdf_stem)`**（`YY.MM月-JMxxx-标题`，§4.7）；无 namer 或返回 None 时退回 `re.sub(r'[\\/:*?"<>|]', '', pdf_stem)` 清理原名。
- MD 文件头固定（`<title>` = PDF stem，即新命名后的 stem）：H1 标题 + 空行 + `> 来源：茶馆杂谈系列` + `> 原文件：<title>.pdf` 两行引用 + `---` 分隔线（实现见 `pdf_to_md.py`）。

**正文排版（2026-11-12 起，转换即排版）**：
- 规则在 `scripts/md_layout.py`（`format_markdown`/`verify`/`layout`）：行尾无终止标点则与下一行拼接，有终止标点则断段；空行密集（OCR/已排版型）时原空行即段落边界。
- `pdf_to_md.py::_convert_light` 在 `write_text()` **之前**调 `md_layout.layout()`。门禁四项（字符守恒/有 H1/无三连空行/物理行不得原样输出）**失败抛 `[LAYOUT-FAIL]` 不落盘**（fail-close）。
- 知识库侧另有 `scripts/format_chaguan_md.py`，两份规则由 `test_md_layout.py` 逐例比对，`RULE_VERSION` 必须一致；**改规则两侧同步 + bump 版本号**。
- `--no-format` 仅供诊断。增强标记（`##`/`>`）属人工语义判断，不纳入自动转换；无 JM 编号的早期文章每次同步会被重转覆盖（§5.5）。语义层面的复查判据（六类缺陷/硬红线/判定速查表）见 §5.5 指向的 skill。

### 4.6 下载预检

`download_entries()` 先做 `[SKIP]` 存在性预检：复用 `_file_matches_short_id()` 短 ID 表匹配 `DOWNLOAD_DIR` 里已有的 `.pdf`/`.exe`/`.zip`，产物已存在直接跳过、**不再启动浏览器**。这是边界日不重复下载的保障，不要绕过。

**下载实现**：单次点击 + context 级 `download` 监听（含中转新页面），用 `page.wait_for_timeout()` 泵事件并 `save_as`。不要恢复「原 page `expect_download` 空等 + 二次点击」旧写法，也**不要**用 `time.sleep` 等 Playwright 事件。

### 4.7 存档分工：知识库只放 MD，PDF 只进资料库

`archive_pdfs(namer=None)` 把 `茶馆杂谈文件同步/*.pdf` 增量归档到项目资料库。**知识库 `MARKDOWN_DIR`（茶馆杂谈/JM系列/）只放 `.md`**（`pdf_to_md` 写），**不收 PDF**（2026-11-12 规则，此前并排的 94 个 PDF 已清空）。两侧同 stem：`xx.md`（知识库）↔ `xx.pdf`（资料库）。命名由 `scripts/naming.py` 生成，`sync.py` 按条目日期传 `namer`。

**项目资料库 `周老师茶馆历史文档/`（PDF 唯一归属地）**：
- `JM\d...` → `历史学习资料-YYYY/`（YYYY = 发布年，由新命名 `YY.MM月-` 推出，非当前年）；`<=2020` 进 `历史学习资料-2020及以前`。文件名与知识库完全一致（2026-11-12 起两侧同名）
- `python学习材料\d...` / `ptyhon学习材料\d...`（蓝奏云误拼变体）/ `外篇\d...` / `WP\d...` → `Python学习材料/`（沿用原名）
- 其他未识别前缀**不擅自分类**：仅外部归档 + `[WARN]` 等人工确认
- 判重按 JM 编号跨全部年度目录扫描，改日期换目录不重复入库

**JM 命名规则（`scripts/naming.py`，唯一事实源）**：有编号 `YY.MM月-JM<编号>-<文章名>`，无编号（早期文章）`YY.MM月-JM早期文章-<文章名>`；编号不补零（`JM66` 而非 `JM066`）；标题保留原文，仅清文件系统非法字符。`_file_matches_short_id()` 同时兼容下载原名 `JM1140 xxx` 与知识库新名 `26.10月-JM1140-xxx`。知识库双链由 Obsidian 自动维护（重命名走 `obsidian rename`）；`audit_lint.parse_tea_filename` 已兼容新旧两种文件名。

**年月怎么定（`YY.MM`）**——**JM 编号顺序第一优先**，任何日期来源都不得让编号递增时年月倒退：① 坚果云条目日期（首选，`build_entry_dates()` 从最新条目倒推，禁止直接拼当前年）；② 原批次年月（仅编号集中时采用，`2021年01月_` 是批量归档日，永不采信）；③ 缺口按编号线性插值，再全局强制单调；④ PDF `creationDate` 是导出日，仅兜底；⑤ 献词：新年献词记前一年 `YY.12月`，春节贺词记春节所在月。

`scripts/audit_dates.py` 是这条规则的守门脚本（编号/年月倒挂、同编号多份、与坚果云不符、正文内嵌编号笔误），**同步后跑一次，退出码非 0 即需处理**。「同编号、不同标题」= 两篇不同文章（如 JM143 别做投枪 / JM146 愚公移山），**不是重复**；只有同编号且正文逐字相同才算重复副本。

**通用约定**：目标目录已有同名 `.pdf` **跳过不覆盖**（幂等）；不删 `DOWNLOAD_DIR` 源 PDF 与 `.zip`/`.exe` 残留；**归档只写 PDF，资料库不生成 `.md`**（既有 `.md`/`html`/`docx` 来自历史补档）；`(copied, skipped)` 是**单目的地**口径。sync 步骤 7 自动调用，也可 `python3 archive_pdfs.py` 补跑。

### 4.8 外置盘增量备份（手动执行）

`scripts/backup_to_external.py` 把**项目资料库**（**不是整个 Git 仓库**）增量同步到外置盘：源为项目 `周老师茶馆历史文档/`，备为 `/Volumes/My PSSD/文档资料/project-zhou`（对应资料库根目录，不是仓库镜像）。

`DIR_MAP` 保持外置盘旧目录名：`历史学习资料-2020及以前`→`历史学习材料`、`历史学习资料-{2021,2022}`→`历史学习材料-{年}`、`历史学习资料项目`→`历史学习资料`，其余同名，**不要改映射**。

**忽略**：`.DS_Store` 与**所有以 `._` 开头**的 AppleDouble 元数据文件（exFAT 上 macOS 写文件时的伴随文件）——不参与比对、不计入 extra、也不删除。

**行为约定**：SHA-256 逐文件比对（分块读），缺失才 `copy2`、相同跳过、**不同只列异常绝不覆盖**；备份侧 extra **只报告绝不删除**（稳态 0）。默认模式同步后**再复检一遍**，有缺失/差异则非零退出；`--check` 只读输出 missing/different/extra。**外置盘未挂载或备份根目录不存在 → 报错 exit 2**，**绝不自动创建根路径**、绝不静默写回内置盘。用户挂载后手动运行，**无任何定时任务**；只用标准库，兼容 Python 3.9。状态标记 ASCII。

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
python3 fetch_jianguoyun.py      # 只抓页面（旧脚本，密码 0403 抓不到，仅截屏/落 HTML）
python3 parse_html.py            # 只解析 data/jianguoyun_page.html
python3 download.py 0624         # 只下载（接受上次日期作参数）
python3 extract.py               # 只解压 茶馆杂谈文件同步/ 下的压缩包
python3 archive_pdfs.py [--dry-run]   # 只归档 PDF（--dry-run 只列待拷贝）
python3 pdf_to_md.py [--auto|--mode light|medium|full]   # 默认 light（转换即排版）
```
`--no-format` 仅诊断用；`medium`/`full` 当前降级到 light（预留接口）。

### 5.3 显式依赖
```bash
pip install playwright pdfplumber PyMuPDF
brew install p7zip               # 7z 命令，需用于 .rar / .7z 以及 zip fallback
```
`playwright install chromium` 可选——现役用 `channel="chrome"`（§7.5）。

### 5.4 外置盘备份（手动，需先挂载外置盘）

```bash
cd scripts
python3 backup_to_external.py           # 增量同步 + 同步后校验（写入外置盘）
python3 backup_to_external.py --check   # 只读体检，不写入
```
退出码：`0` 一致；`1` 有 missing 或 different；`2` 外置盘未挂载或备份根缺失（详见 §4.8）。

## 5.5 定期同步的标准执行流程（项目级 Skill）

`.kimi-code/skills/chaguan-sync/` 是定期同步标准入口；用户说「同步一下」时加载。其 `precheck.py`、`export_review.py`、`verify_fix.py` 负责预检、导出比对材料、修复门禁，均需 `env -u PYTHONPATH /usr/bin/python3`；语义判据见 skill 的 `references/layout_review_rubric.md`。

### 5.6 zlsdcg.com 个人站管线（全量归档，增量见 §5.7）

入口 `scripts/zlsdcg_*.py`，数据与报告在 `data/zlsdcg_archive/`。**完整流程与操作细则在 skill `doc-ingest` 的「管线 C」**。项目层不变量：命名 `YYYYMMDD_标题`（最长 60 字）、同名加 `_wp<ID>`、PDF 同 stem、**不覆盖既有归档**；正文判重为主，同名异文与实质修订版保留，纯图片文章不得以旧空文本 MD 判重；原始 HTML 只解析不执行；图片限制协议、大小并验文件头；发布前跑 `zlsdcg_verify.py --pre-publish`，最终跑 `zlsdcg_verify.py` 与 `zlsdcg_final_report.py`；HTML/MD 用 doc-ingest 的 wapi venv，PDF/fitz 用 `env -u PYTHONPATH /usr/bin/python3`（不加 `-I`）。快照见 `data/zlsdcg_archive/final_report.md`，数量不在本文重复维护。

### 5.7 zlsdcg 增量重跑（站点新增文章后重跑同一条链）

2026-11-23 打通（站点 2674→2675，新增 1 篇，验收 0 问题）。脚本与 §5.6 同一批，**操作细则与四个坑见 skill `doc-ingest` 的「管线 C」**（fetch 缓存失效、图片只用 finalize_assets、已归档不重复发布、verify 不写死源站总数）。

```
zlsdcg_fetch.py → zlsdcg_index_kb.py → zlsdcg_process.py --prepare → zlsdcg_compare.py
→ 语义复核 → zlsdcg_finalize_review.py → zlsdcg_publish.py --stage
→ zlsdcg_finalize_assets.py → zlsdcg_publish.py --publish
→ zlsdcg_render_pdfs.py → zlsdcg_verify.py → zlsdcg_final_report.py
```

**引流尾块**：个人站文章末尾的「更多交流，请关注小红圈/芥末圈（孤苑白首…）」**及其配图**与正文无关，不入正文。管线锚点已覆盖（此前只认「（完）/404文章获取/个人网站：」），存量 775 篇已用 `scripts/zlsdcg_backfill_trim.py` 回填（备份在 `data/zlsdcg_archive/backfill_trim_backup/`）。改截断规则要 bump `trim_promo_tail.py` 的 `RULE_VERSION`，否则 `trim_state.json` 会跳过旧文件不再重判。

**语义复核可沿用上一轮判定**，但必须机械核验证据一致（status / nearest path / similarity / 正文哈希），差异项单独复核并在 decision 标注 `carried_over_from`；批次与决定文件 ID 集必须完全相同（`semantic_batches/batch-*.json` ↔ `review_decisions/semantic-*.json`）。每轮关键产物复制到 `data/zlsdcg_archive/history/<日期>/`。

**不要在发布后单独重跑 `zlsdcg_finalize_review.py`**：它依赖知识库现状判定"已归档"，发布后重跑会把刚发布的文章改判为重复，与 manifest / 验收记录脱节。要重跑就整链重跑，或先从 `history/<日期>/review_decisions.json` 恢复发布时状态。

---

## 6. 测试与质检

无 pytest/unittest 测试目录（`test_md_layout.py` 是独立回归脚本）。质检三种形态：

1. **PDF → Markdown 双引擎交叉质检**（`_compare_pages`，`pdfplumber` + `PyMuPDF` 逐页比字符数）：`diff_ratio > 0.15` → `warn`；一侧无文本、纯图片页 → `error`；含图且文本 <50 字符 → `warn`；末页一致判空且其余页有内容 → `ok`（中间空白页仍 `warn`）。结果落 `_qc_report.json`。**历史补档仍有警告，不能声称全库 QC 无警告。**
2. **离线复跑**——`progress.json` 充当"测试 fixture"。每次同步后增量记录历史，回看 `total_downloaded` / `history[].count` 判断当次稳态。
3. **排版回归测试**（2026-11-12 起）：`test_md_layout.py` 比对 project-zhou 与知识库两份规则实现的输出、门禁结论与 `RULE_VERSION`，并验证存量已排版文件幂等；含排版被跳过/掉字/缺 H1/连续空行四类负例。改 `md_layout.py` 或知识库侧 `format_chaguan_md.py` 后必跑，退出码非 0 不得同步。

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

### 7.1–7.5 不可退让的边界

- **坚果云密码封禁护栏**：`sync.py` 内置 `MAX_PWD_ATTEMPTS = 3`，超过必须 `raise` 让用户介入，**不要悄悄绕过**——无限重试会触发 30 分钟～数小时的 IP 封禁。
- **不要直接运行 .exe**：`茶馆杂谈文件同步/` 里的 `.exe` 全部是 PDF 伪装。`rename_exe_to_pdf()` 之外**绝对不要**对这些文件做 `subprocess.run([...])`；碰到 `.exe` 一律先 `read(5) == b"%PDF-"` 判别。
- **状态标记用 ASCII**：旧版 Windows GBK 下 Unicode 符号（`✓` `⚠`）会崩，一律 `[OK]`/`[FAIL]`/`[WARN]`，**不要回退到 Unicode**。
- **路径硬编码**：`/Users/allenwywang/...` 是单人项目本机化设计，**不要擅自抽参数**；确要改时至少同步更新 `sync.py`、`pdf_to_md.py`、`download.py`、`extract.py` 的同一常量。
- **Playwright → 本机 Chrome**：`channel="chrome"` 是已知选择（国内拉 chromium 太慢），改回默认写法前先确认网络可达。

### 7.6 AI 会话里跑脚本必须先清 PYTHONPATH

WorkBuddy / CodeBuddy 等宿主会通过 `PYTHONPATH` 注入 `sitecustomize.py`，它 patch 了 `os.mkdir` / `Path.mkdir`：对**已存在**的目录不遵守 `exist_ok=True`，伪报 `FileExistsError`（步骤 1 的 `mkdir assets` 必踩）。同时宿主默认 `python3` 常是自带的 3.13，缺 `playwright`/`pdfplumber`/`fitz`。

在 AI 会话里统一用 `env -u PYTHONPATH /usr/bin/python3 sync.py`。本机 `/usr/bin/python3` 是 3.9.6 且依赖齐全；用户自己终端不需要这层包装。这是**执行环境差异，不是代码 bug**——不要改 `mkdir` 调用。

---

## 8. 常见调试指引

故障定位统一见 `.kimi-code/skills/chaguan-sync/references/troubleshooting.md`（含存量库标定基线，改阈值前必读）。

---

## 9. 修改时的红线

- **不要改动** file_id 正则 `r'^(\d{4}更新)[：:](.+)[：:]\s*(\/?i[a-zA-Z0-9/]{8,})(?:[：:\s]*密码[：:]([a-zA-Z0-9]+))?\s*$'` 的 file_id 字符类 `[a-zA-Z0-9/]`（`/` 兼容历史脏字符前缀；`i` 前缀与前置 `\/?`、`[：:\s]*密码` 是容错）。
- **不要把** `find_last_date_line` 的 `max(...) by line_no` 改成按出现位置（多列数据下会重复抓旧列）；**不要**把 `>= start_line` 改回 `>`（会漏掉"上次日期当天最右列"那条）。
- **不要删除** `renamed = rename_exe_to_pdf()`（`convert_batch()` 只 glob `*.pdf`）；**不要**绕过 `download_entries()` 的 `[SKIP]` 预检（§4.6）；**不要**移除 `channel="chrome"`（§7.5）。
- **不要**增删 `progress.json.history` entry 的字段名（下游人工复盘依赖稳定 schema）。
- **不要**绕过 `_file_matches_short_id()` 的前缀表 `{"JM": ["JM"], "WP": ["外篇","WP"], "python": ["python学习材料","ptyhon学习材料"]}`（WP 与 python 的真实下载文件名与条目名不一致；`ptyhon学习材料` 是 python904 的蓝奏云误拼变体）。
- **不要把** `archive_pdfs()` 改成覆盖同名 `.pdf`（存档只追加，覆盖破坏历史真相）；**不要**把 PDF 放进知识库 `MARKDOWN_DIR`（MD 里 `> 原文件：xxx.pdf` 只是溯源）；**不要**往项目资料库写 `.md`（MD 只在 MARKDOWN_DIR 生成）。
- **不要改动** `archive_pdfs()` 的 `classify_project_dest()` 分类规则：JM → `历史学习资料-<发布年>`（`<=2020` 进 `历史学习资料-2020及以前`），python/ptyhon/外篇/WP → `Python学习材料`；未识别前缀不擅自归类，只外部归档 + `[WARN]`。
- **不要把** `archive_pdfs()` 改回双目的地（知识库只放 `.md`、PDF 只进资料库；`(copied, skipped)` 是单目的地口径，2026-11-12 前的旧口径已废）。
- **不要**让 `backup_to_external.py` 覆盖备份侧内容不同的同名文件、删除备份侧额外文件、在备份根目录不存在时自动创建、或挂 launchd/cron 定时任务——只列异常不覆盖、只报告不删除、未挂载必须 exit 2、用户要求手动执行；**不要改动** `DIR_MAP`。
- **不要**把 JM 文件名改回 `YYYY年MM月_JMxxx 标题`/`JMxxx 标题`（已统一为 `YY.MM月-JMxxx-标题`，`scripts/naming.py` 是唯一事实源）；**不要**让 python / 外篇 / WP 重新进知识库 `MARKDOWN_DIR`。
- **不要移除** `pdf_to_md.py::_convert_light` 里的 `md_layout.layout()` 调用、门禁判断或 `md_content == raw_md` 断言，也不要把 `do_format` 默认值改成 `False`（全库排版成果不回归的唯一防线；`--no-format` 只用于诊断）。
- **不要删掉** `zlsdcg_finalize_review.py` 的「同一 wordpress_id / 来源链接已在知识库 → 判重复」判定（否则增量重跑会重复发布已归档文章）；**不要在** `zlsdcg_verify.py` 里写死源站文章总数（读 `fetch_report.json` 的 `fetched_total`）；**不要**把 `zlsdcg_download_assets.py` 与 `zlsdcg_finalize_assets.py` 连着跑（前者改写暂存 MD 的图片引用，后者随后误判失败并阻断发布）。
- **不要**让公众号管线的 `trim_promo_tail.py` / 渲染改动个人站管线的 MD——`公众号直采/` 是两条管线共用的目录（§2），公众号管线只处理 `source=mp.weixin.qq.com` 的文件。
- **不要**未经用户明确指定并二次确认就跑全量同步——三条通道默认只做增量（skill `doc-ingest`「执行铁律」）：微信 `fetch --since-days 30`（不带 `--since-days`/`--full` 直接拒绝），蓝奏云 `run_lanzou_sync.sh` 续跑，个人站 `run_zlsdcg_sync.sh prepare|publish`；怀疑漏抓先跑对账定位缺口，别整站重来。

---

## 10. 版本/状态速览

- 主推入口 `scripts/sync.py`；Markdown 只用 `light`（双引擎）。
- **排版**：2026-11-12 全量排版完成，此后转换即排版（§4.5）。
- **编号完整性（2026-11-12 复核）**：C++ 正篇 1–221、外篇 1–9、JM 1–1148、Python 1–925、Python 外篇 1–348（合订本须展开范围）。知识库缺 JM5 的 MD；资料库 JM5 PDF 实为「春节贺词」错标副本。
- 归档：**单目的地**（只进项目资料库，增量不覆盖、幂等；知识库只放 MD），规则见 §4.7。
- **外置盘备份**：挂载后先 `--check` 再增量同步（旧基线已过期，11-12 资料库重命名 + 按年归位）；手动执行，**不建定时任务**。
- 历史补档部分 Markdown 仍带纯图片页 / 文本差异 QC 警告，**原版 PDF 存档完整**——已知情况，非数据缺陷。
- **zlsdcg 个人站**：全量轮 2026-11-22 发布 1702 篇，其后用户手工删除 24 篇「【黑木崖系列】」引流文，现库内 1679 篇；增量轮 2026-11-23 打通（新增 1 篇，验收 0 问题），规则见 §5.7。

---

## 11. 完整性验证

`sync.py` 步骤 9 的 `verify_completeness()` 在 last_date ~ latest_date 范围内逐条检查。

- **5 状态**：`ok`（PDF+MD）/ `needs_convert`（有 PDF 无 MD）/ `needs_unzip` / `needs_rename`（.exe 未改名）/ `missing`。
- **匹配**：`_file_matches_short_id()` 把短 ID（`JM1066`/`WP330`/`python873`）映射到产物真实前缀（`外篇330`/`python学习材料873` 等）。
- **断号**：`_detect_sequence_gaps()` 查 JM / WP / python学习材料 三系列连续性。**每次同步都要查。**
- **增量口径**：只查 `last_date` 锚点（含边界日前序条目）到 `latest_date` 的新增编号是否连续，**不重复扫全库**。C++ 已完结，不参与常规检查。
- **报告落盘**：`data/completeness_report.json`（`by_status` / `missing` / `sequence_gaps`）。

**补跑历史遗漏**：打 `missing` → `download_entries([...])` 补下 → `extract_archives()` + `rename_exe_to_pdf()` + `pdf_to_md.py --mode light` → 复跑确认 0 缺失。
