#!/bin/bash
# 收尾：还原 hosts / 停记录器 / 删除 MITM CA / 重启微信
# 用法：在 Terminal.app 里运行  bash "/Users/allenwywang/allen个人项目/tools/cleanup_mp_intercept.sh"
set -u

SHA1="74F5C6AB197FE900648CF8570D7058CB4224D64C"

echo "==> [1/5] 还原 /etc/hosts"
if [ -f /etc/hosts.mpbak ]; then
  sudo cp /etc/hosts.mpbak /etc/hosts
  echo "    已从 /etc/hosts.mpbak 还原"
else
  sudo sh -c "grep -v '公众号归档抓取用' /etc/hosts | grep -v '^127.0.0.1 mp.weixin.qq.com$' > /tmp/hosts.new && cat /tmp/hosts.new > /etc/hosts"
  echo "    无备份，已用过滤方式移除劫持行"
fi
grep -n "mp.weixin.qq.com" /etc/hosts || echo "    hosts 中已无劫持记录"

echo "==> [2/5] 清理 DNS 缓存"
sudo dscacheutil -flushcache 2>/dev/null
sudo killall -u "$USER" mDNSResponder 2>/dev/null
echo "    完成"

echo "==> [3/5] 停止请求记录器"
sudo pkill -f mp_req_logger.py 2>/dev/null && echo "    已停止" || echo "    未在运行"

echo "==> [4/5] 删除 MITM CA 信任根"
sudo security delete-certificate -Z "$SHA1" /Library/Keychains/System.keychain 2>&1 | head -2
if security find-certificate -a -c mitmproxy -Z /Library/Keychains/System.keychain 2>/dev/null | grep -q "SHA-1 hash"; then
  echo "    ⚠️ 系统钥匙串中仍有证书，请把上面的报错贴给 Claude"
else
  echo "    ✅ 已从系统钥匙串移除"
fi

echo "==> [5/5] 重启微信（让它重新解析域名）"
pkill -x WeChat 2>/dev/null
sleep 4
open -a WeChat
sleep 5
pgrep -x WeChat >/dev/null && echo "    微信已启动" || echo "    ⚠️ 微信未启动，请手动打开"

echo
echo "==> 收尾完成。当前状态："
echo "    hosts: $(grep -c 'mp.weixin.qq.com' /etc/hosts) 条劫持记录"
echo "    CA:   $(security find-certificate -a -c mitmproxy -Z /Library/Keychains/System.keychain 2>/dev/null | grep -c 'SHA-1 hash') 份（0=已清除）"
echo "    系统代理: $(networksetup -getsecurewebproxy 'Wi-Fi' | sed -n 's/^Enabled: //p')"
