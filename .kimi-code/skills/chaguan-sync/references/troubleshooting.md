# 常见故障与定位

## 同步阶段

### `sync.py` 报「未找到 XXXX 更新」

`progress.json` 的 `last_sync_date` 已超过源页最新条目。

```bash
cd scripts && env -u PYTHONPATH /usr/bin/python3 parse_html.py
```

看实际解析到哪几条。若源页确实没有更新的，说明坚果云还没更新，等下次。

### 坚果云反复弹密码框

已接近 IP 封禁（累计 3 次密码错误封 30 分钟～数小时）。

**不要**改成无限重试——`MAX_PWD_ATTEMPTS = 3` 超限直接 raise 是有意的护栏。
换 IP（重置路由器 / VPN）后再试，或等封禁解除。

### 下载失败 / `Target page ... closed`

蓝奏云分享页点击后打开**中转新页面**，download 事件挂在新页面上。

当前实现：单次点击 + `context.on("page", ...)` 监听 + `page.wait_for_timeout()` 泵事件循环。
**不要**恢复「原 page `expect_download` 空等 60s + 二次点击」的旧写法。

**不要**用 `time.sleep` 等事件——Playwright 同步 API 只在调用其方法时泵事件，`time.sleep` 期间事件不投递，会产生「事件到了但文件没落盘」的假阳性。

### 所有 `.exe` 未被重命名

用 Python 读前 5 字节确认真实 magic：

```python
with open(f, "rb") as fh:
    print(fh.read(5))
```

不是 `%PDF-` 才跳过。**绝不要**用 `head -c 5` 替代，也**绝不要**执行 `.exe`。

### 压缩包解压失败

- `7z` 不在 PATH → `brew install p7zip`
- 文件名不含数字 → 无密码，手动 `7z x -p<纯数字> <file>` 验证
- 密码规则：**文件名中的所有数字拼接**（`JM1056.zip` → `1056`）

## 转换阶段

### `[LAYOUT-FAIL]` 出现在日志里

排版门禁 fail-close，该文件**未落盘**。常见原因：

| 原因 | 处理 |
|---|---|
| 正文字符不守恒 | 排版规则吃字/掉字 → 查 `md_layout.verify` 的 `reasons` |
| 缺少 H1 标题 | 源 MD 头部结构异常 → 查 `_pages_to_markdown` |
| 存在连续空行 | 段落拼接产生三连空行 |
| 排版未生效 | 输出与物理行原文一致 → 规则链路被绕过 |

文件不会进知识库，修好再重转（`pdf_to_md.py --auto`）。

### `_qc_report.json` 显示大量 `pdfplumber 漏提`

文件大或多列表格。当前只有 light 档可用，`medium`/`full` 未接入多模态。

**不能声称全库 QC 无警告**——历史补档仍有纯图片页 / 文本差异警告，这是已知情况，不是数据缺陷。

### 某篇文章的知识库 MD 内容变了

大概率是**无 JM 编号的早期文章被重转覆盖**（94 篇受影响）——`convert_batch` 的跳过逻辑按 JM 编号匹配，对它们不生效。

处理：用 `export_review.py` 导出 `src.txt`，确认是不是内容变了；若只是排版差异，重跑语义复查即可。

## 复查阶段

### 预检命中了存量库里「已知没问题」的文件

阈值被改动了。用存量库验证：

```bash
env -u PYTHONPATH /usr/bin/python3 .kimi-code/skills/chaguan-sync/scripts/precheck.py --all
```

存量库（1241 篇已验收）命中率应在 **1~2%**。显著升高说明阈值过松，需要重标定。

标定基线（2026-11-12）：

| 指标 | 值 |
|---|---|
| 段落数 | 26163 |
| 段落长度 p50 / p90 / p99 / max | 51 / 118 / 204 / 726 |
| 末尾无终止标点的段落 | 368 段（1.41%） |
| 段内「。+汉字」命中文件占比 | 99.8% ← **不可用作信号** |
| H1 与文件名不一致 | 42 篇（3.4%）← 全是良性差异，**不可用作信号** |

### `verify_fix.py` 报「正文字符不守恒」

说明修改动了正文字符。**回退**——只能增删段落边界，不能改字。

用报错里的 `index=N` 定位差异位置。

### `verify_fix.py` 报「再次排版幂等」失败

分段还没稳定，再排版一次内容会变。常见于段尾既无终止标点又该断的地方。

修法：确保每个段落末尾要么是终止标点，要么是明确的独立段（如小标题、列举项）。

## 审计阶段

### `audit_dates.py` 退出码非 0

检查编号/年月倒挂、同编号多份、与坚果云不符、正文内嵌编号笔误。

**注意**：「同编号、不同标题」= 两篇不同文章（如 JM143 别做投枪 / JM146 愚公移山），**不是重复**。只有同编号且正文逐字相同才算重复副本。

### 完整性验证报断号

`_detect_sequence_gaps()` 查 JM / WP / python学习材料 三系列连续性。

补跑缺失条目：

```bash
cd scripts
env -u PYTHONPATH /usr/bin/python3 -c "import sync; ..."
# 或手动：download_entries([...]) → extract_archives() → rename_exe_to_pdf() → pdf_to_md.py --mode light
```

## 备份阶段

### `backup_to_external.py` 报 exit 2

外置盘未挂载，或 `/Volumes/My PSSD/文档资料/project-zhou` 不存在。

**不要**自动创建目录，**不要**静默退回到内置盘写入。挂载后重跑。

```bash
cd scripts
env -u PYTHONPATH /usr/bin/python3 backup_to_external.py --check   # 只读体检
env -u PYTHONPATH /usr/bin/python3 backup_to_external.py         # 增量同步
```

备份侧同名但内容不同的文件**只列异常绝不覆盖**；备份侧的额外文件**只报告绝不删除**。
