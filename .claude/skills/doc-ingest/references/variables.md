# 环境变量与默认值

所有脚本零配置可在本机直接跑（默认值即茶馆项目现值）；接入新公众号/新机器时按此表覆盖。

## 全局

| 变量 | 默认值 | 用途 |
|---|---|---|
| `DOC_INGEST_WORKDIR` | `~/.doc-ingest` | 管线工作目录（raw/凭据/日志/备份都放这里的 `data/wechat_archive/`） |
| `TEA_NICKNAME` | `周先生的茶馆四代目` | 公众号名（MD frontmatter、PDF 目录名） |
| `TEA_BIZ` | `MzkyNzUxNDUzNA==` | 目标号 `__biz`（凭据提取时比对用） |
| `TEA_FAKEID` | `MzkyNzUxNDUzNA==` | 公众号 fakeid（后台列表接口用，已废弃但保留兜底） |

## 阶段 3 正文抓取（wechat_archive.py）

| 变量 | 默认值 | 用途 |
|---|---|---|
| `WECHAT_API_BASE` | `http://localhost:5001` | wechat-download-api 服务地址 |
| `CONTENT_INTERVAL` | `13`（代码内）；实践建议 `8` | 正文抓取间隔秒数（自适应下限 6s） |
| `VERIFY_PAUSE` | `900` | 触发安全验证页后的整队暂停秒数（实测 14 分钟冷却） |
| `OBSIDIAN_ARCHIVE_DIR` | `历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采` | MD 输出目录 |

## 阶段 1 凭据捕获

| 变量 | 默认值 | 用途 |
|---|---|---|
| `SCHINZA_ROOT` | `~/allen个人项目/tools/schinza` | Schinza 源码位置（提供 mitm_capture/history_client） |
| `CAPTURE_WAIT` | `600` | 等待用户点开文章的最长秒数 |
| `MP_REQ_LOG` | `<WORKDIR>/data/wechat_archive/mp_requests.jsonl` | hosts 劫持记录器输出 |

## 阶段 5 PDF 归档（render_pdfs.py，须 /usr/bin/python3）

| 变量 | 默认值 | 用途 |
|---|---|---|
| `PDF_ARCHIVE_ROOT` | `project-zhou/周老师茶馆历史文档` | PDF 资料库根（落 `<号名>/YYYY/`） |
| `TRIM_TARGET_DIR` | 同 `OBSIDIAN_ARCHIVE_DIR` | trim 与 render_pdfs 共用的 MD 源目录 |

## 服务端（wechat-download-api）

启动时必须覆盖的 .env 值（否则限频过紧/轮询撞接口）：

```
RSS_POLL_INTERVAL=86400   # 关掉每小时列表轮询（列表接口已死，轮询只会延长风控）
RATE_LIMIT_GLOBAL=30
RATE_LIMIT_PER_IP=20
RATE_LIMIT_ARTICLE_INTERVAL=2
```

## 接入新公众号的最小清单

1. `TEA_BIZ=<新号__biz> TEA_NICKNAME=<新号名>` 覆盖环境变量
2. `OBSIDIAN_ARCHIVE_DIR`/`TRIM_TARGET_DIR` 指向新 MD 目录；`PDF_ARCHIVE_ROOT` 不变（按号名分目录）
3. 阶段 1 重新捕获凭据（extract 会校验 `__biz` 匹配）
4. 首篇正文人工抽查渲染质量（frontmatter/图片/引流截断）再放全量
