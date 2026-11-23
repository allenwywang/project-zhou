#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周先生的茶馆四代目 —— 客户端凭据通道 全量抓取（Schinza 无 GUI 驱动）

背景：微信自 2026-07-30 起关闭了公众号后台「跨号文章列表」接口（ret=200013），
      唯一能拿到全量 URL 列表的免费通道是「微信桌面客户端凭据 + profile_ext?action=getmsg」。

流程：
  1. 启动 Schinza 的 mitmproxy 抓包代理（127.0.0.1:8088）并开启系统代理
  2. 用户在「微信桌面端」用内置浏览器打开目标公众号任一文章 → 自动捕获
     __biz / uin / key / pass_ticket（30 分钟 TTL）
  3. 用捕获到的凭据分页拉取全量历史（getmsg，count 按推送数计）
  4. 落盘 articles.jsonl，随后由 wechat_archive.py --content-only 抓正文并渲染进 Obsidian

用法：
    python3 wechat_client_fetch.py capture     # 启动抓取并等待凭据（最长 10 分钟）
    python3 wechat_client_fetch.py fetch       # 用已保存凭据拉全量列表
    python3 wechat_client_fetch.py status
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

SCHINZA_ROOT = Path(os.environ.get("SCHINZA_ROOT", "/Users/allenwywang/allen个人项目/tools/schinza")).resolve()
sys.path.insert(0, str(SCHINZA_ROOT))

WORK_ROOT = Path(os.environ.get("DOC_INGEST_WORKDIR", Path.home() / ".doc-ingest")).expanduser()
DATA_DIR = WORK_ROOT / "data" / "wechat_archive"
RAW_DIR = DATA_DIR / "raw"
ARTICLES = DATA_DIR / "articles.jsonl"
STATE = DATA_DIR / "state.json"
CREDS = DATA_DIR / "client_creds.json"
CAPTURE_LOG = DATA_DIR / "capture.log"

TARGET_BIZ = os.environ.get("TEA_BIZ", "MzkyNzUxNDUzNA==")
ACCOUNT = os.environ.get("TEA_NICKNAME", "周先生的茶馆四代目")
CAPTURE_WAIT = int(os.environ.get("CAPTURE_WAIT", "600"))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def article_key(link):
    """文章的稳定身份：mid+idx。

    微信的 link 带 sn / chksm / key 等运行期参数，同一篇文章在不同轮抓取里
    link 字符串不同，按 link 去重会漏判；mid+idx 才是跨轮稳定的标识。
    解析不出时退回 link 本身。
    """
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    except Exception:
        return link
    mid = (query.get("mid") or [""])[0]
    idx = (query.get("idx") or [""])[0]
    if mid and idx:
        return f"{mid}:{idx}"
    return link


def ensure_dirs():
    for d in (DATA_DIR, RAW_DIR):
        d.mkdir(parents=True, exist_ok=True)


def save_creds(cred):
    payload = {k: v for k, v in cred.items()
               if k in ("__biz", "uin", "key", "pass_ticket", "appmsg_token",
                        "wxtoken", "user_agent", "devicetype", "clientversion")}
    tmp = CREDS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CREDS)
    return payload


def load_creds():
    if not CREDS.exists():
        return None
    try:
        return json.loads(CREDS.read_text(encoding="utf-8"))
    except Exception:
        return None


def cmd_capture(args):
    """启动抓包代理，等待用户在微信桌面端打开文章。"""
    from app.mitm_capture import MitmCaptureService

    ensure_dirs()
    svc = MitmCaptureService(SCHINZA_ROOT)
    ok, msg = svc.start(set_system_proxy=True)
    log(msg)
    if not ok:
        return 1

    log(f"请在【微信桌面端】用内置浏览器打开「{ACCOUNT}」的任意一篇文章"
        f"（如果已打开，滚动一下历史消息页），凭据会被自动捕获。")
    log(f"等待最长 {CAPTURE_WAIT} 秒…")

    deadline = time.time() + CAPTURE_WAIT
    found = None
    try:
        while time.time() < deadline:
            for c in svc.read_new_credentials():
                if c.get("__biz") == TARGET_BIZ and c.get("key"):
                    found = c
                    break
                if c.get("__biz") and c.get("key"):
                    log(f"捕获到其他号凭据 {c.get('__biz')}，继续等待目标号…")
            if found:
                break
            time.sleep(2)
    finally:
        ok2, msg2 = svc.stop(restore_proxy=True)
        log(f"抓包停止：{msg2}")

    if not found:
        log("未捕获到目标公众号凭据。可用 --manual 手动粘贴，或重试。")
        return 2

    save_creds(found)
    log(f"[OK] 已捕获 {ACCOUNT} 凭据，保存到 {CREDS}")
    log("下一步：python3 wechat_client_fetch.py fetch")
    return 0


def _patch_dns_bypass_hosts():
    """把 mp.weixin.qq.com 直连真实 IP，绕开 /etc/hosts 的劫持记录。

    抓包阶段我们把域名指向 127.0.0.1 以记录请求；抓取阶段必须回到真实上游，
    否则会打进本机记录器导致 TLS 校验失败。这里在进程内改写解析结果，
    不需要再动系统文件（也就不用再输一次 sudo 密码）。
    """
    import socket

    REAL_IPS = ["101.91.22.114", "101.227.133.172", "101.91.40.80",
                "101.89.49.42", "61.151.226.28", "101.89.49.171"]
    target = "mp.weixin.qq.com"
    orig = socket.getaddrinfo

    def patched(host, port, *a, **k):
        if host == target:
            return orig(REAL_IPS[0], port, *a, **k)
        return orig(host, port, *a, **k)

    socket.getaddrinfo = patched
    log(f"已启用 DNS 旁路：{target} → {REAL_IPS[0]}")


def cmd_fetch(args):
    from app.history_client import fetch_history_days, is_rate_limit_error

    ensure_dirs()
    cred = load_creds()
    if not cred:
        log("没有已保存的凭据，先跑 capture。")
        return 2

    log(f"开始拉取 {ACCOUNT} 全量历史")
    _patch_dns_bypass_hosts()
    log(f"  节奏：count={args.count} 间隔={args.sleep}s(±{args.jitter:.0%}) "
        f"每 {args.cooldown_every} 页冷却 {args.cooldown_extra}s 上限 {args.max_pages} 页")
    log(f"  预计 {args.max_pages * args.sleep / 60:.0f} 分钟内完成；遇风控立即停止")

    since_days = getattr(args, "since_days", 0) or 0
    full = bool(getattr(args, "full", False))
    if since_days > 0:
        days = since_days
        log(f"增量模式：只翻最近 {since_days} 天（页面全早于该范围即停）")
    elif full:
        days = None                     # None = 全部
        log("[WARN] 全量模式：翻到空页为止（106 页/约 18 分钟，风控与配额成本最高）")
    else:
        log("[拒绝] 默认只同步增量：全量拉取需要显式 --full，且必须先与用户二次确认。")
        log("        增量用法：fetch --since-days 30（只翻最近 30 天）")
        log("        全量用法：fetch --full   ← 执行前须向用户说明代价并得到明确确认")
        return 2
    t0 = time.time()
    result = fetch_history_days(
        cred,
        days=days,
        max_pages=args.max_pages,
        count=args.count,
        sleep_s=args.sleep,
        sleep_jitter=args.jitter,
        cooldown_every=args.cooldown_every,
        cooldown_extra_s=args.cooldown_extra,
        on_progress=lambda *a, **k: log(f"  进度 {a if a else k}"),
    )

    arts = result.get("articles") or []
    err = result.get("error") or ""
    log(f"结果 ok={result.get('ok')} 错误={err or '无'} "
        f"页数={result.get('pages')} 文章数={len(arts)} "
        f"停止原因={result.get('stopped_reason')} 耗时={time.time() - t0:.0f}s")

    if err and is_rate_limit_error(err):
        log("!! 触发微信风控，已停止。已抓到的部分照常落盘。")
        log("!! 建议停手数小时到一天后再用同一个小号重试，不要连续重试。")

    if not arts:
        return 3

    records = []
    if ARTICLES.exists():
        for line in ARTICLES.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("link"):
                records.append(record)
    # 同一篇文章在不同轮抓取里 link 的 sn 等运行期参数会变，按 link 去重会漏判，
    # 索引里就会出现同一篇的重复记录。用 mid+idx 这个稳定身份归并。
    by_key = {}
    for record in records:
        by_key[article_key(record["link"])] = record
    seen = set(by_key)
    merged = list(by_key.values())
    new = 0
    for a in arts:
        link = a.get("link") or a.get("url") or ""
        if not link:
            continue
        key = article_key(link)
        if key in seen:
            continue
        seen.add(key)
        merged.append({
            "aid": a.get("aid", ""),
            "title": a.get("title", ""),
            "link": link,
            "publish_time": a.get("publish_ts") or a.get("publish_time") or 0,
            "author": a.get("author", ""),
            "digest": a.get("digest", ""),
        })
        new += 1
    temporary = ARTICLES.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as f:
        for record in merged:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(ARTICLES)
    dropped = len(records) - len(by_key)
    log(f"[OK] 写入 articles.jsonl：新增 {new}，累计 {len(seen)}"
        + (f"（归并重复记录 {dropped} 条）" if dropped else ""))

    st = {}
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            st = {}
    st["list_done"] = True
    st["list_source"] = "client_getmsg"
    st["total_articles"] = len(seen)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def cmd_extract(args):
    """从 mp_req_logger 记录的 URL 里提取客户端凭据（uin/key/pass_ticket）。"""
    import urllib.parse

    log_path = Path(os.environ.get(
        "MP_REQ_LOG",
        str(DATA_DIR / "mp_requests.jsonl")))
    if not log_path.exists():
        log(f"没有记录文件：{log_path}")
        return 2

    best = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        path = rec.get("path") or ""
        if TARGET_BIZ not in path:
            continue
        q = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        cred = {k: (v[0] if v else "") for k, v in q.items()}
        if not (cred.get("__biz") and cred.get("uin") and cred.get("key")):
            continue
        cred["__biz"] = cred.get("__biz") or TARGET_BIZ
        cred["user_agent"] = rec.get("ua") or ""
        cred["pass_ticket"] = cred.get("pass_ticket", "")
        best = cred

    if not best:
        log(f"记录文件里没找到带凭据的请求（需含 __biz={TARGET_BIZ} 且带 uin/key）")
        log("请确认：① 已运行 setup_mp_intercept.sh ② 微信已切到小号 ③ 已点开文章")
        return 3

    save_creds(best)
    log(f"[OK] 已提取凭据：__biz={best.get('__biz')} uin={best.get('uin')} "
        f"key={best.get('key','')[:8]}… pass_ticket={'有' if best.get('pass_ticket') else '无'}")
    log("下一步：python3 wechat_client_fetch.py fetch")
    return 0


def cmd_status(args):
    from app.history_client import validate_credentials
    cred = load_creds()
    info = {"creds_file": str(CREDS), "has_creds": bool(cred)}
    if cred:
        ok, err = validate_credentials(cred)
        info["cred_valid"] = ok
        info["cred_error"] = err
        info["biz"] = cred.get("__biz")
    if ARTICLES.exists():
        info["articles"] = sum(1 for _ in ARTICLES.open(encoding="utf-8"))
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture"); c.set_defaults(fn=cmd_capture)
    x = sub.add_parser("extract"); x.set_defaults(fn=cmd_extract)
    f = sub.add_parser("fetch")
    f.add_argument("--max-pages", type=int, default=250)
    f.add_argument("--since-days", type=int, default=0,
                   help="增量：只翻最近 N 天。翻页到页面全部早于 N 天前即停")
    f.add_argument("--full", action="store_true",
                   help="全量拉取（默认禁止）：106 页/约 18 分钟，须先与用户二次确认")
    f.add_argument("--count", type=int, default=10)       # 客户端原生值，最不显眼
    f.add_argument("--sleep", type=float, default=4.5)    # 拉长间隔，降低风控概率
    f.add_argument("--jitter", type=float, default=0.25)
    f.add_argument("--cooldown-every", type=int, default=4)
    f.add_argument("--cooldown-extra", type=float, default=20.0)
    f.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
