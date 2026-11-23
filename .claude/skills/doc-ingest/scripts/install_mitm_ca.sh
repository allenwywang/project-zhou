#!/bin/bash
# 安装 mitmproxy CA 到系统钥匙串并验证信任是否真正生效。
# 用法：在 Terminal.app 里运行  bash /Users/allenwywang/allen个人项目/tools/install_mitm_ca.sh
set -u

CER="$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
SHA1="74F5C6AB197FE900648CF8570D7058CB4224D64C"
PY="/Users/allenwywang/allen个人项目/tools/schinza/.venv-mac/bin/python"

echo "==> 证书: $CER"
[ -f "$CER" ] || { echo "!! 找不到证书文件，先启动一次 mitmdump 生成"; exit 1; }

echo "==> 清理登录钥匙串里的旧副本（避免与系统副本冲突）"
security delete-certificate -Z "$SHA1" "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null || true

echo "==> 安装到系统钥匙串（需要管理员密码）"
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CER"
rc=$?
if [ $rc -ne 0 ]; then
  echo "!! 安装失败 rc=$rc —— 请把上面几行错误原样贴给 Claude"
  exit $rc
fi

echo "==> 验证：系统钥匙串中是否存在"
security find-certificate -a -c mitmproxy -Z /Library/Keychains/System.keychain 2>&1 | grep -E "SHA-1 hash|labl" | head -4

echo "==> 验证：走代理 + 系统默认信任库实测"
nohup "/Users/allenwywang/allen个人项目/tools/schinza/.venv-mac/bin/mitmdump" \
      --listen-host 127.0.0.1 --listen-port 8088 --set block_global=false \
      > /tmp/mitm_ca_check.log 2>&1 &
sleep 5
"$PY" - <<'PYEOF'
import urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({'https': 'http://127.0.0.1:8088'}))
try:
    r = op.open('https://mp.weixin.qq.com/s/BkpRQIcrpgQcs2-jFszoQQ', timeout=25)
    print('✅ 信任已生效 —— 走代理 HTTPS 成功:', r.status)
except Exception as e:
    print('❌ 仍未生效:', type(e).__name__, str(e)[:160])
PYEOF
pkill -f "mitmdump" 2>/dev/null
echo "==> 验证结束"
