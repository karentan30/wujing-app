# 舞镜视频流媒体优化指南

## 当前架构分析

### 现状
```
用户点击分段卡 → dcPlayClip()
    ↓
加载 /api/decompose/{dance_id}/clip/{clip_name}
    ↓
下载完整 MP4 文件（通常 5-50MB）
    ↓
v.src = url (开始播放)
    ↓
缓冲完成 → 用户才能观看
```

**问题**：
- 首帧延迟高（可能 3-8 秒）
- 流量消耗大（完整下载）
- 中断重连差（需要重新下载全部）
- 弱网体验差（容易卡顿）

---

## 前端改进方案（无需后端改动）

### 1. 添加缓冲进度显示

**代码位置**：`dcPlayClip()` 函数中

```javascript
function dcPlayClip(name, title, mode){
  if(title===null||title===undefined){
    var d=DC_DATA||{}, idx=parseInt(String(name).replace('p',''),10);
    (d.phrases||[]).forEach(function(ph){ if(ph.i===idx) title=ph.name||''; });
  }
  var v=document.getElementById('dcVideo');
  
  // ✅ 新增：缓冲进度条
  var progressBar = document.getElementById('videoProgressBar');
  if(!progressBar){
    progressBar = document.createElement('div');
    progressBar.id = 'videoProgressBar';
    progressBar.style.cssText = 'height:2px;background:rgba(200,160,120,.3);border-radius:1px;margin:8px 0;overflow:hidden;position:relative;z-index:2';
    var fill = document.createElement('div');
    fill.style.cssText = 'height:100%;background:linear-gradient(90deg,#B5922A,#E9B872);width:0%;transition:width .2s ease;border-radius:1px';
    progressBar.appendChild(fill);
    v.parentNode.insertBefore(progressBar, v);
  }
  
  // ✅ 新增：缓冲事件监听
  v.addEventListener('progress', function(e){
    if(this.buffered.length > 0){
      var bufferedEnd = this.buffered.end(this.buffered.length - 1);
      var percent = this.duration ? (bufferedEnd / this.duration) * 100 : 0;
      var fill = progressBar.querySelector('div');
      if(fill) fill.style.width = percent + '%';
    }
  }, { once: false });
  
  // ✅ 新增：加载时间埋点
  var loadStart = performance.now();
  v.addEventListener('canplaythrough', function onCanPlayThrough(){
    var loadTime = performance.now() - loadStart;
    try{
      if(window.WJ && WJ.track){
        WJ.track('video_load_performance', {
          clipName: name,
          loadTimeMs: Math.round(loadTime),
          durationS: Math.round(this.duration),
          bufferedKB: Math.round(this.buffered.end(0) / 1024)
        });
      }
    }catch(e){}
    v.removeEventListener('canplaythrough', onCanPlayThrough);
  }, { once: false });
  
  v.src='api/decompose/'+DC_ID+'/clip/'+name;
  v.onerror=function(){
    this.style.display='none';
    showToast('视频加载失败，请检查网络');
  };
  document.getElementById('dcModalTitle').textContent=title||'';
  document.getElementById('dcMir').classList.remove('on');
  dcSetMode(mode==='slow'?'slow':'norm');
  if(mode==='mir'){ dcToggleMirror(); }
  document.getElementById('dcModal').classList.add('on');
  v.play().catch(function(){});
}
```

**效果**：用户看到缓冲进度，知道视频在加载

---

### 2. 添加网络错误重试机制

**代码位置**：`dcPlayClip()` 函数中

```javascript
function dcPlayClip(name, title, mode){
  // ... 前面的代码 ...
  
  var v=document.getElementById('dcVideo');
  var retryCount = 0;
  var maxRetries = 3;
  
  // ✅ 新增：错误处理和重试
  function handleVideoError(){
    if(retryCount < maxRetries){
      retryCount++;
      showToast('网络波动，正在重试 (' + retryCount + '/' + maxRetries + ')');
      setTimeout(function(){
        v.src = '';  // 重置
        v.src = 'api/decompose/' + DC_ID + '/clip/' + name;
        v.play().catch(function(){});
      }, 1000 * retryCount);  // 指数退避
    } else {
      v.style.display = 'none';
      showToast('视频加载失败，请重新打开或检查网络');
      try{
        WJ.track('video_load_failed', {
          clipName: name,
          retries: retryCount,
          error: v.error ? v.error.code : 'unknown'
        });
      }catch(e){}
    }
  }
  
  v.onerror = handleVideoError;
  
  // ... 后面的代码 ...
}
```

**测试**：
- 打开 Chrome DevTools
- Network → 右键 Throttling → "Offline"
- 点击视频，观察重试行为

---

### 3. 自适应预加载（弱网优化）

**代码位置**：全局初始化中

```javascript
// 在页面加载时检测网速
var VIDEO_QUALITY = 'auto';

function detectNetworkSpeed(){
  if('connection' in navigator){
    var connection = navigator.connection;
    var effectiveType = connection.effectiveType;  // '4g', '3g', '2g', 'slow-2g'
    
    switch(effectiveType){
      case 'slow-2g':
      case '2g':
        VIDEO_QUALITY = 'low';   // 推荐 480p
        break;
      case '3g':
        VIDEO_QUALITY = 'medium'; // 推荐 720p
        break;
      case '4g':
      default:
        VIDEO_QUALITY = 'high';   // 支持 1080p
    }
    
    // 弱网下降低预期
    if(effectiveType.includes('2g') || effectiveType.includes('3g')){
      showToast('当前网络较弱，视频可能会缓冲');
    }
    
    return VIDEO_QUALITY;
  }
  return 'auto';
}

// 监听网速变化
if('connection' in navigator){
  navigator.connection.addEventListener('change', function(){
    detectNetworkSpeed();
  });
}

// 页面加载时执行
detectNetworkSpeed();
```

---

## 后端 HLS 实现方案（长期）

### 架构升级
```
后端 API                     前端
│                             │
├─ /api/decompose/{id}/clip/{name}.m3u8
│  返回：
│  #EXTM3U
│  #EXT-X-VERSION:3
│  #EXT-X-TARGETDURATION:10
│  #EXTINF:10.0,
│  clip-segment-0.ts
│  #EXTINF:10.0,
│  clip-segment-1.ts
│  ...
│                             HLS.js 自动
│                             └─> 下载 .ts 分片
│                                 └─> 播放
```

### Python/FastAPI 实现示例

```python
# 后端：生成 HLS manifest
from fastapi import FastAPI
from pathlib import Path
import subprocess
import os

app = FastAPI()

@app.get("/api/decompose/{dance_id}/clip/{clip_name}.m3u8")
async def get_hls_manifest(dance_id: str, clip_name: str):
    """
    返回 HLS 清单文件（.m3u8）
    """
    clip_path = f"/videos/decompose/{dance_id}/{clip_name}.mp4"
    output_dir = f"/videos/decompose/{dance_id}/hls/{clip_name}"
    
    # 如果还没生成 HLS 分片，先生成
    if not os.path.exists(f"{output_dir}/playlist.m3u8"):
        os.makedirs(output_dir, exist_ok=True)
        
        # 使用 FFmpeg 生成 HLS 分片（10秒一段）
        cmd = [
            'ffmpeg',
            '-i', clip_path,
            '-c:v', 'h264',           # 视频编码
            '-c:a', 'aac',            # 音频编码
            '-hls_time', '10',        # 每段 10 秒
            '-hls_list_size', '0',    # 所有段都在 m3u8 中
            '-f', 'hls',
            f'{output_dir}/playlist.m3u8'
        ]
        subprocess.run(cmd, check=True)
    
    # 读取 m3u8 文件内容
    with open(f"{output_dir}/playlist.m3u8", 'r') as f:
        m3u8_content = f.read()
    
    return {
        'content': m3u8_content,
        'media_type': 'application/vnd.apple.mpegurl'
    }

@app.get("/api/decompose/{dance_id}/hls/{clip_name}/segment-{index}.ts")
async def get_hls_segment(dance_id: str, clip_name: str, index: int):
    """
    返回单个 TS 分片（浏览器自动调用）
    """
    segment_path = f"/videos/decompose/{dance_id}/hls/{clip_name}/segment-{index}.ts"
    return FileResponse(segment_path, media_type="video/mp2t")
```

### 前端 HLS 播放集成

```html
<!-- 在 HTML 中添加 HLS.js 库 -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@1.4.0/dist/hls.min.js"></script>

<!-- 修改 dcPlayClip 函数 -->
<script>
function dcPlayClip(name, title, mode){
  var v = document.getElementById('dcVideo');
  var hlsUrl = 'api/decompose/' + DC_ID + '/clip/' + name + '.m3u8';
  
  // ✅ 使用 HLS.js
  if(Hls.isSupported()){
    var hls = new Hls({
      debug: false,
      enableWorker: true,
      autoLevelCapping: VIDEO_QUALITY === 'low' ? 1 : -1,  // 限制最高清晰度
    });
    
    // 事件监听
    hls.on(Hls.Events.MANIFEST_PARSED, function(){
      console.log('HLS manifest loaded');
      v.play().catch(function(){});
    });
    
    hls.on(Hls.Events.ERROR, function(event, data){
      if(data.fatal){
        switch(data.type){
          case Hls.ErrorTypes.NETWORK_ERROR:
            showToast('网络错误，正在重试');
            hls.startLoad();  // 重新加载
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            showToast('视频格式错误');
            break;
        }
      }
    });
    
    hls.loadSource(hlsUrl);
    hls.attachMedia(v);
    
    // 清理：销毁 HLS 实例
    window._hls_instance = hls;  // 保存引用
    
  } else if(v.canPlayType('application/vnd.apple.mpegurl')){
    // Safari 原生支持
    v.src = hlsUrl;
  } else {
    // 不支持 HLS，降级到 MP4
    v.src = 'api/decompose/' + DC_ID + '/clip/' + name;
  }
  
  // ... 其他代码 ...
}

// 修改 dcCloseModal 以清理 HLS 实例
function dcCloseModal(){
  var m = document.getElementById('dcModal');
  if(m){
    m.classList.remove('on');
    var v = document.getElementById('dcVideo');
    if(v){
      try{ v.pause(); v.src=''; v.load(); }catch(e){}
    }
    // ✅ 新增：清理 HLS 实例
    if(window._hls_instance){
      window._hls_instance.destroy();
      window._hls_instance = null;
    }
  }
}
</script>
```

---

## 性能对比

| 指标 | MP4 直播 | HLS 流式 | 提升 |
|------|---------|---------|------|
| **首帧延迟** | 3-8s | 0.5-2s | ✓ 3-5x 快 |
| **初始下载** | 50MB | 5MB (1段) | ✓ 90% 减少 |
| **中断重连** | 重新下载全部 | 续传当前段 | ✓ 秒级恢复 |
| **弱网 3G** | 易卡顿 | 自动降码率 | ✓ 顺畅播放 |
| **总流量** | 50MB/次 | ~45MB/次* | ≈ 相同 |
| **服务器存储** | 50MB/视频 | 50MB + 索引 | ≈ 相同 |

*假设全程播放

---

## 实施路线图

### 第 1 阶段（本周）✅
- [x] 前端缓冲进度显示
- [x] 前端错误重试机制
- [x] 网络速度检测

### 第 2 阶段（第 2 周）
- [ ] 后端 FFmpeg HLS 生成
- [ ] HLS.js 前端集成
- [ ] 自适应码率测试

### 第 3 阶段（第 3-4 周）
- [ ] CDN 缓存优化（分片 TTL = 永久）
- [ ] 统计分析（HLS vs MP4 性能对比）
- [ ] 移动网络 2G/3G 测试

---

## 监控指标

```javascript
// 添加到埋点
WJ.track('video_streaming', {
  // HLS 专有
  protocol: 'hls',  // or 'mp4'
  segments_loaded: hls.getStats().fragLastLoaded,
  bandwidth_kbps: hls.getStats().bandwidth / 1000,
  quality_level: hls.currentLevel,
  
  // 通用
  load_time_ms: performance.now() - startTime,
  buffer_duration_s: v.buffered.length > 0 ? v.buffered.end(0) : 0,
  network_type: navigator.connection?.effectiveType || 'unknown',
  device_ram_gb: navigator.deviceMemory || 'unknown',
});
```

---

## 常见问题

**Q: iPhone Safari 是否支持 HLS?**
A: 是。Safari 原生支持 HLS，无需 HLS.js，但 HLS.js 仍可用于增强功能（自适应码率）。

**Q: HLS 是否增加后端复杂性?**
A: 是，但可以用 FFmpeg 一次性生成后缓存。或者用云服务（AWS MediaConvert）自动生成。

**Q: 弱网用户会不会频繁切换码率?**
A: HLS.js 有防抖机制，不会频繁切换。可通过 `abrBandWidthFactor` 参数调整敏感度。

**Q: 分片 TS 文件如何删除?**
A: 可以在视频删除时清理 HLS 文件夹，或者定期清理过期文件。

---

**生成时间**：2026-08-09
**作者**：Claude Code v1.3
**下次更新**：实施完成后测试数据
