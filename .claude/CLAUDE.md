# 茶馆杂谈文件同步项目

## 项目概述
从坚果云读取蓝奏云下载参数，批量下载并解压文件。约每半月执行一次。

## 数据源

- **坚果云页面**：https://www.jianguoyun.com/p/DcEaxJgQ-P7XCRiJnL4FIAA （密码：`psw0528`）
  - ⚠️ 密码错误累计 3 次会触发 IP 封禁（30分钟~数小时），见踩坑记录 6
  - ⚠️ sync.py 已加保护：密码最多 3 次自动重试，3 次后停下来问用户
- **本地文件**：`C:\Users\Administrator\Downloads\特殊秘籍20240405.txt`
- **下载目录**：`C:\Users\allenwywang\allenwywang的同步盘\Allen documents\新建文件夹`

## 文件结构

```
茶馆系列文件同步项目/
├── .claude/
│   └── CLAUDE.md                # 本文档
├── scripts/                     # 核心脚本
│   ├── sync.py                  # 【主推】一键同步主控脚本（7步全自动）
│   ├── pdf_to_md.py             # PDF→Markdown转换器（支持 light/medium/full 三档）
│   ├── fetch_jianguoyun.py      # 抓取坚果云页面
│   ├── parse_html.py            # 解析HTML提取条目
│   ├── download.py              # 下载脚本（可独立运行）
│   └── extract.py               # 解压脚本（可独立运行）
├── data/                        # 当前执行的数据缓存
│   └── jianguoyun_page.html     # 坚果云页面快照
├── assets/                      # 当前执行的截图
│   └── jianguoyun.png           # 坚果云页面截图
├── archive/                     # 历史执行归档
│   └── 20260525/                # 每次执行单独归档
├── progress.json                # 同步进度记录
└── markdown/                    # PDF转换后的Markdown文件
    └── _qc_report.json          # 转换质检报告
```

## 核心逻辑

### 坚果云文件格式

文件包含多列数据（JM / python / WP 各成一列），最新条目在最后一列。
每列按日期倒序排列，最后一列的最新条目随时间更新（截至2026-05-25为 `0526更新`）。

### 下载定位逻辑

1. 每次下载前，读取上次同步日期（如 `0526`，存储在 `progress.json` 中）
2. 脚本找到该日期在所有条目中出现位置中**行号最大**的那个 → 自然定位到最后一列
3. 筛选该行号之后的所有条目开始下载

**关键规则**：文件有多列时，同一日期会在多列重复出现。`sync.py` 和 `download.py` 都遵循"**只取行号最大的那个（最后一列）**"的原则，确保每次从最后一列的最新位置继续，不会漏也不会重复。

### 文件名处理

蓝奏云服务器返回的文件名是正常的（如 `JM1056 换家（上）.exe`），直接使用 `suggested_filename`。

> **注意**：下载后的 `.exe` 文件实际是蓝奏云伪装的 PDF（文件头为 `%PDF-1.7`），**不要直接运行**。需读取文件头确认后批量重命名为 `.pdf`。

## 使用流程

### 【推荐】一键同步（自动从上次的时点继续）

```bash
cd scripts
python sync.py
```

- 自动读取 `progress.json` 中的上次同步日期
- 自动完成：抓取 → 解析 → 下载 → 解压 → 处理 .exe 伪装 → PDF转Markdown
- 自动检测PDF内容类型，选择最佳转换模式
- 自动更新 `progress.json`

首次运行时需要手动输入上次同步日期，之后全自动：

```bash
cd scripts
python sync.py
# 首次会提示：请输入上次同步日期（如 0331）
```

后台运行（不显示浏览器窗口）：

```bash
cd scripts
python sync.py --headless
```

### 手动分步执行（调试或单独使用某一步）

```bash
cd scripts

# 步骤1：抓取坚果云
python fetch_jianguoyun.py

# 步骤2：解析页面（生成本地数据文件）
python parse_html.py

# 步骤3：下载（指定上次同步日期）
python download.py 0506

# 步骤4：解压
python extract.py
```

## 执行记录

| 日期 | 操作 | 范围 | 结果 |
|------|------|------|------|
| 2026-05-07 | 下载+解压 | 0331~0506（最后一列） | 32个下载，25个解压成功 |
| 2026-05-25 | 下载+解压+重命名 | 0506~0526（最后一列） | 19个下载，11个zip解压成功，19个exe重命名为pdf |
| 2026-06-09 | 下载+解压+重命名+转MD | 0526~0609（最后一列） | 12个下载（10成功/2失败），5 zip解压，10 exe→pdf，9 MD转出 |
| 2026-06-09 | 补跑失败 | 0605~0606 | 2下载成功，6 zip解压（含已存在），2 exe→pdf，2 新MD（JM1071/python877） |

## 踩坑记录与经验总结

### 1. 下载路径变更（2026-05-25）
原脚本配置为 `E:\allenwywang同步盘`，但实际同步盘路径为 `C:\Users\allenwywang\allenwywang的同步盘`。E盘不存在会导致 `FileNotFoundError`。

### 2. Windows 控制台 Unicode 编码问题（2026-05-25）
Windows bash 环境默认使用 GBK 编码，脚本中的 `✓` `✗` `⚠` 等 Unicode 字符会导致 `UnicodeEncodeError: 'gbk' codec can't encode character` 崩溃。**解决方案**：全部替换为 `[OK]` `[FAIL]` `[WARN]` 等 ASCII 安全标记。

### 3. 后台任务管道输入失效（2026-05-25）
`echo "0506" | python download_from_local.py` 在 Windows bash 后台任务中无法正确传递给 `input()`，导致任务无限卡住。**解决方案**：改为命令行参数传入 `python download.py 0506`。

### 4. 蓝奏云 .exe 伪装（2026-05-25）
JM / python / WP 系列文件下载后扩展名为 `.exe`，但文件头实际是 `%PDF-1.7`，是蓝奏云将 PDF 伪装成可执行文件以绕过检测。**解决方案**：读取文件头确认后批量重命名为 `.pdf`。

### 5. 后台任务输出延迟
后台 bash 任务的 stdout 不会实时刷新，需将日志同时写入本地文件（如 `download_log.txt`）以便随时查看进度。

### 6. 坚果云密码错误 3 次后封 IP（2026-06-09）
坚果云对同一 IP 密码错误累计 3 次后会触发"密码错误次数过多，已禁止访问"，**持续 30 分钟~数小时**（按 IP 封禁）。**解决方案**：触发后必须换 IP（重启路由器 / VPN）或等待。`sync.py` 已加保护：密码最多 3 次自动重试，3 次后直接 raise 停下来问用户，不再继续尝试以免延长封禁。

### 7. Mac Chrome 148 + playwright 用本机 Chrome（2026-06-09）
Playwright 自带 chromium 国内 CDN 慢，`playwright install chromium` 卡在 git 拉源。**解决方案**：脚本改用 `p.chromium.launch(channel="chrome", headless=...)` 调用本机 Google Chrome（`/Applications/Google Chrome.app`），无需安装 chromium。

### 8. 补跑失败条目的临时脚本（2026-06-09）
sync.py 默认从 `last_sync_date` 之后全部重跑，无法精准补单。**解决方案**：写一次性脚本 `_retry_failed.py`，调用 sync.py 的 `download_one / extract_archives / rename_exe_to_pdf` 工具函数，跑完即删（不入 git）。

## 注意事项

- 蓝奏云下载按钮点击后需等待文件缓存加载，否则文件名可能乱码（已在代码中处理）
- 新页面打开后等待 3 秒再找下载按钮
- 如需从特定位置继续：输入日期关键词（如 `0331更新`）搜索跳位置
- `.exe` 文件不要直接运行，先检查文件头是否为 PDF 伪装
- `headless=False` 时能看到浏览器窗口便于调试，`headless=True` 适合后台运行
