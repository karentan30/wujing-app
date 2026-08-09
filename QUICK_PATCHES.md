# 舞镜 P0 修复 - 快速补丁 (Copy & Paste)

## 最小化修复（如果时间紧张，优先做这些）

### 必做 #1：移除视频 autoplay（1 行改动）

**文件：** `_live/design-upgrade.html` 第 4574 行

```bash
# 命令行快速修复
sed -i '' 's/<video id="dcPracticeVideo" autoplay/<video id="dcPracticeVideo"/g' design-upgrade.html
```

或手动编辑：
```html
<!-- 查找 -->
<video id="dcPracticeVideo" autoplay loop playsinline controls></video>

<!-- 改为 -->
<video id="dcPracticeVideo" loop playsinline controls></video>
```

**测试：**
```javascript
// Console 中验证
var vid = document.getElementById('dcPracticeVideo');
console.log(vid.hasAttribute('autoplay')); // 应显示 false
```

---

### 必做 #2：修复 dcPracticeRender() 函数

**文件：** `_live/design-upgrade.html` 第 4595 行附近

**查找以下代码段：**
```javascript
vid.load();
vid.play().catch(function(){
  // fallback to regular clip at 0.5x
  vid.src=normSrc; vid.playbackRate=0.5; vid.load(); vid.play().catch(function(){
    vid.style.display='none';
    var msg=document.createElement('div');
    msg.className='dc-practice-no-clip';
    msg.textContent='视频加载失败，请稍后重试';
    top.appendChild(msg);
  });
});
```

**替换为：**
```javascript
vid.load();
var playPromise = vid.play();
if (playPromise !== undefined) {
  playPromise
    .then(function() {
      console.log('[Video] 播放成功');
    })
    .catch(function(err) {
      console.warn('[Video] 播放失败，尝试降级', err);
      vid.src = normSrc;
      vid.playbackRate = 0.5;
      vid.load();
      var fallback = vid.play();
      if (fallback !== undefined) {
        fallback.catch(function(err2) {
          console.warn('[Video] 降级失败', err2);
          vid.style.display = 'none';
          var msg = document.createElement('div');
          msg.className = 'dc-practice-no-clip';
          msg.textContent = '视频加载失败，请稍后重试';
          top.appendChild(msg);
        });
      }
    });
}
```

---

### 必做 #3：添加前端超时保护

**文件：** `_live/design-upgrade.html` `</head>` 前

在 `</head>` 标签前添加（紧贴 PostHog 初始化后）：

```html
<script>
/* ═══ 快速修复：Fetch 超时保护 ═══ */
var _FETCH_TIMEOUT = 10000;
function _withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise(function(_, reject) {
      setTimeout(function() {
        reject(new Error('网络超时，请检查连接'));
      }, ms);
    })
  ]);
}
var _origFetch = window.fetch;
window.fetch = function(url, opts) {
  opts = opts || {};
  try {
    var dev = localStorage.getItem('wj_device_id');
    if (dev) {
      if (!opts.headers) opts.headers = {};
      if (!opts.headers['X-Device-Id']) opts.headers['X-Device-Id'] = dev;
    }
  } catch (e) {}
  return _withTimeout(_origFetch(url, opts), _FETCH_TIMEOUT).catch(function(err) {
    if (err.message && err.message.indexOf('超时') !== -1) {
      console.warn('[Fetch Timeout]', url);
      if (typeof toast === 'function') toast('⏱ ' + err.message);
    }
    throw err;
  });
};

/* ═══ 全局错误处理 ═══ */
window.onerror = function(message, source, lineno, colno, error) {
  console.error('[JS Error]', message);
  if (message && (message.indexOf('Cannot read') !== -1 || message.indexOf('is not a function') !== -1)) {
    if (typeof toast === 'function') toast('⚠️ 应用遇到问题，请刷新重试');
  }
  return true;
};
window.onunhandledrejection = function(event) {
  console.error('[Unhandled Promise]', event.reason);
  event.preventDefault();
};

/* ═══ 页面卸载清理 ═══ */
window.addEventListener('beforeunload', function() {
  try {
    document.querySelectorAll('video, audio').forEach(function(el) {
      el.pause();
      el.src = '';
    });
  } catch (e) {}
});
</script>
</head>
```

---

### 必做 #4：后端添加超时中间件

**文件：** `_live/server.py` 导入部分（最上面）

确保有这些导入：
```python
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
```

**添加位置：** `app.add_middleware(CORSMiddleware, ...)` 之后（约 84 行）

```python
@app.middleware("http")
async def global_timeout_middleware(request: Request, call_next):
    """全局超时保护"""
    try:
        response = await asyncio.wait_for(call_next(request), timeout=30.0)
        return response
    except asyncio.TimeoutError:
        print(f"[Timeout] {request.url.path}")
        return JSONResponse(
            status_code=504,
            content={"error": "API 请求超时，请重试"}
        )
```

---

### 必做 #5：生图防烧钱

**文件：** `_live/server.py` 变量定义部分（约 30-50 行）

在 `_FREE_LIMIT` 定义后添加：
```python
_bg_daily_limit = {}
_BG_LIMIT = {"per_day": 10}
```

**找到** `/api/generate-bg` **端点，改为：**
```python
@app.post("/api/generate-bg")
async def generate_background(request: Request):
    # 验证登录
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return JSONResponse(status_code=401, content={"error": "需要登录"})
    
    user_id = decode_token(token)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "登录过期"})
    
    # 检查配额
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    quota_key = f"bg:{user_id}:{today}"
    daily_count = _bg_daily_limit.get(quota_key, 0)
    
    if daily_count >= _BG_LIMIT["per_day"]:
        return JSONResponse(status_code=429, content={
            "error": "今日生图配额已用完（10张/天），明天再来"
        })
    
    _bg_daily_limit[quota_key] = daily_count + 1
    
    # 继续原有逻辑...
    # ... rest of the function ...
```

---

## 最小化测试清单

部署后必须验证这些：

### 前端测试 (2 分钟)

```javascript
// 打开 Console，逐个运行

// 1. 验证超时保护
console.log('超时设置:', _FETCH_TIMEOUT); // 应显示 10000

// 2. 验证错误处理
console.log('onerror 已启用:', typeof window.onerror === 'function'); // true

// 3. 验证 Promise 保护
Promise.reject(new Error('test'))
  .catch(function() {
    console.log('Promise 保护正常');
  });

// 4. 验证视频标签
var vid = document.getElementById('dcPracticeVideo');
console.log('autoplay 已移除:', !vid.hasAttribute('autoplay')); // true
```

### 后端测试 (2 分钟)

```bash
# 1. 测试 API 超时（应在 30 秒后返回 504）
timeout 35 curl http://localhost:8000/api/decompose \
  -F "file=@test.mp4" \
  -F "title=Test"

# 2. 测试生图配额（应在第 11 次返回 429）
for i in {1..11}; do
  curl -X POST http://localhost:8000/api/generate-bg \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"prompt":"test"}' \
    -s | grep -o '"error"' && echo "Failed at request $i" || echo "OK $i"
done
```

---

## 快速部署脚本

```bash
#!/bin/bash
# 将此脚本保存为 deploy-p0-fixes.sh，chmod +x 后运行

set -e

cd /Users/karen/projects/舞镜/_live

echo "📋 开始部署 P0 修复..."

# 1. 备份
echo "✓ 备份原文件..."
cp design-upgrade.html design-upgrade.html.backup.$(date +%s)
cp server.py server.py.backup.$(date +%s)

# 2. 前端修复
echo "✓ 修复前端..."
sed -i '' 's/<video id="dcPracticeVideo" autoplay/<video id="dcPracticeVideo"/g' design-upgrade.html

# 3. 后端修复（假设已手动编辑 server.py）
echo "✓ 后端修复已手动完成（请参考文档）"

# 4. 重启服务
echo "✓ 重启服务..."
systemctl restart wujing

# 5. 验证
echo "✓ 验证..."
sleep 2
curl -s http://localhost:8000/api/health && echo "✅ 服务正常" || echo "❌ 服务异常"

echo "✅ 部署完成！"
echo "📊 请查看 PostHog 监控错误率变化"
echo "📖 详细文档见 PERFORMANCE_FIXES_P0.md"
```

保存并运行：
```bash
chmod +x deploy-p0-fixes.sh
./deploy-p0-fixes.sh
```

---

## 紧急回滚脚本

```bash
#!/bin/bash
# 将此脚本保存为 rollback-p0-fixes.sh

set -e

cd /Users/karen/projects/舞镜/_live

echo "⚠️ 开始回滚 P0 修复..."

# 找最新的备份
LATEST_HTML=$(ls -t design-upgrade.html.backup.* 2>/dev/null | head -1)
LATEST_PY=$(ls -t server.py.backup.* 2>/dev/null | head -1)

if [ -n "$LATEST_HTML" ]; then
  echo "✓ 恢复前端: $LATEST_HTML"
  cp "$LATEST_HTML" design-upgrade.html
else
  echo "❌ 未找到前端备份"
fi

if [ -n "$LATEST_PY" ]; then
  echo "✓ 恢复后端: $LATEST_PY"
  cp "$LATEST_PY" server.py
else
  echo "❌ 未找到后端备份"
fi

# 重启
echo "✓ 重启服务..."
systemctl restart wujing

sleep 2
curl -s http://localhost:8000/api/health && echo "✅ 回滚完成" || echo "⚠️ 服务可能需要手动检查"
```

---

## 指标验证脚本

```bash
#!/bin/bash
# 验证修复效果

echo "📊 舞镜 P0 修复效果验证"
echo "========================"

# 1. 检查进程
echo ""
echo "1️⃣ 后端服务状态："
systemctl status wujing --no-pager | grep -E "active|inactive"

# 2. 检查错误日志
echo ""
echo "2️⃣ 过去 5 分钟的错误："
tail -50 /var/log/wujing.log | grep -E "\[Error\]|\[Timeout\]" | wc -l
echo "   条（应该是 0 或很少）"

# 3. 检查内存
echo ""
echo "3️⃣ 进程内存占用："
ps aux | grep "[p]ython.*wujing" | awk '{print $6 " MB"}'

# 4. 检查响应时间
echo ""
echo "4️⃣ API 响应时间（毫秒）："
time curl -s http://localhost:8000/api/health > /dev/null

# 5. PostHog 检查
echo ""
echo "5️⃣ PostHog 埋点："
echo "   📈 请访问 PostHog 仪表板"
echo "   🔍 搜索事件：js_error, fetch_error, api_timeout"
echo "   📉 比较修复前后的错误率"
```

---

## 配置优化（可选）

### 调整超时时间

**前端：** 改快 (5 秒) / 改慢 (15 秒)
```javascript
var _FETCH_TIMEOUT = 5000;  // 改为 5000 或 15000
```

**后端：** 改快 (10 秒) / 改慢 (60 秒)
```python
response = await asyncio.wait_for(call_next(request), timeout=10.0)
```

### 调整生图配额

**每用户每天额度：**
```python
_BG_LIMIT = {"per_day": 20}  # 改为 20
```

### 启用请求日志

**后端添加：**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 在中间件中添加
logger.info(f"[Request] {request.method} {request.url.path} {request.client}")
```

---

## 常见问题快速解答

### Q: 修复后视频还是播放不了？
```javascript
// Console 中运行诊断
var vid = document.getElementById('dcPracticeVideo');
console.log('Video 状态:', {
  src: vid.src,
  networkState: vid.networkState, // 0=未初始化, 1=闲置, 2=加载中, 3=已加载
  readyState: vid.readyState,     // 0=未初始化, 1=元数据, 2=正在加载, 3=已加载, 4=可播放
  error: vid.error
});
```

### Q: 后端还是 502？
```bash
# 检查日志
tail -20 /var/log/wujing.log | grep ERROR

# 检查进程
ps aux | grep wujing

# 尝试手动启动
cd /www/wujing-api && python3 server.py
```

### Q: 生图配额限制不生效？
```python
# 检查 decode_token 是否正常
print(decode_token("your_test_token"))

# 检查配额字典
print(_bg_daily_limit)

# 检查日期格式
from datetime import datetime
print(datetime.now().strftime("%Y-%m-%d"))
```

---

## 最后检查清单

部署前：
- [ ] 已读 P0_FIXES_SUMMARY.md
- [ ] 已备份原文件

部署时：
- [ ] 修改了 design-upgrade.html（autoplay + 函数）
- [ ] 添加了前端脚本
- [ ] 修改了 server.py（中间件 + 生图防护）

部署后：
- [ ] Console 显示初始化日志
- [ ] API 能正常返回
- [ ] 没有 502 错误
- [ ] 生图配额生效（测试第 11 次返回 429）

---

**快速参考完成！** 🎉

更多详情见：
- 📖 PERFORMANCE_FIXES_P0.md
- 🛠️ INTEGRATION_GUIDE.md
- 📁 patches/ 目录
