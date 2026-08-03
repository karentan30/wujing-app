# 舞镜 紧急回滚SOP

> 生产出问题时2分钟内完成回滚

---

## 快速健康检查

```bash
ssh root@47.242.80.65 "systemctl status wujing-api && curl -s http://localhost:3006/health"
```

预期输出：`{"ok": true, "service": "wujing-api"}`

---

## 一、前端回滚（HTML改坏了）

```bash
# 本机操作
cd ~/projects/舞镜/_live

# 查看最近提交
git log --oneline -5

# 回滚到上一个稳定版
git checkout HEAD~1 design-upgrade.html

# 部署到服务器
scp design-upgrade.html root@47.242.80.65:/www/wujing-api/_live/design-upgrade.html
```

验证：`curl -s https://wujing.mylumee.app | grep "舞镜"`

---

## 二、后端回滚（Python崩了）

```bash
# 登服务器
ssh root@47.242.80.65

# 查看日志找根因
journalctl -u wujing-api -n 50 --no-pager

# 回滚代码（本机git管理，或手动恢复）
cd /www/wujing-api

# 重启服务
systemctl restart wujing-api

# 验证
sleep 3 && curl -s http://localhost:3006/health
```

---

## 三、服务器彻底崩（systemd死了）

```bash
ssh root@47.242.80.65 "cd /www/wujing-api && source venv/bin/activate && nohup uvicorn server:app --host 0.0.0.0 --port 3006 &"
```

---

## 四、数据库损坏

```bash
ssh root@47.242.80.65

# 检查WAL完整性
cd /www/wujing-api
sqlite3 wujing.db "PRAGMA integrity_check"

# 从备份恢复（备份在 /www/wujing-api/backups/）
ls -lt backups/ | head -5
cp backups/wujing_YYYYMMDD_HHMMSS.db wujing.db
systemctl restart wujing-api
```

---

## 五、付款回调失联（微信/支付宝通知不到）

1. 检查服务器公网可达：`curl https://wujing.mylumee.app/api/pay/health`
2. 检查Caddy状态：`systemctl status caddy`
3. 如Caddy崩：`systemctl restart caddy`
4. 手动补履约（紧急）：
   ```bash
   sqlite3 /www/wujing-api/wujing.db \
     "UPDATE orders SET status='paid' WHERE out_trade_no='xxx'"
   ```

---

## 六、WJ_FREE_MODE紧急开关

前端 design-upgrade.html 顶部：
```js
const WJ_FREE_MODE = true;  // 改true关闭付费门（紧急绕过）
```

---

## 回滚后验证清单

- [ ] `/health` 返回 `{"ok":true}`
- [ ] 首页正常加载
- [ ] 上传视频不报错
- [ ] 登录注册流程通
- [ ] 付款入口显示正常

---

## 联系

服务器：`root@47.242.80.65`  
前端地址：`/www/wujing-api/_live/design-upgrade.html`  
后端地址：`/www/wujing-api/server.py`  
数据库：`/www/wujing-api/wujing.db`
