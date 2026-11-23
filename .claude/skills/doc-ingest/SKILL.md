---
name: doc-ingest
description: project-zhou 茶馆项目核心技能，统管全部内容同步、处理与归档。当用户要求：同步公众号文章（全量/增量）、同步茶馆杂谈 JM/python 系列文档（坚果云+蓝奏云）、归档外部文档为 MD+PDF 双格式、把内容分发到 Obsidian 知识库或资料库、执行增量同步、对账验收、外置盘备份时使用。覆盖三条来源通道（微信客户端凭据 getmsg、浏览器直抓公开页、坚果云→蓝奏云 9 步管线）、个性化清洗（短剧广告卡/违规页/引流块/日期审计）、标准化输出（MD→Obsidian 日常阅读，PDF→资料库年度归档）、四层断点增量与验收对账。触发词：同步、增量同步、公众号同步、茶馆杂谈同步、拉取文章、归档、知识库分发、对账、备份资料库。
---

# Doc Ingest：project-zhou 内容同步·处理·归档核心管线

本技能是 project-zhou（茶馆杂谈文件同步项目）的唯一同步入口，统管三条来源通道，
把外部内容**个性化清洗 → 标准化为 MD+PDF 双格式 → 双目的地分发**：

- **MD → Obsidian 知识库** `历史学习资料/历史学习/raw/articles/`：日常阅读、双链检索
- **PDF → 资料库** `project-zhou/周老师茶馆历史文档/`：永久归档（外置盘另有增量备份）

知识库目录分工（平行并存）：

```
raw/articles/茶馆杂谈/
├── JM系列/      ← 蓝奏云管线产出（1247 篇，命名 YY.MM月-JMxxx-标题）
└── 公众号直采/   ← 微信管线 1023 + zlsdcg 个人站 1679 = 2702 篇（YYYYMMDD_标题，图片在 _attachments/）
```

## 技能位置

本技能在**项目仓库内**：`<project-zhou>/.claude/skills/doc-ingest/`，随 project-zhou 仓库 git 管理。
全局路径 `~/.claude/skills/doc-ingest` 是指向它的软链（单一真身，改一处即可）。
`services/` 是本机运行时依赖（`wapi-venv` 虚拟环境、微信解析服务及其 `.env` 凭据），**不入仓**，
重建方式见 `services/README.md`。

## 执行铁律：默认只同步增量

**用户说"同步""同步一下""更新一下"＝增量同步。** 三条通道的默认动作都只碰增量：

| 通道 | 增量（默认） | 全量（需明确指定 + 二次确认） |
|---|---|---|
| 微信公众号 | `fetch --since-days 30` → 正文/MD/清洗/PDF 走断点 | `fetch --full`（106 页 / 18 分钟，风控与配额成本最高） |
| 蓝奏云茶馆杂谈 | `run_lanzou_sync.sh`（从 `progress.json.last_sync_date` 续跑） | `run_lanzou_sync.sh 0624`（从起点重跑全量，重复下载已入库内容） |
| zlsdcg 个人站 | `run_zlsdcg_sync.sh prepare` → `publish` | 整条链重跑（含全量复核），仅在明确要求时 |

**全量同步的执行条件（缺一不可）**：
1. 用户**明确说了全量**（"全量重跑""从头再抓一遍""重新抓全站"），"同步"二字不算；
2. 先向用户说明代价（耗时、微信风控与配额、是否重复下载/覆盖），用提问确认；
3. 得到**明确肯定答复**后才执行。

**不得自行升级为全量**：上次跑失败、怀疑漏抓、想验证完整性——都先按增量跑，
再用对账报告（`final_report.py` / `zlsdcg_verify.py` / `audit_dates.py`）定位缺口；
真需要补历史，只补缺口那几条，不要整站重来。

**脚本层已有硬闸**：`wechat_client_fetch.py fetch` 不带 `--since-days` 也不带 `--full`
会直接拒绝执行（防止手滑跑成 106 页全量）。

## 通道决策树

| 来源 | 通道 | 入口 | 说明 |
|---|---|---|---|
| **茶馆杂谈 JM/python 系列**（蓝奏云压缩包） | 坚果云→蓝奏云 9 步全自动管线 | `scripts/run_lanzou_sync.sh [起点|--headless]` | sync.py 的安全封装（规避沙箱注入 + 依赖自检）。**约每半月人工触发一次**；MD 只收 JM 进知识库 `JM系列/`，PDF 全系进资料库年度目录 |
| **微信公众号**（任意号，全量/增量） | 客户端凭据：微信桌面端凭据 + `profile_ext?action=getmsg` | `scripts/wechat_client_fetch.py` | 唯一免费全量通道。微信后台列表接口已于 2026-07-30 关闭（ret=200013），勿再尝试 |
| **zlsdcg.com 个人站**（茶馆四代目同源站，WordPress） | 公开 REST API 枚举 → 正文判重 → 图片本地化 → MD+PDF 双格式归档 | `scripts/run_zlsdcg_sync.sh prepare\|publish` | 无需凭据。脚本本体在 `project-zhou/scripts/`（单一事实源）；本 skill 只封装调用。**站点有更新时按增量跑**（约每周一次），见「管线 C」 |
| **微信单篇/少量** | 浏览器直抓：curl_cffi Chrome 指纹直连公开页 | `services/wechat-download-api`(:5001，随 skill) `POST /api/article` | 公开页零凭据零风控 |
| 新增外部来源 | 先评估：有无公开列表页 → 能否免登录枚举 → 是否需要客户端凭据 | 按「微信管线」模板改造 | 决策依据见 references/lessons.md §1-2 |

## 管线 A：坚果云+蓝奏云（茶馆杂谈 JM/python 系列文档）

### 执行

```bash
scripts/run_lanzou_sync.sh              # 从 progress.json.last_sync_date 续跑（默认）
scripts/run_lanzou_sync.sh --headless   # 后台
```

9 步流水线：抓坚果云页 → 解析条目 → 边界日预检 → 下载蓝奏云 → 解压（密码=文件名数字拼接）
→ `.exe` 伪装识别（文件头 `%PDF-` → 改 `.pdf`，**绝不执行**）→ PDF 转 MD（双引擎交叉质检）
→ 归档分流 → 完整性报告。全程 `progress.json` 断点续跑。

### 关键规则（违规即返工）

- **存档分工**：知识库 `JM系列/` 只放 MD 且**只收 JM 系列**；python/外篇/WP 只归档资料库
  `Python学习材料/`；PDF 一律进资料库 `历史学习资料-YYYY/`（YYYY=发布年，≤2020 并入
  `历史学习资料-2020及以前`），两侧同 stem
- **命名**：`scripts/naming.py` 是唯一事实源（`YY.MM月-JM<编号>-<标题>`；无编号用
  `JM早期文章`；编号不补零）；判重按 JM 编号跨全部年度目录
- **坚果云密码**：最多重试 3 次，超限直接 raise（防 30 分钟封禁）
- **失败不推进锚点**：`last_sync_date` 只在全部成功时推进，失败条目下次自动重试
- **同编号不同标题 = 两篇不同文章**，不是重复；只有同编号且正文逐字相同才算重复副本

### 验收（每次同步后必做）

```bash
scripts/audit_dates.py            # 退出码非 0 = 编号/年月倒挂等问题，需处理
cat progress.json                 # last_sync_date / total_downloaded
data/completeness_report.json     # by_status / missing / sequence_gaps
```

## 管线 B：微信公众号（任意号）

前置：启动本地解析服务
`cd <skill>/services/wechat-download-api/src && env RSS_POLL_INTERVAL=86400 nohup ../wapi-venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 5001 > server.log 2>&1 &`（服务本体在 skill `services/` 内）
（`RSS_POLL_INTERVAL=86400` 必须——否则每小时轮询撞已关闭的列表接口延长风控。）

解释器分工：正文/渲染用 API venv（`/Users/allenwywang/.claude/skills/doc-ingest/services/wapi-venv/bin/python`，有
markdownify/bs4/curl_cffi）；PDF 用 `/usr/bin/python3`（有 playwright+fitz）。

### 首次全量（六阶段）

1. **凭据捕获**（一次性，TTL 30 分钟；风险主体是**登录的微信号**，用小号）：
   `bash scripts/setup_mp_intercept.sh`（hosts 劫持 + 记录器 + 重启微信）→ 用户在微信内点开
   目标公众号任意文章 → `TEA_BIZ=<__biz> scripts/wechat_client_fetch.py extract` →
   `bash scripts/cleanup_mp_intercept.sh` **立即还原 hosts + 删 MITM CA**
2. **列表**：`scripts/wechat_client_fetch.py fetch`（getmsg 翻页，~106 页/18 分钟；空页即到底）
3. **正文**：`CONTENT_INTERVAL=8 scripts/wechat_archive.py --content-only`（必须直连 Chrome
   指纹；每 ~100 篇触发一次安全验证页，整队暂停 15 分钟自愈）
4. **MD**：`scripts/wechat_archive.py --render-only` → `scripts/trim_promo_tail.py`（引流截断）
5. **PDF**：`/usr/bin/python3 scripts/render_pdfs.py`（图片 base64 内嵌，落
   `资料库/<号名>/YYYY/`）
6. **对账**：`scripts/final_report.py`（等式：索引 = MD + 广告剔除 + 失效；link 里 sn 是
   运行期占位符，跨清单匹配用 mid+idx）

### 增量同步（日常例行，存量零重复）

**只做增量，不碰存量**：每一步都有断点，存量文章既不重新下载也不重新转换。
四层断点（索引按 mid+idx 去重 / raw 按 mid+idx 断点 / MD、PDF 按目标存在跳过 / trim 按 mtime 跳过）：

```bash
# 解释器分工：正文与渲染必须用 API venv（有 markdownify/bs4）；PDF 用系统 python3
export DOC_INGEST_WORKDIR=/Users/allenwywang/allen个人项目/project-zhou
VENV=~/.claude/skills/doc-ingest/services/wapi-venv/bin/python

scripts/wechat_client_fetch.py extract                  # 用户点开文章后（30 分钟内）
scripts/wechat_client_fetch.py fetch --since-days 30    # 只翻最近 30 天（4 页/18 秒）
$VENV scripts/wechat_archive.py --content-only          # raw 断点自动跳存量
$VENV scripts/wechat_archive.py --render-only           # 目标 MD 已存在就早退
$VENV scripts/trim_promo_tail.py                        # 未变更的 MD 跳过
/usr/bin/python3 scripts/render_pdfs.py                 # 目标存在即跳
/usr/bin/python3 scripts/final_report.py                # 对账（只读，可全量）
```

**不要用 `/usr/bin/python3` 跑 `--content-only` / `--render-only`**：渲染要 markdownify，
缺了会在渲染阶段全量报错（正文已抓到，MD 却没生成，极易误判成"抓取失败"）。

**稳定身份是 mid+idx，不是 link**：微信 link 里的 `sn`/`chksm`/`key` 是运行期参数，
同一篇文章在不同轮抓取里 link 字符串不同。凡是"跨轮要认得出同一篇"的地方
（索引去重、raw 断点、失败/广告台账匹配）一律用 `mid+idx`；用整条 link 会导致
每轮重抓存量（实测一次多抓 18 篇）、索引里堆重复记录。

### 清洗规则（个性化处理，勿凭直觉改）

- **短剧广告卡**：4 个精确标记（`mp-common-cpsad`/`data-adtype=`/`new_cps_iframe`/
  `data-pluginname="mpcps"`）或去标签文字<10 字。**不能按 idx=2 猜**（正常次条混布）；
  **禁止加 `custom_select_card`**（泛类标记，实测误伤 45/93）
- **引流尾块**：按「（完）/（未完待续）」行截断（970/977 篇）；无结束符用「404文章获取」
  「个人网站：」行；荐书文（原价+元/套）正文即推广，不动。脚本幂等+备份可还原
- **违规页**（`此内容因违规无法查看`，32KB）= 微信侧真删，永久失效跳过并记 `failed.jsonl`；
  不要被 API 兜底文案里的「验证」二字误导成限频死循环——先直连诊断页面再分类
- **带货软广**（2026-11-23 新增样本：「天价虫草…赠伊」，引导加微信/领白皮书/限时公开）：
  4 个短剧广告卡标记**不匹配**，正文又长（<10 字规则也不触发），机器规则漏判。
  已按语义判定剔除并记 `ads.jsonl`（理由写"语义判定：带货软广"）。
  **规则暂未改**——加"加微信/领白皮书"这类文本特征有误伤风险，等积累样本后再定。
  判过的广告不再渲染（`ads.jsonl` 按 mid+idx 识别），所以删掉的广告不会复活
- **公众号直采目录是两条管线共用的**（公众号管线 + zlsdcg 个人站管线都写这里）：
  对账必须按 frontmatter `source` 分开统计，不能拿全目录 MD 数去套公众号的等式；
  **公众号管线的 `trim_promo_tail.py` 与渲染只处理 `source=mp.weixin.qq.com` 的 MD**，
  不碰个人站管线的文件（已加防护，勿去掉）

### 接入新公众号

改环境变量（见 references/variables.md）：`TEA_BIZ`/`TEA_NICKNAME`/`OBSIDIAN_ARCHIVE_DIR`/
`TRIM_TARGET_DIR`（PDF 落 `PDF_ARCHIVE_ROOT/<号名>/YYYY/` 自动分目录）→ 重捕获凭据 →
首篇人工抽查渲染质量再放全量。

## 管线 C：zlsdcg.com 个人站（WordPress 公开站）

站点 `zlsdcg.com` 是「周先生的茶馆四代目」的原始发布站，同一批文章另有公众号版本。
**无需凭据**，公开 REST API 即可枚举全部文章；与公众号管线互为补充（同名不同文、
修订版都保留），不与 JM 系列冲突。

### 执行（增量，约每周一次）

```bash
scripts/run_zlsdcg_sync.sh prepare   # 抓取→建知识库索引→正文比对→生成本轮复核批次
#   ↑ 中间必须做语义复核（见下），决定写 review_decisions/semantic-<NNN>.json
scripts/run_zlsdcg_sync.sh publish   # 合并决定→暂存→图片本地化→发布 MD→渲染 PDF→验收→报告
```

脚本本体在 `project-zhou/scripts/zlsdcg_*.py`（**单一事实源，skill 不复制**），
数据与报告在 `project-zhou/data/zlsdcg_archive/`。规则细节见项目 `AGENTS.md` §5.6（全量）与 §5.7（增量）。

### 语义复核（prepare 与 publish 之间）

- 批次在 `data/zlsdcg_archive/semantic_batches/batch-*.json`（每批 ≤25 项），
  决定写 `data/zlsdcg_archive/review_decisions/semantic-<NNN>.json`，
  **ID 集必须与批次完全一致**、每项 `decision` ∈ `duplicate|new|uncertain`，
  判重必须带 `evidence_path`（命中的知识库路径），否则 `finalize_review.py` 拒绝发布。
- 判据：**同一正文仅排版/图片地址/引流尾块/少量错字不同 → duplicate**；
  有新增或删减的实质正文 → new（即使 95% 相似）。
- 沿用上一轮判定前，必须**机械核验证据一致**（status / nearest path / similarity / 正文哈希），
  差异项单独复核，并在决定文件里标注沿用来源（`carried_over_from`）。

### 关键规则（违反即返工）

- **知识库只收 MD、资料库只收 PDF**，同 stem；既有文件**绝不覆盖**（同名冲突会抛错）
- **已归档文章不重复发布**：同一 wordpress_id 或同一来源链接已在知识库 → 判重复
  （纯图片文章无从比对、知识库副本被姓名脱敏改写导致哈希不等，这两种靠机械判重都兜不住）
- **fetch 缓存必须失效**：站点新增文章会让分页整体错位，prepare 已自动把 `raw_pages/` 归档
- **图片步骤只能用 `zlsdcg_finalize_assets.py`**：不要改用 `zlsdcg_download_assets.py`
  （它自己会改写暂存 MD 的图片引用，随后 finalize_assets 会把本地引用误判为失败并阻断发布）
- **不要在发布后单独重跑 `zlsdcg_finalize_review.py`**：它依赖知识库现状判定"已归档"，
  发布后重跑会把刚发布的文章改判为重复，与 manifest/验收记录脱节。要重跑就整链重跑
- 解释器分工：HTML/MD（process/publish）用 `services/wapi-venv/bin/python`；
  其余（fetch/index/compare/verify/render_pdfs）用 `env -u PYTHONPATH /usr/bin/python3`

### 验收（每次同步后必做）

`run_zlsdcg_sync.sh publish` 末尾会自动跑 `zlsdcg_verify.py` 与 `zlsdcg_final_report.py`；
关键产物在 `data/zlsdcg_archive/`，每轮另存一份到 `data/zlsdcg_archive/history/<日期>/`。

## 风控与合规边界

- 风险主体是**凭据/抓包用的微信号**（可能被要求验证）；被抓公众号与公开页抓取不受影响
- 蓝奏云管线：坚果云密码 3 次封顶；蓝奏云有中转页下载型链接（context 级 download 监听已内置）
- 微信公开页抓取不带凭据、间隔≥6s，长期实测零风控；验证页（`secitptpage/verify.html`，
  JS 渲染无文字特征）= 累计配额，15 分钟冷却自愈，勿硬冲
- 个人存档属灰色但普遍接受的自用；**再分发/商用是明确红线**
- MITM CA 用完立即删；hosts/系统代理还原（cleanup 脚本一键）

## 资料库维护

```bash
scripts/backup_to_external.py   # 资料库 → /Volumes/My PSSD/文档资料/project-zhou 增量备份（手动，外置盘挂载后）
```

## 故障速查

| 症状 | 根因 | 处置 |
|---|---|---|
| 列表 `200013 freq control` | 微信已关闭该接口（2026-07-30） | 不等待，走客户端凭据通道 |
| `no session`（profile_ext） | 缺 uin/key/pass_ticket | 重新捕获凭据（凭据阶段 1） |
| 队列卡单篇反复重试 | 违规页被误判限频 | 用新版脚本（先诊断再分类） |
| 正文整页 17KB 无文字 | 安全验证页 | 整队暂停 15 分钟，勿改参数硬冲 |
| `No module named 'markdownify'` | 解释器用错 | 换 API venv |
| `mkdir` 伪报 EEXIST | WorkBuddy 沙箱注入 sitecustomize | `run_lanzou_sync.sh` 已规避；手动时 `env -u PYTHONPATH /usr/bin/python3` |
| 蓝奏云下载 Target page closed | 中转页下载型链接 | sync.py 已用 context 级 download 监听修复 |
| PDF 图片缺失 | Chromium 未等 data URI 解码 | render_pdfs.py 已带 networkidle + print_background |
| playwright 未装 chromium | 首次未下载 | `python3 -m playwright install chromium` |
| 审计退出码非 0 | 编号/年月倒挂 | 按 audit_dates.py 输出逐条处理，勿绕过 |
| 个人站 `source ID count changed` | 验收脚本写死了源站文章总数 | 已改为读 `fetch_report.json` 的 `fetched_total` |
| 个人站 `staging conflict` / 生成 `_wp<ID>` 副本 | 已归档文章被当成新增再次发布 | 走 `finalize_review.py` 的"已归档"判定（同一 wordpress_id / 来源链接） |
| 个人站图片全部 `unsupported_scheme` | 先跑了 `download_assets.py`（它会改写暂存 MD 的图片引用） | 删掉暂存稿重跑 stage，只用 `finalize_assets.py` |
| 个人站复核发布被拒（exit 2） | 批次与决定文件 ID 集不一致，或判重缺 `evidence_path` | 对齐 `semantic_batches/batch-*.json` 与 `review_decisions/semantic-*.json` |

## 深入参考

- `references/lessons.md` — 11 条实战教训（200013 真相、抓包死路、验证页伪装、广告误伤、尾部饥饿、同名不同文、增量重跑的已归档判定等）
- `references/variables.md` — 全部环境变量与接入新来源清单
- 项目侧权威文档：`project-zhou/AGENTS.md`（蓝奏云 §4-§9、个人站 §5.6/§5.7、红线、调试指引）
- 蓝奏云管线脚本本体在 `project-zhou/scripts/`（sync.py 等），本 skill 通过 `run_lanzou_sync.sh` 调用——单一事实源，勿复制
- 个人站管线脚本本体同样在 `project-zhou/scripts/zlsdcg_*.py`，本 skill 通过 `run_zlsdcg_sync.sh` 调用——同样单一事实源，勿复制
