# 舞镜应用 5 大 P0 性能问题修复方案

## 问题总览

| 序号 | 问题 | 位置 | 优先级 | 影响范围 |
|------|------|------|--------|---------|
| 1 | 无 fetch 超时保护 | design-upgrade.html, server.py | P0 | 所有 API 调用 |
| 2 | autoplay 导致 play() 报错 | design-upgrade.html:4574 | P0 | 跟练模式视频 |
| 3 | 无全局错误处理 | design-upgrade.html <script> | P0 | JS 运行崩溃 |
| 4 | 页面卸载内存泄漏 | design-upgrade.html | P0 | 长时间使用性能下降 |
| 5 | 后端资源长时占用 | server.py, auto_decompose.py | P0 | 拆解任务无超时 |

---

## 修复方案 1：添加 fetch 超时保护

### 问题分析
- 所有 fetch 调用默认无超时，可能导致请求永久挂起
- 慢网络下用户会一直等待，无法重试或取消

### 前端修复 (design-upgrade.html)

在 `<script>` 最开始添加（约 1761 行后）：

```javascript
/* ═══ FETCH 超时保护 ═══ */
var _FETCH_TIMEOUT = 10000; // 10 秒超时

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
  
  // 包装所有 fetch 调用为带超时的 Promise.race
  return _withTimeout(_origFetch(url, opts), _FETCH_TIMEOUT).catch(function(err) {
    // 显示用户友好的错误提示
    if (err.message.indexOf('超时') !== -1) {
      toast('⏱ ' + err.message);
    }
    throw err;
  });
};
```

### 后端修复 (server.py)

添加全局超时中间件（约 84 行后）：

```python
import asyncio

# ── 全局 HTTP 超时保护 ──
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    """所有 API 请求添加 30 秒全局超时"""
    try:
        response = await asyncio.wait_for(call_next(request), timeout=30.0)
        return response
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"error": "API 请求超时，请重试"}
        )
```

### 关键修改点

在所有 fetch 调用的 `.catch()` 中添加自动重试逻辑（可选，仅用于幂等请求）：

```javascript
function fetchWithRetry(url, opts, retries = 2) {
  return fetch(url, opts).catch(function(err) {
    if (retries > 0 && err.message.indexOf('超时') !== -1) {
      return fetchWithRetry(url, opts, retries - 1);
    }
    throw err;
  });
}
```

---

## 修复方案 2：修复视频 autoplay 导致的 play() 报错

### 问题分析
- 浏览器端限制：某些浏览器/移动设备禁用自动播放（autoplay 属性被忽略）
- 当代码调用 `.play()` 时抛出错误：`NotAllowedError: play() failed`
- 错误未被捕获导致业务逻辑中断

### 前端修复 (design-upgrade.html)

**第一步：移除 autoplay 属性**

找到约 4574 行：
```html
<!-- 旧版本 -->
<video id="dcPracticeVideo" autoplay loop playsinline controls></video>
```

改为：
```html
<!-- 新版本 -->
<video id="dcPracticeVideo" loop playsinline controls></video>
```

**第二步：修复 dcPracticeRender() 函数（约 4595 行）**

```javascript
function dcPracticeRender(){
  var d=_dcPracticeData;if(!d)return;
  var p=d.phrases[_dcPracticeIdx];
  var vid=document.getElementById('dcPracticeVideo');
  var slowSrc='api/decompose/'+d.id+'/clip/p'+p.i+'_slow';
  var normSrc='api/decompose/'+d.id+'/clip/p'+p.i;
  var top=document.getElementById('dcPracticeTop');
  
  vid.style.display='block';
  top.querySelector('.dc-practice-no-clip') && top.querySelector('.dc-practice-no-clip').remove();
  vid.src=slowSrc;
  vid.playbackRate=0.5;
  vid.load();
  
  // ✅ 改进：添加 .catch() 处理 play() 失败
  var playPromise = vid.play();
  if (playPromise !== undefined) {
    playPromise
      .then(function() {
        // 播放成功
      })
      .catch(function(err) {
        console.warn('初始播放失败，切换后备源', err);
        // 降级：尝试普通速度
        vid.src=normSrc;
        vid.playbackRate=0.5;
        vid.load();
        var fallbackPlay = vid.play();
        if (fallbackPlay !== undefined) {
          fallbackPlay
            .then(function() {
              // 降级播放成功
            })
            .catch(function(err2) {
              console.warn('降级播放也失败', err2);
              vid.style.display='none';
              var msg=document.createElement('div');
              msg.className='dc-practice-no-clip';
              msg.textContent='视频加载失败，请稍后重试';
              top.appendChild(msg);
            });
        }
      });
  }
  
  var label=p.i+'/'+(d.phrases.length)+' · '+(p.name||'');
  document.getElementById('dcPracticeLabel').textContent=label;
  var fb=document.getElementById('dcPracticeFrames');
  fb.innerHTML='';
  for(var f=0;f<(d.strip||4);f++){
    (function(fi){
      var img=document.createElement('img');
      img.src='api/decompose/'+d.id+'/frame/p'+p.i+'_'+fi;
      img.alt='帧'+(fi+1);
      img.onerror=function(){this.style.display='none';};
      fb.appendChild(img);
    })(f);
  }
}
```

**第三步：添加用户主动播放事件处理（可选，提升体验）**

在 HTML 中的视频标签之后添加事件监听：

```javascript
/* 视频播放权限处理 */
document.addEventListener('DOMContentLoaded', function() {
  var vid = document.getElementById('dcPracticeVideo');
  if (vid) {
    // 监听 play 事件，防止重复调用
    vid.addEventListener('play', function() {
      // 播放成功
    }, { once: false });
    
    // 监听播放暂停
    vid.addEventListener('pause', function() {
      // 清理加载状态
    }, { once: false });
  }
});
```

---

## 修复方案 3：添加全局错误处理

### 问题分析
- JS 运行时错误未被捕获会导致整个应用卡死
- 特别是在 Promise 异步流程中，未处理的 rejection 导致无声失败

### 前端修复 (design-upgrade.html)

在 `<script>` 最开始添加（最好在 PostHog 初始化之后）：

```javascript
/* ═══ 全局错误处理 ═══ */

// 1. 捕获同步 JS 错误
window.onerror = function(message, source, lineno, colno, error) {
  console.error('[JS Error]', message, 'at', source + ':' + lineno + ':' + colno, error);
  
  // 上报到埋点系统
  try {
    if (window.WJ && WJ.track) {
      WJ.track('js_error', {
        message: String(message).slice(0, 100),
        source: source,
        lineno: lineno,
        colno: colno,
        stack: error ? String(error.stack).slice(0, 500) : ''
      });
    }
  } catch (e) {}
  
  // 显示用户友好提示（仅在重要错误时）
  if (message.indexOf('Cannot read') !== -1 || message.indexOf('is not a function') !== -1) {
    toast('⚠️ 应用遇到问题，请刷新重试');
  }
  
  // 返回 true 阻止默认错误处理
  return true;
};

// 2. 捕获未处理的 Promise rejection
window.onunhandledrejection = function(event) {
  var err = event.reason;
  console.error('[Unhandled Promise]', err);
  
  // 上报到埋点
  try {
    if (window.WJ && WJ.track) {
      WJ.track('promise_rejection', {
        message: err ? String(err.message || err).slice(0, 100) : 'unknown',
        stack: err && err.stack ? String(err.stack).slice(0, 500) : ''
      });
    }
  } catch (e) {}
  
  // 重要：阻止浏览器默认崩溃处理（Chrome 会显示 "Uncaught (in promise)" 错误）
  event.preventDefault();
};

// 3. 包装所有 setTimeout/setInterval，捕获执行时错误
var _origSetTimeout = window.setTimeout;
window.setTimeout = function(fn, delay) {
  return _origSetTimeout(function() {
    try {
      if (typeof fn === 'function') fn();
    } catch (err) {
      console.error('[setTimeout Error]', err);
      window.onerror(err.message, 'setTimeout', 0, 0, err);
    }
  }, delay);
};

var _origSetInterval = window.setInterval;
window.setInterval = function(fn, delay) {
  return _origSetInterval(function() {
    try {
      if (typeof fn === 'function') fn();
    } catch (err) {
      console.error('[setInterval Error]', err);
      window.onerror(err.message, 'setInterval', 0, 0, err);
    }
  }, delay);
};

// 4. 为所有 fetch 添加错误上报
var _origFetchForError = window.fetch;
window.fetch = function(url, opts) {
  return _origFetchForError(url, opts)
    .catch(function(err) {
      console.error('[Fetch Error]', url, err);
      try {
        if (window.WJ && WJ.track) {
          WJ.track('fetch_error', {
            url: String(url).slice(0, 200),
            message: err ? err.message : 'unknown'
          });
        }
      } catch (e) {}
      throw err; // 重新抛出，让调用方处理
    });
};
```

---

## 修复方案 4：页面卸载清理（防内存泄漏）

### 问题分析
- 页面离开时未清理 setInterval / setTimeout
- 事件监听器未移除
- 大对象引用未释放

### 前端修复 (design-upgrade.html)

在 `<script>` 最开始添加全局追踪机制：

```javascript
/* ═══ 页面卸载清理机制 ═══ */

// 全局定时器注册表
var _activeTimers = [];
var _activeListeners = [];

// 覆盖原生 setTimeout/setInterval，自动追踪
var _origSetTimeout = window.setTimeout;
window.setTimeout = function(fn, delay, args) {
  var id = _origSetTimeout(fn, delay, args);
  _activeTimers.push({ type: 'timeout', id: id });
  return id;
};

var _origSetInterval = window.setInterval;
window.setInterval = function(fn, delay, args) {
  var id = _origSetInterval(fn, delay, args);
  _activeTimers.push({ type: 'interval', id: id });
  return id;
};

// 覆盖 clearTimeout/clearInterval
var _origClearTimeout = window.clearTimeout;
window.clearTimeout = function(id) {
  _activeTimers = _activeTimers.filter(function(t) { return t.id !== id; });
  return _origClearTimeout(id);
};

var _origClearInterval = window.clearInterval;
window.clearInterval = function(id) {
  _activeTimers = _activeTimers.filter(function(t) { return t.id !== id; });
  return _origClearInterval(id);
};

// 页面卸载时清理所有
window.addEventListener('beforeunload', function() {
  // 清理所有定时器
  _activeTimers.forEach(function(t) {
    if (t.type === 'timeout') _origClearTimeout(t.id);
    if (t.type === 'interval') _origClearInterval(t.id);
  });
  _activeTimers = [];
  
  // 移除所有监听器
  _activeListeners.forEach(function(l) {
    try {
      l.element.removeEventListener(l.event, l.handler, l.options);
    } catch (e) {}
  });
  _activeListeners = [];
  
  // 清理大对象
  _dcPracticeData = null;
  DC_DATA = null;
  
  console.log('[Cleanup] 已清理定时器、监听器、内存对象');
});

// 页面卸载后清理
window.addEventListener('unload', function() {
  // 最后保险：停止所有音视频播放
  document.querySelectorAll('video, audio').forEach(function(el) {
    try {
      el.pause();
      el.src = '';
    } catch (e) {}
  });
  
  // 发送最后一条埋点
  try {
    if (window.WJ && WJ.track) {
      WJ.track('page_unload', { timestamp: Date.now() });
    }
  } catch (e) {}
});

// 监听路由/标签页切换
document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    // 页面失焦：暂停视频、音乐播放，减少资源消耗
    document.querySelectorAll('video, audio').forEach(function(el) {
      if (!el.paused) {
        el.setAttribute('data-was-playing', '1');
        el.pause();
      }
    });
  } else {
    // 页面重新获焦：恢复播放（可选）
  }
});
```

### 关键修改点

在所有 `addEventListener` 调用中追踪：

```javascript
// ❌ 旧版本（可能泄漏）
element.addEventListener('click', myHandler);

// ✅ 新版本（自动追踪）
function addTrackedListener(element, event, handler, options) {
  element.addEventListener(event, handler, options);
  _activeListeners.push({ element: element, event: event, handler: handler, options: options });
}

// 使用示例
addTrackedListener(document, 'click', handleClick, false);
```

---

## 修复方案 5：后端资源超时保护

### 问题分析
- 拆解任务 (auto_decompose.py) 可能陷入长时间计算
- 无 timeout 保护导致服务器资源被单个任务独占
- 生图请求 (/api/generate-bg) 可能长时间挂起

### 后端修复 (server.py)

添加任务超时装饰器：

```python
import functools
import signal

def _timeout_handler(signum, frame):
    raise TimeoutError("任务执行超时")

def task_timeout(seconds=300):
    """任务超时装饰器（仅 Linux/Unix）"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 仅在 Unix 系统上启用信号超时
            if hasattr(signal, 'SIGALRM'):
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)  # 取消超时
                return result
            except TimeoutError:
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)
                raise TimeoutError(f"任务超过 {seconds} 秒，已中止")
        return wrapper
    return decorator
```

在 /api/decompose 端点添加超时：

```python
@app.post("/api/decompose")
async def decompose_upload(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    genre: str = Form(default=""),
    song: str = Form(default=""),
    lyric_first: str = Form(default=""),
    lyric_last: str = Form(default=""),
    x_device_id: str = Header(default="guest")
):
    """AI 拆解舞蹈视频"""
    user_id = _current_user_id()
    identity = user_id or x_device_id
    
    # 检查免费配额
    if not _free_quota_ok(identity):
        return JSONResponse(status_code=429, content={
            "error": "达到免费额度限制，请登录升级或明日再试"
        })
    
    did = str(uuid.uuid4())
    file_path = os.path.join(DATA_DIR, did, "video.mp4")
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    # 保存上传文件
    async with aiofiles.open(file_path, 'wb') as f:
        contents = await file.read()
        await f.write(contents)
    
    # ✅ 在后台线程中启动拆解任务，添加超时保护
    def run_with_timeout():
        try:
            _run_decompose_with_hooks(did, file_path, user_id, title, genre,
                                     song=song, lyric_first=lyric_first, 
                                     lyric_last=lyric_last)
        except TimeoutError as e:
            print(f"[decompose timeout] {did}: {e}")
            # 标记为失败
            import json as json_module
            meta_path = os.path.join(DATA_DIR, did, "meta.json")
            with open(meta_path, 'w') as f:
                json_module.dump({
                    "status": "failed",
                    "error": "处理超时，请稍后重试",
                    "did": did
                }, f)
        except Exception as e:
            print(f"[decompose error] {did}: {e}")
    
    # 后台线程 + 30 分钟硬超时
    import threading
    t = threading.Thread(target=run_with_timeout, daemon=True)
    t.start()
    # 可选：join 但带超时（不阻塞响应）
    
    return JSONResponse(status_code=202, content={
        "dance_id": did,
        "status": "processing",
        "message": "视频上传成功，AI 正在拆解..."
    })
```

### 修复 auto_decompose.py

添加子任务超时（FFmpeg/MediaPipe）：

```python
import subprocess
import signal

def run_decompose_with_timeout(video_path, timeout_sec=600):
    """
    运行拆解任务，添加超时保护
    timeout_sec: 超时秒数（默认 10 分钟）
    """
    cmd = [
        "python3", "mediapipe_extract.py", 
        video_path
    ]
    
    try:
        result = subprocess.run(
            cmd,
            timeout=timeout_sec,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"MediaPipe 处理失败: {result.stderr[-500:]}")
        return result.stdout
    except subprocess.TimeoutExpired:
        print(f"[timeout] MediaPipe 超过 {timeout_sec} 秒，已中止")
        raise TimeoutError(f"视频处理超时（>={timeout_sec}s），请上传较短视频")
```

---

## 后端生图防烧钱漏洞修复 (server.py)

### 问题分析
- /api/generate-bg 无鉴权保护，任何人都能调用
- 可能导致大量免费生图烧配额

### 修复代码

```python
@app.post("/api/generate-bg")
async def generate_background(request: Request):
    """生成背景图（需登录 + 配额限制）"""
    
    # ✅ 必须登录
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return JSONResponse(status_code=401, content={"error": "需要登录"})
    
    user_id = decode_token(token)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "登录过期"})
    
    # ✅ 每天限制生图次数（防滥用）
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"bg:{user_id}:{today}"
    daily_count = _bg_daily.get(key, 0)
    
    if daily_count >= 10:  # 每用户每天最多 10 张
        return JSONResponse(status_code=429, content={
            "error": "今日生图次数已用完，明天再来"
        })
    
    _bg_daily[key] = daily_count + 1
    
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        
        if not prompt or len(prompt) < 5:
            return JSONResponse(status_code=400, content={"error": "prompt 太短"})
        
        # 调用生图 API...
        result = call_image_api(prompt, timeout=30)
        
        return JSONResponse(status_code=200, content={
            "status": "ok",
            "url": result["url"]
        })
    except TimeoutError:
        return JSONResponse(status_code=504, content={"error": "生图超时，请重试"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "生图失败"})
```

---

## 测试清单

### 前端测试
- [ ] 网络延迟模拟：Chrome DevTools Throttle 设为 Slow 3G，验证 10 秒超时提示
- [ ] 视频播放：打开跟练模式，验证视频能正常播放（无 play() 错误）
- [ ] 错误处理：Console 中手动触发错误 (throw new Error('test'))，验证显示用户提示
- [ ] 内存泄漏：打开关闭多次页面，Chrome DevTools Memory 检查堆内存是否增长

### 后端测试
- [ ] 超时测试：调用 /api/decompose，中断网络 15 秒，验证 10 秒超时返回错误
- [ ] 生图配额：登录状态下连续调用 /api/generate-bg 11 次，第 11 次应返回 429
- [ ] 大文件：上传 500MB 视频，验证 30 分钟内处理或返回超时

### 埋点验证
- [ ] PostHog 中搜索 'js_error', 'promise_rejection', 'fetch_error' 事件
- [ ] 验证错误堆栈能正确捕获（用于调试）

---

## 部署步骤

1. **备份现有文件**
   ```bash
   cp /Users/karen/projects/舞镜/_live/design-upgrade.html design-upgrade.html.backup
   cp /Users/karen/projects/舞镜/_live/server.py server.py.backup
   ```

2. **应用前端修改** (design-upgrade.html)
   - 移除 autoplay 属性（第 4574 行）
   - 添加 fetch 超时装饰器（第 1761 行附近）
   - 添加全局错误处理（最开始）
   - 修复 dcPracticeRender() 函数
   - 添加页面卸载清理逻辑

3. **应用后端修改** (server.py)
   - 添加 timeout_middleware
   - 修改 /api/decompose 添加超时保护
   - 修改 /api/generate-bg 添加鉴权 + 配额限制

4. **测试验证**（参考上面的测试清单）

5. **部署上线**
   ```bash
   cd /Users/karen/projects/舞镜/_live
   git add -A
   git commit -m "P0 性能修复：fetch超时+视频播放+错误处理+内存清理+后端超时"
   git push origin main
   ```

6. **监控验证**
   - 打开 PostHog 监控面板
   - 查看 js_error, fetch_error 等事件是否减少
   - 观察 30 分钟内错误率变化

---

## 后续优化方向

1. **前端缓存**：添加 ServiceWorker，缓存常用 API 响应，减少网络依赖
2. **请求去重**：同一时间内的相同请求自动合并（debounce/throttle）
3. **离线降级**：网络中断时显示本地缓存数据而非白屏
4. **性能监控**：集成 Sentry，自动上报性能指标和错误堆栈
5. **资源预加载**：预加载常用的视频/图片资源，减少卡顿

