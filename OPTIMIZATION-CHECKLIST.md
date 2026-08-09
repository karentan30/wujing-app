# 舞镜性能优化 · 实施清单

## ✅ 已完成的优化

### 1. CSS 压缩
- [x] 移除 `:root` 变量块中的换行（单行 81 个 CSS 变量）
- [x] 压缩 `html,body,body,#app` 基础选择器
- [x] 压缩 `.safe-pad,.safe-pad-b,.topbar` 等安全区域样式
- [x] 压缩 `.brand-*,.back` 顶栏样式
- [x] 压缩视图过渡动画样式
- **总体进度**：约 20% 完成（还有 350KB CSS 可继续压缩）

### 2. 内存泄漏防护 ✅ 
- [x] 增强 `showView()` 视图切换清理逻辑
  - 视图隐藏时停止所有视频播放
  - 清理视频 `src` 属性释放缓冲
- [x] 修复 `dcCloseModal()` 
  - 添加 `v.load()` 完整释放
  - 添加 try-catch 错误处理
- [x] 修复 `mvStopVideo()` 和 `mvStopPreview()`
  - 完整清理视频资源
  - 清理 Canvas 像素数据
- [x] 新增 `globalCleanup()` 函数
  - 集中管理所有资源清理
  - 页面卸载时自动执行
  - 标签页隐藏时自动暂停视频（电池友好）

### 3. 事件监听器清理
- [x] 添加 `beforeunload` 事件监听
- [x] 添加 `pagehide` 事件监听（更可靠）
- [x] 添加 `visibilitychange` 事件监听
- [x] 所有监听器使用 `{ once: false }` 确保持久监听

---

## 📋 待办事项（优先级）

### 🔴 高优先级（1周内）
- [ ] **测试内存占用**
  ```bash
  # Chrome DevTools: F12 → Memory → Take heap snapshot
  # 监控目标：
  # - 视图切换前后的内存变化
  # - 首次加载 vs 二次加载的内存峰值
  # - 单个视频最大占用 (目标: <50MB)
  ```

- [ ] **继续压缩 CSS**（预计再减 20-30KB）
  - 压缩所有选择器（去除格式化）
  - 移除无用选择器
  - 合并相同属性

- [ ] **部署到生产环境**
  - 在 `/live/` 目录更新 design-upgrade.html
  - 在 Caddy 配置中检查 gzip 压缩是否启用
  - 验证没有 console 错误

### 🟡 中优先级（2-4周）
- [ ] **后端 HLS 支持**
  - 在 `/api/decompose/{id}/clip/{name}` 返回 `.m3u8` 文件
  - 生成 `.ts` 分片（推荐 10s 一段）
  - 参考实现：
    ```python
    # 伪代码
    def get_hls_manifest(dance_id, clip_name):
        video = load_video(f"{dance_id}/{clip_name}.mp4")
        m3u8 = generate_m3u8(video, segment_duration=10)
        return m3u8, 'application/vnd.apple.mpegurl'
    ```

- [ ] **添加网络错误重试机制**
  ```javascript
  // 已在 dcPlayClip 中预留了框架，需补充实现
  v.onerror = function(){
    var retries = this.dataset.retries ? parseInt(this.dataset.retries) : 0;
    if(retries < 3){
      this.dataset.retries = retries + 1;
      setTimeout(function(){ v.load(); }, 1000 * (retries + 1));
    }
  };
  ```

### 🟢 低优先级（优化方向）
- [ ] **添加性能埋点**
  ```javascript
  // 在 dcPlayClip 中添加
  var loadStart = performance.now();
  v.addEventListener('canplaythrough', function(){
    var loadTime = performance.now() - loadStart;
    WJ.track('video_load_time', {
      loadTime: Math.round(loadTime),
      videoSize: this.buffered.end(0) || 0
    });
  }, { once: true });
  ```

- [ ] **实现低端设备检测**
  ```javascript
  function isLowEndDevice(){
    // RAM < 2GB or CPU cores < 2
    var cores = navigator.hardwareConcurrency || 4;
    return cores < 2;
  }
  // 低端设备自动禁用某些动画
  if(isLowEndDevice()) document.body.classList.add('low-end');
  ```

- [ ] **Canvas 预渲染优化**（MV Studio）
  - 使用 `OffscreenCanvas` 转移到 Worker
  - 分片渲染而不是一帧一帧
  - 预计提升 30-50% 帧率

---

## 🧪 测试方案

### A. 内存泄漏测试
**场景**：用户频繁切换视图观看多个分段视频

```javascript
// 在浏览器 console 运行
setInterval(() => {
  console.log('Memory:', performance.memory?.usedJSHeapSize / 1048576 + ' MB');
}, 1000);

// 操作步骤：
// 1. 上传舞蹈 → 点击八拍卡 → 查看视频 → 关闭
// 2. 重复 5 次
// 预期：内存峰值不应大幅增长
```

### B. CSS 加载时间测试
```javascript
// 测量 CSS 解析时间
performance.mark('css-start');
// ... 页面加载 ...
performance.mark('css-end');
var cssTime = performance.measure('css', 'css-start', 'css-end');
console.log('CSS parse time:', cssTime.duration + 'ms');
```

### C. 视频播放流畅度测试
```javascript
// 监控帧率丢失
var lastTime = performance.now();
var frameCount = 0;

function checkFPS(){
  var now = performance.now();
  var fps = 1000 / (now - lastTime);
  frameCount++;
  lastTime = now;
  
  if(frameCount % 60 === 0){
    console.log('FPS:', fps.toFixed(1));
  }
  requestAnimationFrame(checkFPS);
}
checkFPS();
```

---

## 📊 预期效果

| 指标 | 预期改善 | 验证方法 |
|------|---------|---------|
| **首页加载时间** | -5% ~ -10% | Lighthouse |
| **视图切换延迟** | <100ms | Chrome DevTools Performance |
| **内存占用峰值** | -20% ~ -40% | DevTools → Memory |
| **电池消耗** | -15% ~ -25% | 后台播放时间 |
| **首个视频加载** | 待 HLS 实现 | 缓冲进度条 |

---

## 🚀 部署步骤

### 1. 本地验证
```bash
cd /Users/karen/projects/舞镜
# 检查 HTML 语法
html5-validator _live/design-upgrade.html

# 检查文件大小
ls -lh _live/design-upgrade.html
```

### 2. 上传到服务器
```bash
# HK 服务器（47.242.80.65）
scp _live/design-upgrade.html root@47.242.80.65:/home/wujing/_live/

# 验证权限和重启
ssh root@47.242.80.65 "systemctl restart wujing"
```

### 3. 生产验证
- 打开 https://wujing.mylumee.app
- F12 → Console 检查是否有错误
- 测试视图切换、视频播放、支付流程
- 检查内存占用（Memory 标签）

---

## 📞 问题排查

| 问题 | 症状 | 解决方案 |
|------|------|---------|
| 视频无法播放 | 黑屏或加载圈 | 检查 `/api/decompose/{id}/clip/{name}` 返回状态 |
| 内存仍持续增长 | Chrome 内存标签显示上升线 | 检查是否有其他计时器（setInterval）未清理 |
| Canvas 花屏 | MV 预览显示花屏 | 确认 `clearRect()` 在正确位置调用 |
| 样式破损 | 排版错乱 | CSS 压缩时避免删除必要的分号 |

---

## 💾 文件版本管理

```bash
# 备份原始文件
cp _live/design-upgrade.html _live/design-upgrade.html.backup

# 新版本标记
# design-upgrade.html
#   版本号：v2.1.0-optimized
#   优化时间：2026-08-09
#   变更：CSS压缩、内存清理、视频资源释放
```

---

**生成时间**：2026-08-09
**更新周期**：建议每周检查一次内存占用和性能指标
