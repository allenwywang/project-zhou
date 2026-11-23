#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周先生的茶馆四代目 · 公众号全量归档 → Obsidian

数据源：本机 wechat-download-api（默认 http://localhost:5001）

三个阶段，全部可断点续跑：
  L 列表：GET  /api/public/articles?fakeid=..&begin=..&count=20
          appmsgpublish 的 begin/count/total 以「发布组」为单位（一组可含多篇），
          因此固定 begin += 20，直到 begin >= total。
  C 正文：POST /api/article {"url": link}
  R 渲染：HTML → Markdown + 图片本地化 → OBSIDIAN_DIR/YYYYMMDD_标题.md

微信限频（ret=200013 / freq control）自动退避 10→20→40→60 分钟；
触发安全验证页暂停 30 分钟。所有状态以文件为准，中断后重跑即续。

用法：
    cd scripts
    python3 wechat_archive.py              # 全流程（后台跑建议 nohup）
    python3 wechat_archive.py --list-only  # 只抓列表
    python3 wechat_archive.py --content-only
    python3 wechat_archive.py --render-only  # 只按本地 raw 重新生成 MD
    python3 wechat_archive.py --status
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("WECHAT_API_BASE", "http://localhost:5001").rstrip("/")
FAKEID = os.environ.get("TEA_FAKEID", "MzkyNzUxNDUzNA==")
NICKNAME = os.environ.get("TEA_NICKNAME", "周先生的茶馆四代目")

WORK_ROOT = os.environ.get("DOC_INGEST_WORKDIR", os.path.join(os.path.expanduser("~"), ".doc-ingest"))
DATA_DIR = os.path.join(WORK_ROOT, "data", "wechat_archive")
RAW_DIR = os.path.join(DATA_DIR, "raw")
ARTICLES = os.path.join(DATA_DIR, "articles.jsonl")
STATE = os.path.join(DATA_DIR, "state.json")
FAILED = os.path.join(DATA_DIR, "failed.jsonl")

OBSIDIAN_DIR = os.environ.get(
    "OBSIDIAN_ARCHIVE_DIR",
    "/Users/allenwywang/allen个人项目/历史学习资料/历史学习/raw/articles/茶馆杂谈/公众号直采",
)
IMG_DIR = os.path.join(OBSIDIAN_DIR, "_attachments")

PAGE = 20              # 每页请求的发布组数
LIST_INTERVAL = 30     # 列表页间隔（秒）
# 正文间隔（秒）。正文走 mp.weixin.qq.com/s/ 公开页、不带账号凭据，
# 与小号无关联；默认保守 13s，可用环境变量按服务端限频能力调整。
CONTENT_INTERVAL = int(os.environ.get("CONTENT_INTERVAL", "13"))
VERIFY_PAUSE_S = int(os.environ.get("VERIFY_PAUSE", "900"))  # 验证页触发后的整队暂停秒数
TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def log(msg):
    print(f"[{datetime.now(TZ).strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def _request(method, path, params=None, body=None, timeout=150):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_dirs():
    for d in (DATA_DIR, RAW_DIR, OBSIDIAN_DIR, IMG_DIR):
        os.makedirs(d, exist_ok=True)


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {"list_done": False, "begin": 0, "total": 0}


def save_state(st):
    st["updated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def norm_link(link):
    return (link or "").split("#")[0].strip()


def load_articles():
    out, seen = [], set()
    if not os.path.exists(ARTICLES):
        return out
    for line in open(ARTICLES, encoding="utf-8"):
        try:
            a = json.loads(line)
        except Exception:
            continue
        link = norm_link(a.get("link"))
        if not link or link in seen:
            continue
        seen.add(link)
        a["link"] = link
        out.append(a)
    return out


def article_key(link):
    return hashlib.sha1(norm_link(link).encode()).hexdigest()[:16]


def stable_id(link):
    """跨轮稳定的文章身份：mid+idx。

    link 里的 sn / chksm / key 等是运行期参数，同一篇文章在不同轮抓取里
    link 字符串不同。用它做断点键，否则每轮都会把存量文章重抓一遍。
    """
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    except Exception:
        return norm_link(link)
    mid = (query.get("mid") or [""])[0]
    idx = (query.get("idx") or [""])[0]
    return f"{mid}:{idx}" if mid and idx else norm_link(link)


def fetched_ids():
    """已经抓到正文的文章（按稳定身份）：扫 raw 目录，用文件里记录的 link 反解。"""
    ids = set()
    for path in glob.glob(os.path.join(RAW_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        link = payload.get("link") or ""
        if link:
            ids.add(stable_id(link))
    return ids


def failed_ids():
    """已确认永久失效（违规/删除）的文章（按稳定身份）。"""
    ids = set()
    if not os.path.exists(FAILED):
        return ids
    with open(FAILED, encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            link = record.get("link") or ""
            if link:
                ids.add(stable_id(link))
    return ids


def raw_path(link):
    return os.path.join(RAW_DIR, article_key(link) + ".json")


def is_freq_error(err):
    e = (err or "").lower()
    return ("200013" in e or "freq" in e or "200003" in e or "验证" in e or "频繁" in e)


def is_verify_error(err):
    return any(k in (err or "") for k in ("安全验证", "验证码", "环境异常", "请输入图片"))


# ---------------------------------------------------------------------------
# 阶段 L：文章列表
# ---------------------------------------------------------------------------
def list_phase(st, deadline):
    if st.get("list_done"):
        log(f"列表阶段已完成（{st.get('total')} 组）")
        return True

    seen = {norm_link(a["link"]) for a in load_articles()}
    begin = int(st.get("begin") or 0)
    total = int(st.get("total") or 0)
    backoff = 600

    while time.time() < deadline:
        if total and begin >= total:
            st["list_done"] = True
            save_state(st)
            log(f"列表抓取完成：begin={begin} >= total={total}，累计 {len(seen)} 篇")
            return True

        try:
            j = _request("GET", "/api/public/articles",
                         params={"fakeid": FAKEID, "begin": begin, "count": PAGE},
                         timeout=60)
        except Exception as e:
            log(f"列表请求异常：{e} → {backoff // 60} 分钟后重试")
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)
            continue

        if not j.get("success"):
            err = j.get("error") or ""
            if is_freq_error(err):
                log(f"列表被微信限频（{err}）→ {backoff // 60} 分钟后重试（begin={begin}）")
                time.sleep(backoff)
                backoff = min(backoff * 2, 3600)
                continue
            log(f"列表接口错误（{err}）→ 5 分钟后重试")
            time.sleep(300)
            continue

        d = j.get("data") or {}
        arts = d.get("articles") or []
        total = int(d.get("total") or total or 0)
        new = 0
        with open(ARTICLES, "a", encoding="utf-8") as f:
            for a in arts:
                link = norm_link(a.get("link"))
                if not link or link in seen:
                    continue
                seen.add(link)
                f.write(json.dumps({
                    "aid": a.get("aid", ""),
                    "title": a.get("title", ""),
                    "link": link,
                    "publish_time": a.get("update_time") or a.get("create_time") or 0,
                    "author": a.get("author", ""),
                    "digest": a.get("digest", ""),
                }, ensure_ascii=False) + "\n")
                new += 1
        st["total"] = total
        backoff = 600
        log(f"begin={begin} 组：返回 {len(arts)} 篇，新增 {new}，累计 {len(seen)} 篇"
            + (f" / 共 {total} 组" if total else " / 组数未知"))

        if total and begin + PAGE >= total:
            st["list_done"] = True
            st["begin"] = total
            save_state(st)
            log(f"列表抓取完成：累计 {len(seen)} 篇（{total} 组）")
            return True
        if not total and len(arts) < PAGE:
            st["list_done"] = True
            st["begin"] = begin + PAGE
            save_state(st)
            log(f"列表抓取完成（末页不足 {PAGE} 篇判据）：累计 {len(seen)} 篇")
            return True

        begin += PAGE
        st["begin"] = begin
        save_state(st)
        time.sleep(LIST_INTERVAL)

    log("列表阶段未在时限内完成，状态已保存，稍后重跑可续")
    return False


# ---------------------------------------------------------------------------
# 阶段 C：正文
# ---------------------------------------------------------------------------
def save_raw(rec, data):
    payload = {
        "key": article_key(rec["link"]),
        "link": rec["link"],
        "list_title": rec.get("title", ""),
        "list_publish_time": rec.get("publish_time", 0),
        "fetched_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "data": data,
    }
    p = raw_path(rec["link"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, p)
    return p


PERMANENT_MARKS = ("此内容因违规无法查看", "该内容已被发布者删除", "此内容因违规无法查看",
                   "内容已删除", "该公众号已迁移", "此帐号已被屏蔽")
SOFT_MARKS = ("环境异常", "完成验证", "去验证", "频繁", "繁忙", "稍后再试",
              "secitptpage/verify", "PAGE_MID")  # 验证页由 JS 渲染，无文字特征


def _diagnose(url, tag):
    """失败时直连取一次原始页面，判断是「永久失效」还是「临时软限流」。

    返回 "permanent" / "soft" / "unknown"。
    永久失效 = 文章被删或违规（重试无意义，直接跳过）
    软限流   = 环境异常/验证页（退避后重试有意义）
    """
    try:
        from curl_cffi import requests as cfq
        r = cfq.get(url, impersonate="chrome120", timeout=40)
        html = r.text or ""
    except Exception as e:
        log(f"      诊断抓取失败：{e}")
        return "unknown"
    out = os.path.join(DATA_DIR, "diag", f"{tag}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    if any(m in html for m in PERMANENT_MARKS):
        return "permanent"
    if "secitptpage/verify" in html or "PAGE_MID" in html:
        log(f"      诊断页 {len(html)} 字节 → 安全验证页")
        return "verify"
    soft = [m for m in SOFT_MARKS if m in html]
    if soft:
        log(f"      诊断页 {len(html)} 字节 → 软限流标记 {soft}")
        return "soft"
    log(f"      诊断页 {len(html)} 字节 → 无已知标记（unknown）")
    return "unknown"


def content_phase(deadline):
    """抓正文。节奏自适应：连续成功就逐步收窄间隔，出问题就退避并放大间隔。

    2026-11-18 实测：公开文章页在 ~20 次/分钟时会拿到「无正文」的软限流页，
    且错误文案里不含「验证/环境异常」关键词，容易被误判。这里改为指数退避 +
    抓取失败即落盘诊断页，并且失败不阻塞整条队列。
    """
    arts = load_articles()
    if not arts:
        log("列表为空，跳过正文阶段")
        return
    # 断点按稳定身份（mid+idx）判定：link 的 sn 每轮都变，用整条 link 做键会
    # 把存量文章全部重抓一遍；已确认永久失效的也不必每轮重试。
    done, dead = fetched_ids(), failed_ids()
    todo = [a for a in arts
            if stable_id(a["link"]) not in done and stable_id(a["link"]) not in dead]
    log(f"正文阶段：共 {len(arts)} 篇，待抓 {len(todo)} 篇，初始间隔 {CONTENT_INTERVAL}s")

    interval = float(CONTENT_INTERVAL)
    floor = 6.0
    ok_streak = 0
    backoff = 60
    for i, rec in enumerate(todo, 1):
        if time.time() > deadline:
            log("正文阶段到达时限，剩余稍后续跑")
            return
        for attempt in range(4):
            try:
                j = _request("POST", "/api/article", body={"url": rec["link"]}, timeout=180)
            except Exception as e:
                log(f"  [{i}/{len(todo)}] 请求异常 {rec.get('title','')[:20]}：{e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 900)
                continue

            if j.get("success") and (j.get("data") or {}).get("content"):
                save_raw(rec, j["data"])
                log(f"  [{i}/{len(todo)}] OK {rec.get('title','')[:30]}")
                try:
                    render_one(rec, j["data"])
                except Exception as e:
                    log(f"      渲染失败：{e}")
                ok_streak += 1
                # 每 15 篇成功就收窄 1 秒，直到下限。用「成功计数」而不是
                # 「连续成功」——广告/失效篇目会打断连续，导致永远攒不够。
                if ok_streak >= 15 and interval > floor:
                    interval = max(floor, interval - 1)
                    ok_streak = 0
                    log(f"      15 篇成功，间隔收窄到 {interval:.0f}s")
                backoff = 60
                break

            err = j.get("error") or "空正文"
            soft = is_freq_error(err) or "无法获取文章内容" in err
            if soft:
                # 先诊断一次：违规/删除页当场落判，验证页才暂停重试
                kind = _diagnose(rec["link"], article_key(rec["link"]))
                if kind == "permanent":
                    log(f"  [{i}/{len(todo)}] → 违规/删除，永久失效，跳过")
                    with open(FAILED, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"link": rec["link"], "title": rec.get("title", ""),
                                            "reason": "文章被删除/违规，无法查看",
                                            "at": datetime.now(TZ).isoformat(timespec="seconds")},
                                           ensure_ascii=False) + "\n")
                    break
                if kind == "verify":
                    log(f"  [{i}/{len(todo)}] → 安全验证页，整队暂停 {VERIFY_PAUSE_S // 60} 分钟")
                    time.sleep(VERIFY_PAUSE_S)
                    interval = max(interval, 15)
                    continue  # 不消耗 attempt，暂停后接着重试本篇
                # unknown/soft：按软限流退避
                log(f"      → 判定为临时软限流，退避 {backoff}s 后重试")
                time.sleep(backoff)
                backoff = min(backoff * 2, 1800)
                interval = max(interval, 12)
                continue

                if attempt == 0:
                    log(f"  [{i}/{len(todo)}] 取不到正文：{err[:70]}")
                    kind = _diagnose(rec["link"], article_key(rec["link"]))
                    if kind == "permanent":
                        log(f"      → 文章已被删除/违规，永久失效，直接跳过（不重试）")
                        with open(FAILED, "a", encoding="utf-8") as f:
                            f.write(json.dumps({"link": rec["link"], "title": rec.get("title", ""),
                                                "reason": "文章被删除/违规，无法查看",
                                                "at": datetime.now(TZ).isoformat(timespec="seconds")},
                                               ensure_ascii=False) + "\n")
                        break
                    # 验证页 = 队列级风控信号：整队暂停，而不是单篇重试
                    log(f"      → 安全验证页，整队暂停 {args_verify_pause//60} 分钟")
                    time.sleep(VERIFY_PAUSE_S)
                    backoff = 120
                    interval = max(interval, 15)
                    continue
                time.sleep(backoff)
                backoff = min(backoff * 2, 1800)
                interval = max(interval, 12)
                continue

            log(f"  [{i}/{len(todo)}] 失败：{err[:90]}")
            time.sleep(30)
            break
        else:
            with open(FAILED, "a", encoding="utf-8") as f:
                f.write(json.dumps({"link": rec["link"], "title": rec.get("title", ""),
                                    "reason": "4 次重试仍失败",
                                    "at": datetime.now(TZ).isoformat(timespec="seconds")},
                                   ensure_ascii=False) + "\n")
            log(f"  [{i}/{len(todo)}] 放弃并跳过：{rec.get('title','')[:30]}")

        ok_streak = 0
        if i % 10 == 0 or i == len(todo):
            log(f"  进度 {i}/{len(todo)} | 间隔 {interval:.0f}s | raw {len(load_articles())} 篇索引")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# 阶段 R：渲染
# ---------------------------------------------------------------------------
def _safe_title(s):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    if not s:
        s = "无标题"
    return s[:60].rstrip()


def _yaml_str(s):
    return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _download_image(url, referer="https://mp.weixin.qq.com/"):
    if not url or url.startswith("data:"):
        return None
    if url.startswith("//"):
        url = "https:" + url
    ext = ".jpg"
    m = re.search(r"wx_fmt=(\w+)", url)
    if m:
        ext = "." + ("jpg" if m.group(1) == "jpeg" else m.group(1))
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + ext
    dest = os.path.join(IMG_DIR, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return name
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
            ct = (r.headers.get("Content-Type") or "").lower()
        if ct.startswith("image/") and blob:
            if "png" in ct:
                name = name.rsplit(".", 1)[0] + ".png"
                dest = os.path.join(IMG_DIR, name)
            with open(dest, "wb") as f:
                f.write(blob)
            return name
    except Exception:
        return None
    return None


def html_to_md(content_html):
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(content_html, "html.parser")
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        local = _download_image(src) if src else None
        if local:
            img.attrs = {"src": f"_attachments/{local}", "alt": img.get("alt", "")}
        else:
            img.attrs = {"src": src, "alt": img.get("alt", "")}

    text = markdownify(str(soup), heading_style="ATX", bullets="-",
                       strip=["script", "style", "iframe"])
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


AD_MARKERS = ("mp-common-cpsad", "data-adtype=", "new_cps_iframe",
              'data-pluginname="mpcps"')
ADS = os.path.join(DATA_DIR, "ads.jsonl")


def _text_of(html):
    import re as _re
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", html or "")).strip()


def _is_advertisement(html, text=None):
    """广告判定：微信商业推广卡（短剧/小程序/外链）没有正文文字。

    注意：不能用「idx=2」判断——2024-04 的【原创】自发觉醒是正常次条。
    只能按内容判定：有广告标记，或正文几乎无文字。
    """
    if html and any(m in html for m in AD_MARKERS):
        return True
    t = text if text is not None else _text_of(html)
    return len(t) < 10


def _record_ad(rec, reason):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ADS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"link": rec.get("link"), "title": rec.get("title", ""),
                            "reason": reason,
                            "at": datetime.now(TZ).isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")


def _video_cover(html):
    """视频/短剧卡片类文章没有正文，封面图藏在 data-videocarddata 里。"""
    if not html:
        return None
    m = re.search(r'data-videocarddata="([^"]+)"', html)
    if not m:
        return None
    import html as _html
    raw = _html.unescape(m.group(1))
    m2 = re.search(r'"(?:videoCoverUrl|coverUrl)":"([^"]+)"', raw)
    return m2.group(1) if m2 else None


def render_one(rec, data, force=False):
    title = (data.get("title") or rec.get("title") or "无标题").strip()
    ts = data.get("publish_time") or rec.get("publish_time") or 0
    try:
        dt = datetime.fromtimestamp(int(ts), TZ) if ts else datetime.now(TZ)
    except Exception:
        dt = datetime.now(TZ)
    author = data.get("author") or rec.get("author") or NICKNAME

    # 增量：目标 MD 已存在就直接返回，不再转换正文、不再查图片。
    # （原先先转换后判断，等于每轮把全库文章重解析一遍。）
    fname = f"{dt.strftime('%Y%m%d')}_{_safe_title(title)}.md"
    dest = os.path.join(OBSIDIAN_DIR, fname)
    if os.path.exists(dest) and not force:
        return dest

    html = data.get("content") or ""
    body = ""
    if html.strip().startswith("<"):
        body = html_to_md(html)
    if not body.strip():
        body = (data.get("plain_content") or "").strip()

    if _is_advertisement(html, _text_of(html)):
        _record_ad(rec, "微信商业推广卡（无正文）")
        return None

    note = ""
    if not body.strip():
        cover = _video_cover(html)
        if cover:
            local = _download_image(cover)
            if local:
                body = (f"> 本文为视频卡片，无正文文本。封面：\n\n"
                        f"![](_attachments/{local})")
            else:
                body = "> 本文为视频卡片，无正文文本。"
        else:
            body = "> 本文为纯媒体消息（视频/音频/图片分享），无正文文本。"
        note = "media"

    front = "\n".join([
        "---",
        f"title: {_yaml_str(title)}",
        f"author: {_yaml_str(author)}",
        f"date: {_yaml_str(dt.strftime('%Y-%m-%d %H:%M'))}",
        f"source: {_yaml_str(rec['link'])}",
        f"account: {_yaml_str(NICKNAME)}",
        "---",
    ])
    with open(dest, "w", encoding="utf-8") as f:
        f.write(front + "\n\n# " + title + "\n\n" + body + "\n")
    return dest


def ad_ids():
    """已判定为广告的文章（按稳定身份）。判过的就不再渲染，避免反复记账/复活。"""
    ids = set()
    if not os.path.exists(ADS):
        return ids
    with open(ADS, encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            link = record.get("link") or ""
            if link:
                ids.add(stable_id(link))
    return ids


def render_phase(force=False):
    n_new = n_skip = n_bad = n_media = n_ads = 0
    arts = load_articles()
    known_ads = ad_ids()
    for rec in arts:
        p = raw_path(rec["link"])
        if not os.path.exists(p):
            continue
        if stable_id(rec["link"]) in known_ads:
            n_ads += 1
            continue
        try:
            payload = json.load(open(p, encoding="utf-8"))
            data = payload.get("data") or {}
            before = set(os.listdir(OBSIDIAN_DIR)) if os.path.isdir(OBSIDIAN_DIR) else set()
            dest = render_one(rec, data, force=force)
            after = set(os.listdir(OBSIDIAN_DIR))
            if dest is None:
                n_ads += 1
                continue
            base = os.path.basename(dest)
            if base and base in after and (base not in before or force):
                n_new += 1
            else:
                n_skip += 1
            try:
                if "视频卡片" in open(dest, encoding="utf-8").read(4000):
                    n_media += 1
            except Exception:
                pass
        except Exception as e:
            n_bad += 1
            log(f"  渲染失败 {rec.get('title','')[:24]}：{e}")
    log(f"渲染阶段：新增 {n_new} 篇，已存在跳过 {n_skip} 篇，失败 {n_bad} 篇，"
        f"纯媒体卡 {n_media} 篇，广告剔除 {n_ads} 篇")
    return n_new


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
def status():
    arts = load_articles()
    raws = [a for a in arts if os.path.exists(raw_path(a["link"]))]
    mds = 0
    if os.path.isdir(OBSIDIAN_DIR):
        mds = len([f for f in os.listdir(OBSIDIAN_DIR) if f.endswith(".md")])
    imgs = len(os.listdir(IMG_DIR)) if os.path.isdir(IMG_DIR) else 0
    st = load_state()
    print(json.dumps({
        "list_done": st.get("list_done"),
        "groups_begin": st.get("begin"),
        "groups_total": st.get("total"),
        "articles": len(arts),
        "raw_fetched": len(raws),
        "md_in_obsidian": mds,
        "images": imgs,
        "failed": sum(1 for _ in open(FAILED, encoding="utf-8")) if os.path.exists(FAILED) else 0,
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--content-only", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="重渲染：覆盖已存在的 MD")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--max-hours", type=float, default=24.0)
    args = ap.parse_args()

    ensure_dirs()
    if args.status:
        status()
        return

    if args.render_only:
        render_phase(force=args.force)
        return

    deadline = time.time() + args.max_hours * 3600
    st = load_state()
    if not args.content_only:
        if not list_phase(st, deadline):
            return
    if args.list_only:
        return
    content_phase(deadline)
    render_phase(force=args.force)
    status()


if __name__ == "__main__":
    main()
