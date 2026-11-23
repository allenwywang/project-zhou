# services/ — 技能运行时依赖（不入仓）

本目录下的内容是**本机运行时依赖**，不随项目仓库提交（见根目录 `.gitignore`）。
技能本体（`SKILL.md`、`references/`、`scripts/`）在仓库里，是唯一真相源。

## wapi-venv/ — Python 虚拟环境（94MB）

正文/渲染要用 `markdownify`、`bs4`（`/usr/bin/python3` 没有）。
重建方式：创建 venv 后 `pip install fastapi uvicorn markdownify beautifulsoup4 curl_cffi pillow`，
再按需补 `requests`、`python-multipart`。

## wechat-download-api/ — 微信公开页解析服务（上游独立仓库的本地克隆）

- 上游：https://github.com/tmwgsicp/wechat-download-api.git
- 作用：公众号直采管线的正文抓取与图片本地化（服务本体在 `src/`，默认 `:5001`）
- **`.env` 含活的微信会话凭据（cookie/token），严禁提交到任何仓库**；从上游克隆后本地自建 `.env`
- 启动（技能 SKILL.md 里有完整命令）：
  `cd <skill>/services/wechat-download-api/src && env RSS_POLL_INTERVAL=86400 nohup ../wapi-venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 5001 > server.log 2>&1 &`
  （`RSS_POLL_INTERVAL=86400` 必须——微信已关闭后台列表接口，每小时轮询会撞风控。）

全局路径 `~/.claude/skills/doc-ingest` 是指向仓库内 `.claude/skills/doc-ingest` 的软链，
保证只有一份真身。
