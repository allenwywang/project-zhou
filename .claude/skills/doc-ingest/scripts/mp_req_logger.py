#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mp.weixin.qq.com 请求记录器（定向劫持用）

用途：微信 Mac 桌面端**不跟随 macOS 系统代理**，所以 mitmproxy 的常规抓包拿不到
      `profile_ext?action=getmsg` 这类带 uin/key/pass_ticket 的请求。
      本工具配合 /etc/hosts 把 mp.weixin.qq.com 指到 127.0.0.1，在本机终结请求、
      把完整 URL 记下来，再原样转发到真实上游。

监听：
    :80   明文 HTTP（微信对 mp 走的就是 80）
    :443  HTTPS（用 mitmproxy CA 终结，兜底 WeChat 改走 TLS 的情况）

日志：每条请求写一行 JSON 到 data/wechat_archive/mp_requests.jsonl
      命中带 __biz/uin/key 的请求会实时打印提示。
"""

import json
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler

LOG_PATH = os.environ.get(
    "MP_REQ_LOG",
    os.path.join(os.environ.get("DOC_INGEST_WORKDIR",
                 os.path.join(os.path.expanduser("~"), ".doc-ingest")),
                "data", "wechat_archive", "mp_requests.jsonl"),
)
CA_PEM = os.path.expanduser("~/.mitmproxy/mitmproxy-ca.pem")

# 真实上游 IP（绕过被改写的 /etc/hosts，直连 IP 并带原始 Host/SNI）
UPSTREAM_IPS = [
    "101.91.22.114", "101.227.133.172", "101.91.40.80",
    "101.89.49.42", "61.151.226.28", "101.89.49.171",
]
UPSTREAM_HOST = "mp.weixin.qq.com"

CRED_KEYS = ("__biz", "uin", "key", "pass_ticket", "appmsg_token")
_lock = threading.Lock()

# 需要覆盖的域名（用于签发叶子证书的 SAN）
LEAF_NAMES = ["mp.weixin.qq.com", "mpv6.weixin.qq.com", "sz.mp.weixin.qq.com"]
LEAF_DIR = os.path.dirname(CA_PEM)
LEAF_KEY = os.path.join(LEAF_DIR, "mp-leaf.key")
LEAF_CRT = os.path.join(LEAF_DIR, "mp-leaf.crt")


def ensure_leaf_cert():
    """用 mitmproxy CA 签一张 mp.weixin.qq.com 的叶子证书。

    直接把 CA 证书当服务端证书端出来会被客户端拒（签发者名与主机名不符），
    必须由 CA 签发 SAN 正确��叶子证书，客户端才能验签通过。
    """
    if os.path.exists(LEAF_KEY) and os.path.exists(LEAF_CRT):
        return LEAF_CRT, LEAF_KEY

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime

    blob = open(CA_PEM, "rb").read().decode()
    key_pem = blob[blob.index("-----BEGIN"):]
    cert_pem = blob[blob.index("-----BEGIN CERTIFICATE-----"):]
    ca_key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    ca_cert = x509.load_pem_x509_certificate(cert_pem.encode())

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "mp.weixin.qq.com"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "mitmproxy"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in LEAF_NAMES]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    with open(LEAF_KEY, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(LEAF_CRT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(LEAF_KEY, 0o600)
    print(f"[cert] leaf generated: {LEAF_CRT}", flush=True)
    return LEAF_CRT, LEAF_KEY


def log_line(obj):
    with _lock:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def has_creds(path):
    return any(k in path for k in ("key=", "pass_ticket=", "appmsg_token="))


def _relay(sock):
    chunks = []
    while True:
        b = sock.recv(65536)
        if not b:
            break
        chunks.append(b)
    data = b"".join(chunks)
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = lines[0] if lines else b"HTTP/1.1 200 OK"
    hdrs = b"\r\n".join(lines[1:])
    return status, hdrs, body


def forward(raw_req: bytes, host_header: str, tls: bool):
    """把原始请求转发到上游，返回 (status_line, headers_bytes, body_bytes)。

    tls=False → 上游走明文 80；tls=True → 上游走 TLS 443（SNI 用原 Host）。
    """
    last_err = None
    for ip in UPSTREAM_IPS:
        sock = None
        try:
            if tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                raw = socket.create_connection((ip, 443), timeout=25)
                sock = ctx.wrap_socket(raw, server_hostname=UPSTREAM_HOST)
            else:
                sock = socket.create_connection((ip, 80), timeout=25)
            sock.sendall(raw_req)
            out = _relay(sock)
            try:
                sock.close()
            except Exception:
                pass
            return out
        except Exception as e:
            last_err = e
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            continue
    raise last_err or RuntimeError("upstream unreachable")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MPLogger/1.0"

    def log_message(self, *a):
        pass

    def _handle(self):
        raw_path = self.path
        # 组装要转发的原始请求
        body_len = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(body_len) if body_len else b""

        req_lines = [f"{self.command} {raw_path} HTTP/1.1".encode()]
        headers = {k: v for k, v in self.headers.items()}
        headers["Connection"] = "close"
        for k, v in headers.items():
            req_lines.append(f"{k}: {v}".encode())
        raw_req = b"\r\n".join(req_lines) + b"\r\n\r\n" + body

        rec = {
            "ts": time.time(),
            "method": self.command,
            "path": raw_path,
            "host": headers.get("Host", UPSTREAM_HOST),
            "ua": headers.get("User-Agent", ""),
            "creds": has_creds(raw_path),
            "tls": bool(getattr(self.server, "is_tls", False)),
        }
        log_line(rec)
        if rec["creds"]:
            print(f"[CREDS-HIT] {self.command} {raw_path[:300]}", flush=True)
        else:
            print(f"[req] {self.command} {raw_path[:120]}", flush=True)

        try:
            status, hdrs, rbody = forward(raw_req, rec["host"],
                                          tls=bool(getattr(self.server, "is_tls", False)))
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()
            print(f"[UPSTREAM-FAIL] {e}", flush=True)
            return

        # 改写 Connection 并保留其余头
        out_hdrs = []
        for line in hdrs.split(b"\r\n"):
            if not line:
                continue
            low = line.lower()
            if low.startswith(b"connection:") or low.startswith(b"content-length:"):
                continue
            if low.startswith(b"transfer-encoding:"):
                continue
            out_hdrs.append(line)
        out_hdrs.append(b"Connection: close")
        out_hdrs.append(b"Content-Length: " + str(len(rbody)).encode())

        self.wfile.write(status + b"\r\n" + b"\r\n".join(out_hdrs) + b"\r\n\r\n" + rbody)
        self.wfile.flush()

    do_GET = _handle
    do_POST = _handle
    do_HEAD = _handle


def serve_http(port):
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[http] listening on :{port}", flush=True)
    srv.serve_forever()


def serve_https(port):
    crt, key = ensure_leaf_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    ctx.set_alpn_protocols(["http/1.1"])
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.is_tls = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"[https] listening on :{port} (leaf cert for {LEAF_NAMES[0]})", flush=True)
    srv.serve_forever()


def main():
    # 参数格式： "80" 或 "443" 或 "18443:tls"
    specs = sys.argv[1:] or ["80", "443"]
    for spec in specs:
        port_s, _, mode = spec.partition(":")
        port = int(port_s)
        use_tls = mode == "tls" or port == 443
        threading.Thread(target=serve_https if use_tls else serve_http,
                         args=(port,), daemon=True).start()
    print(f"ready, upstream={UPSTREAM_HOST} ips={UPSTREAM_IPS}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
