#!/bin/bash
# 定向劫持 mp.weixin.qq.com：改 hosts + 以 root 启动请求记录器 + 重启微信
# 用法：在 Terminal.app 里运行  bash "/Users/allenwywang/allen个人项目/tools/setup_mp_intercept.sh"
set -u

PROJ="/Users/allenwywang/allen个人项目/project-zhou"
LOGGER="$PROJ/scripts/mp_req_logger.py"
PY="/Users/allenwywang/allen个人项目/tools/schinza/.venv-mac/bin/python"

echo "==> [1/6] 备份 /etc/hosts"
[ -f /etc/hosts.mpbak ] || sudo cp /etc/hosts /etc/hosts.mpbak
echo "    备份在 /etc/hosts.mpbak"

echo "==> [2/6] 写入 hosts 记录"
sudo sh -c "grep -q 'mp.weixin.qq.com' /etc/hosts || printf '\n# 临时：公众号归档抓取用，完工后删除\n127.0.0.1 mp.weixin.qq.com\n' >> /etc/hosts"
grep -n "mp.weixin.qq.com" /etc/hosts

echo "==> [3/6] 停掉旧记录器"
sudo pkill -f mp_req_logger.py 2>/dev/null
sleep 1

echo "==> [4/6] 以 root 启动记录器（需要绑定 80/443）"
sudo nohup "$PY" "$LOGGER" 80 443 > /tmp/mp_req_logger.log 2>&1 &
sleep 4

echo "==> [5/6] 监听状态"
sudo lsof -nP -iTCP:80 -iTCP:443 -sTCP:LISTEN 2>/dev/null | head -5
echo "--- 记录器日志 ---"
sudo tail -6 /tmp/mp_req_logger.log

echo "==> [6/6] 清 DNS 缓存并重启微信"
sudo dscacheutil -flushcache 2>/dev/null
sudo killall -u "$USER" mDNSResponder 2>/dev/null
pkill -x WeChat 2>/dev/null
sleep 4
open -a WeChat
sleep 6
pgrep -x WeChat >/dev/null && echo "    微信已重启" || echo "    ⚠️ 微信未启动，请手动打开"

echo
echo "==> 完成。请在微信里点开公众号文章（内置浏览器），然后回来告诉 Claude。"
echo "    卸载方法：sudo cp /etc/hosts.mpbak /etc/hosts && sudo dscacheutil -flushcache"
