# 茶馆杂谈文件同步项目（Claude 平台入口）

> **本文件只做入口指针，不再承载项目事实。**
> 唯一真相源是项目根目录的 [`AGENTS.md`](../AGENTS.md)——目录结构、命令、正则红线、
> 状态速览、调试指引全部以它为准。本文件与 AGENTS.md 冲突时，一律以 AGENTS.md 为准。

## 一句话定位

从坚果云共享页读取蓝奏云下载参数，批量下载 → 解压 → PDF 伪装识别 → 转 Markdown（知识库只放 MD）→ PDF 归档到项目资料库，
约每半月人工触发一次。本机单人项目。

## 上手三步

```bash
cd scripts
python3 sync.py            # 续跑，自动读 progress.json
python3 sync.py 0624       # 首次运行 / 强制指定起点
python3 sync.py --headless # 后台跑
```

> 本机没有 `python` 命令，一律 `python3`。
> **AI 会话里要加前缀**：`env -u PYTHONPATH /usr/bin/python3`（宿主注入的 `sitecustomize` 会让 `mkdir` 伪报 EEXIST，且默认 `python3` 缺依赖）。详见 AGENTS.md §7.6。

分步调试、依赖安装、质检方式见 **AGENTS.md §5 / §5.2 / §5.3 / §6**。
修改脚本前必读 **AGENTS.md §4（关键约定）与 §9（修改红线）**。

## 跨平台迁移史（仅供考古，本机不再适用）

项目最初跑在 Windows 上，下列经验与当前 macOS 环境无关，保留只为理解脚本里的历史注释：

- 下载路径曾因同步盘实际位置与配置不符报 `FileNotFoundError`
- Windows bash 默认 GBK，导致 `✓`/`⚠` 等 Unicode 符号崩溃 → 全部状态标记改用 ASCII `[OK]`/`[FAIL]`/`[WARN]`
  （这条**仍然有效**，AGENTS.md §7.3 有现行版本）
- `echo "0506" | python download.py` 在后台任务里传不进 `input()` → 改为命令行参数传参

## 现行要点速查（详见 AGENTS.md）

| 边界 | 内容 |
|------|------|
| 坚果云密码 | `psw0528`，最多重试 3 次，超限直接 raise（AGENTS.md §4.3 / §7.1） |
| `.exe` 伪装 | 文件头 `%PDF-` → 重命名为 `.pdf`，**绝不执行**（§4.4 / §7.2） |
| 压缩包密码 | 文件名中所有数字拼接（§4.3） |
| 存档分工 | 知识库 `MARKDOWN_DIR` 只放 `.md`；PDF 只进资料库年度目录，两侧同 stem（§4.7） |
| 进度锚点 | `progress.json` 的 `last_sync_date` 是唯一同步状态（§4.2） |