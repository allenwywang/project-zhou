# AGENTS.md — 茶馆杂谈文件同步项目

本文件为 AI 编程代理提供项目背景知识。读者对项目一无所知。文件应保持与代码现状同步。

---

## 1. 项目概述

**目的**：从坚果云（Jianguoyun）共享页面自动读取蓝奏云（Lanzou Cloud）下载参数，批量抓取文件，解压后将 PDF 转成 Markdown。约每半月人工触发一次，主要服务于个人历史学习资料整理。

**核心痛点**（决定了很多看似"怪异"的设计）：
- 蓝奏云在下载 PDF 时把扩展名伪装成 `.exe`（文件头实际是 `%PDF-`）以绕过安全扫描。
- 坚果云对同一 IP 累计 3 次密码错误就会触发封禁 30 分钟～数小时。
- 共享源文件的下载参数有三列（JM / python / WP），同一日期会在多列重复，最新条目永远在最后一列。

**运行环境**：项目硬编码了 macOS 路径，仅在本机 `/Users/allenwywang/...` 下工作。`chrome` 通道、Homebrew `7z`、`zsh`/`bash` 都是隐含前提。

---

## 2. 目录与文件清单

```
project-zhou/
├── .claude/CLAUDE.md             # 项目叙事 + 踩坑记录（旧位置，仍是事实记录主源）
├── scripts/
│   ├── sync.py                   # 【主推】一键主控脚本，跑完所有 7 个步骤
│   ├── pdf_to_md.py              # PDF → Markdown 转换器（light/medium/full 三档）
│   ├── fetch_jianguoyun.py       # 独立：抓取坚果云页面（旧版本，硬编码密码 `0403`）
│   ├── parse_html.py             # 独立：从 HTML 提取条目（旧版本，依赖本地缓存路径）
│   ├── download.py               # 独立：批量下载（接收命令行参数形式的上次日期）
│   └── extract.py                # 独立：批量解压压缩包
├── data/jianguoyun_page.html     # 坚果云页面快照（运行时生成，gitignore）
├── assets/jianguoyun.png         # 抓取时的全页截图（gitignore）
├── progress.json                 # 同步进度（gitignore，但实际仍入库）
└── 茶馆杂谈文件同步/              # 下载后的原始文件（gitignore）
    ├── *.pdf / *.exe             # 已下载文件（PDF 伪装为 .exe 已重命名）
    └── <uuid>                    # 未重命名的 exe 伪装文件原始名（蓝奏云返回的 UUID）
```

**对外输出目录**（非本仓库内）：
- Markdown 落盘到 `/Users/allenwywang/历史学习资料/历史学习/raw/articles/茶馆杂谈/`（脚本顶部 `MARKDOWN_DIR` 常量）。
- 质检报告 `_qc_report.json` 写在同一个输出目录。

**关键配置文件**：本项目**没有** `pyproject.toml` / `requirements.txt` / `Pipfile`。依赖靠脚本里 `from ... import` 自描述：
- `playwright`（同步 API）+ Chromium 之外的本地 Chrome
- `pdfplumber`
- `PyMuPDF`（import 名 `fitz`）
- `zipfile`（标准库）+ 系统命令 `7z`（Homebrew `p7zip`）

---

## 3. 运行时架构

整条流水线是 `sync.py` → 一连串有副作用的子模块，外部资源依赖如下：

```
坚果云 (jianguoyun.com)  ─登录页─▶  HTML 快照 ─解析▶ 条目列表
                                                      │
蓝奏云 (lanzoui.com)  ◀─逐条 Playwright 下载──────────┘
      │
      ▼
本地 DOWNLOAD_DIR (茶馆杂谈文件同步/)
      │
      ├─▶ extract_archives()  ──7-zip ──▶ 多个子文件落到同目录
      ├─▶ rename_exe_to_pdf() ──读头 magic──▶ .exe → .pdf
      └─▶ PdfConverter.convert_batch() ──pdfplumber + fitz ──▶ MARKDOWN_DIR
                                                       │
                                                       └─▶ _qc_report.json (质检报告)
```

**步骤编号（用户可见）**：
1. 抓取坚果云（含密码自动重试 + 封禁保护）
2. 解析条目
3. 下载
4. 解压
5. 处理 `.exe` 伪装
6. PDF → Markdown（含双引擎交叉质检）
7. 更新 `progress.json`

注意：脚本日志横幅里写的"步骤 X/5"和"步骤 X/7"两种编号并存（早期遗留），不要被 "步骤 7/5" 的字符串迷惑。

---

## 4. 关键约定（修改前必读）

### 4.1 条目行格式

所有输入源（坚果云 HTML、本地 txt）都用同一种文本格式：
```
<4位日期>更新：<名称>：<file_id>[  密码：<pwd>]
```
例：`0526更新：JM1066 从冻省展开（1）：iW1o63qioede  密码：1066`

正则字符类的细节（重要）：
- file_id 字符类**包含 `/`**——因为坚果云 HTML 偶发会在 file_id 前加脏字符 `/`，解析后会 `lstrip('/')` 清理掉。允许在前面再多加一个 `\/?` 兼容历史脏字符（如 `0528更新：JM1067：/iW1o63qioede`）。
- **名称可以含半角冒号**（如 `JM:1074`、`JM:1086`）——这是 2026-07-21 发现的真实数据。解析器用贪婪 `.+` + 行尾 `$` 锚定 + MULTILINE，配合 file_id 必须以 `i` 开头且 ≥ 9 字符，让引擎停在正确的 file_id 上。
- 起点过滤使用 `>=`（**不是** `>`）：找到指定日期在所有出现中**行号最大的那一个**作为起点，取之后的条目。这是为了保证"上一日当天最右列"那条不会漏掉。

### 4.2 进度锚点（同步状态机）

`progress.json` 是唯一的同步状态：
```json
{
  "last_sync_date": "0704",          // 4 位月日，下次同步的左边界
  "last_sync_full_date": "2026-07-04",
  "last_sync_range": "0624~0704",
  "last_sync_count": 10,
  "total_downloaded": 33,
  "history": [{ "date": "...", "range": "...", "count": N, "downloaded": D, "extracted": E, "renamed": R, "converted": C }, ...]
}
```

**首次运行**必须由用户输入初始 `last_date`（如 `0624`），之后 `sync.py` 自动接管。

### 4.3 密码边界

- 坚果云页密码：`psw0528`（写在 `sync.py` 顶部 `PASSWORD` 常量里）。**最多重试 3 次**——超过就 `raise` 停下来，避免触发 IP 封禁延长。
- 蓝奏云分享页密码：从条目里解析，按条目传给对应下载请求。
- 压缩包密码：**文件名中的所有数字拼接**（如 `JM1056.zip` → `1056`）。逻辑在 `extract_password()`。

### 4.4 .exe 伪装 PDF 检测

```
文件头前 5 字节 == b"%PDF-"   →   重命名为 .pdf
```

`rename_exe_to_pdf()` 的规则。已经存在同名 `.pdf` 时**跳过**不覆盖。

### 4.5 文件名规则

- 输出 Markdown 文件名 = PDF stem 经过 `re.sub(r'[\\/:*?"<>|]', '', name)` 清理后的字符串。
- Markdown 文件头标准：
  ```
  # <title>
  
  > 来源：茶馆杂谈系列
  > 原文件：<title>.pdf
  
  ---
  ```

### 4.6 不要相信 `head -c` 代替 `read(5)`

下载文件头检查必须用 `f.read(5)`——文件较大时按需读到内存，不要试图用 `head -c 5 file` 命令替换。

---

## 5. 构建与运行命令

### 5.1 一键同步（默认推荐）
```bash
cd scripts
python sync.py                  # 自动从 progress.json 里的 last_sync_date 续跑
python sync.py 0624             # 首次运行或强制指定起点
python sync.py --headless       # 后台跑（隐藏浏览器窗口）
```

行为：抓页 → 解析 → 下载 → 解压 → 重命名 → 转 MD → 更新 progress.json。

### 5.2 分步调试（适合失败时排查）
```bash
cd scripts
python fetch_jianguoyun.py      # 只跑抓页面（密码 `0403`，独立硬编码；仅做截屏/HTML 落盘）
python parse_html.py            # 只解析 data/jianguoyun_page.html
python download.py 0624         # 只下载（接受上次日期作为参数）
python extract.py               # 只解压茶馆杂谈文件同步/ 下的全部压缩包
```

`pdf_to_md.py` 可以独立跑：
```bash
cd scripts
python pdf_to_md.py                          # 默认 light 模式
python pdf_to_md.py --mode light             # 显式轻量
python pdf_to_md.py --auto                   # 自动扫描 + 推荐模式
python pdf_to_md.py --mode medium            # 占位（当前降级到 light）
python pdf_to_md.py --mode full              # 占位（当前降级到 light）
```

### 5.3 显式依赖
```bash
pip install playwright pdfplumber PyMuPDF
playwright install chromium      # 可选，sync.py 改用了 channel="chrome" 绕过
brew install p7zip               # 7z 命令，需用于 .rar / .7z 以及 zip fallback
```

---

## 6. 测试策略

**没有正式的 pytest / unittest 测试目录**。质检以两种形态存在：

1. **PDF → Markdown 双引擎交叉质检**（`pdf_to_md.py._compare_pages`）
   - 同时跑 `pdfplumber` 和 `PyMuPDF`，逐页比对字符数。
   - `diff_ratio > 0.15` → `warn`。
   - 一边有文本一边没有 → `error`（漏提）。
   - 含图片 + 文本不足 50 字符 → `warn`（可疑图文混合）。
   - 纯图片页 → `error`（需要 OCR，未来 full 模式覆盖）。
   - 结果落盘 `_qc_report.json`：`{ mode, stats, details }`。

2. **离线复跑**——`progress.json` 充当"测试 fixture"。每次同步后增量记录历史，回看 `total_downloaded` / 历史 `count` 可以判断当次稳态。

**修改脚本时的最低验证**：
```bash
cd scripts
python -c "import extract, parse_html, fetch_jianguoyun, download, pdf_to_md, sync"
python pdf_to_md.py --auto <small_test_dir>      # 走一遍整条转换
```

---

## 7. 安全与合规要点

> 不是 web 服务项目，但有几个不容退让的边界，**任何修改都不能破坏**。

### 7.1 坚果云密码封禁护栏
`sync.py` 内置 `MAX_PWD_ATTEMPTS = 3`。超过必须 `raise` 让用户介入，**不要悄悄绕过**——直接换成循环无限的写法会触发 30 分钟～数小时的 IP 封禁，对其它浏览器使用都有影响。

### 7.2 不要直接运行 .exe
`茶馆杂谈文件同步/` 里出现的 `.exe` 全部是 PDF 伪装。`rename_exe_to_pdf()` 之外**绝对不要**对这些文件做 `subprocess.run([...])` 之类。代码里碰到 `.exe` 时一律先 `read(5) == b"%PDF-"` 判别。

### 7.3 Windows 编码历史（保留经验但不适用）
旧版踩坑：Windows bash 默认 GBK 编码导致 Unicode 表情（`✓` `⚠`）崩溃。修复方式：所有状态标记一律使用 ASCII `[OK]` / `[FAIL]` / `[WARN]`。**新代码不要回退到 Unicode 表情**——即便当前是 macOS，也要保持跨平台可移植。

### 7.4 路径硬编码
脚本里多处出现 `/Users/allenwywang/...`。这是单人项目本机化设计。**不要为了"通用化"擅自抽参数**，除非项目主明确要求。如果非要改，至少要同步更新：`sync.py`、`pdf_to_md.py`、`download.py`、`extract.py` 中的同一路径常量。

### 7.5 Playwright → 本机 Chrome
`p.chromium.launch(channel="chrome", ...)` 是已知选择（国内 CDN pull chromium 太慢）。改回 `playwright install chromium` 的默认写法需要先确认网络可达，否则同步会卡在 git 拉源。

---

## 8. 常见调试指引

| 现象 | 优先检查 |
|------|---------|
| `sync.py` 报"未找到 XXXX 更新" | `progress.json` 的 `last_sync_date` 是否已经超过源文件最新条目；尝试 `python parse_html.py` 看实际解析到哪几条 |
| 下载按钮找不到 | 蓝奏云偶发改 selector；当前匹配 `a.btn, a[href*='down'], input.bott, a:has-text('下载')` 等多组。截 `assets/jianguoyun.png` 没必要——抓的是坚果云页；用 `page.content()` 诊断蓝奏云 DOM |
| 所有 .exe 未被重命名 | 先挑一个 `head -c 5 file` 看真实 magic；如果不是 `%PDF-` 才跳过 |
| `_qc_report.json` 显示大量 `pdfplumber 漏提` | 文件大或多列表格；切到 `--mode medium` 或 `--mode full`（当前都降级到 light；预留接口，等未来接入 multidoc-transfer-multimodal） |
| 压缩包解压失败 | 7z 不在 PATH / 文件名不含数字（无密码）；手动 `7z x -p<纯数字> <file>` 验证 |
| 坚果云反复弹密码框 | 已经接近封禁。重置路由器 / VPN 切 IP 后再试 |

---

## 9. 修改时的红线

- **不要改动** file_id 正则 `r'^(\d{4}更新)[：:](.+)[：:]\s*(\/?i[a-zA-Z0-9/]{8,})(?:[：:\s]*密码[：:]([a-zA-Z0-9]+))?\s*$'` 中的 file_id 字符类 `[a-zA-Z0-9/]`——保留 `/` 是为了兼容历史脏字符前缀。`i` 前缀是 lanzou ID 的硬约定（10+ 字符）；允许前面的 `\/?` 和 `[：:\s]*密码` 是 2026-07-21 补的容错。
- **不要把** `find_last_date_line` 里 `max(...) by line_no` 改成单纯按出现位置——多列数据下会重复抓旧列。
- **不要把** `>= start_line` 改回 `> start_line`——后者会漏掉"上次日期当天最后一列"那条。`download_from_local.py` 老 bug 复盘过。
- **不要删除** `renamed = rename_exe_to_pdf()` 这一步——`pdf_to_md.py.convert_batch()` 只 glob `*.pdf`，没有它就少掉一批。
- **不要移除** `channel="chrome"`——见 §7.5。
- **不要**在 `progress.json.history` 的 entry 里增删字段名——下游人工复盘依赖稳定 schema。
- **不要**绕过 `_file_matches_short_id()` 的前缀表（`{"JM": ["JM"], "WP": ["外篇","WP"], "python": ["python学习材料","python"]}`）——WP 和 python 的真实下载文件名跟条目名不一致，验证靠这张表对应。

---

## 10. 版本/状态速览

- 主推入口：`scripts/sync.py`
- 最近一次同步：2026-07-21，0704~0721，14 条全成功（JM1089 首次下载失败后补跑成功；同日新增完整性验证步骤后补回 9 条历史遗漏）
- 累计下载：56
- 完整性验证：0526~0721 范围 56/56 完整、0 序列断号（JM/WP/python学习材料 三个系列）
- Markdown 模式：当前只用 `light`（双引擎文本）；`medium` / `full` 是预留接口（TODO 接入 multidoc-transfer-multimodal）

## 11. 完整性验证（项目迭代，2026-07-21）

`sync.py` 新增步骤 8：`verify_completeness()`。在 last_date ~ latest_date 范围内逐条检查：

- **每条 4 状态**：`ok`（PDF + MD 都有）/ `needs_convert`（有 PDF 无 MD）/ `needs_unzip`（zip 未解压）/ `needs_rename`（.exe 未重命名）/ `missing`（什么都没）
- **匹配逻辑**：`_file_matches_short_id()` 把条目短 ID（"JM1066"、"WP330"、"python873"）映射到下载产物的真实文件名前缀（"JM1066 <title>"、"外篇330"、"python学习材料873"）做模糊匹配
- **序列断号**：`_detect_sequence_gaps()` 检测 JM / WP / python学习材料 三个系列的连续性，输出 `[1067, 1074, 1089]` 这种缺口数组
- **报告落盘**：`data/completeness_report.json`（`{ anchor_date, latest_date, by_status, missing, needs_convert, needs_unzip, sequence_gaps }`）

**典型用法**——补跑历史遗漏：
```python
python3 -c "
import sys; sys.path.insert(0, 'scripts')
import sync
from pathlib import Path
entries = sync.parse_all_entries_from_html(Path('data/jianguoyun_page.html'))
rep = sync.verify_completeness(entries, '0526', '0721')
for r in rep['missing']:
    print(r['index'], r['name'], '->', r['file_id'])
"
```

输出 missing 列表 → 手喂给 `sync.download_entries([...])` 补下 → 跑 `extract_archives()` + `rename_exe_to_pdf()` + `pdf_to_md.py --mode light` → 再跑一次 `verify_completeness()` 确认 0 缺失。
