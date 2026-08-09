/* ═══ 修复视频 autoplay play() 报错 ═══ */

/**
 * 改进的 dcPracticeRender() 函数
 * 移除 autoplay，改为用户交互后播放，添加完整的错误处理
 */
function dcPracticeRender() {
  var d = _dcPracticeData;
  if (!d) return;

  var p = d.phrases[_dcPracticeIdx];
  var vid = document.getElementById('dcPracticeVideo');
  var slowSrc = 'api/decompose/' + d.id + '/clip/p' + p.i + '_slow';
  var normSrc = 'api/decompose/' + d.id + '/clip/p' + p.i;
  var top = document.getElementById('dcPracticeTop');

  vid.style.display = 'block';

  // 移除旧的加载失败提示
  var oldMsg = top.querySelector('.dc-practice-no-clip');
  if (oldMsg) {
    oldMsg.remove();
  }

  vid.src = slowSrc;
  vid.playbackRate = 0.5;
  vid.load();

  // ✅ 改进：添加完整的 .catch() 处理 play() 失败
  var playPromise = vid.play();

  if (playPromise !== undefined) {
    playPromise
      .then(function() {
        // 播放成功
        console.log('[Video] 慢动作播放成功');
      })
      .catch(function(err) {
        console.warn('[Video] 慢动作播放失败，尝试普通速度', err);

        // 降级策略 1: 尝试普通速度源
        vid.src = normSrc;
        vid.playbackRate = 0.5;
        vid.load();

        var fallbackPlay = vid.play();
        if (fallbackPlay !== undefined) {
          fallbackPlay
            .then(function() {
              console.log('[Video] 普通源播放成功');
            })
            .catch(function(err2) {
              console.warn('[Video] 普通源播放也失败', err2);

              // 降级策略 2: 隐藏视频，显示加载失败提示
              vid.style.display = 'none';
              var msg = document.createElement('div');
              msg.className = 'dc-practice-no-clip';
              msg.textContent = '视频加载失败，请稍后重试或刷新页面';
              msg.style.cssText = 'padding:20px;text-align:center;color:#999;font-size:14px';
              top.appendChild(msg);

              // 上报错误
              try {
                if (typeof WJ !== 'undefined' && WJ.track) {
                  WJ.track('video_play_error', {
                    dance_id: d.id,
                    phrase_index: p.i,
                    error_message: err2 ? err2.message : 'unknown'
                  });
                }
              } catch (e) {}
            });
        }
      });
  } else {
    // 旧浏览器不返回 Promise，直接播放
    console.log('[Video] 浏览器不支持 play() Promise');
  }

  // 更新标签
  var label = p.i + '/' + d.phrases.length + ' · ' + (p.name || '');
  document.getElementById('dcPracticeLabel').textContent = label;

  // 加载帧缩略图
  var fb = document.getElementById('dcPracticeFrames');
  fb.innerHTML = '';

  for (var f = 0; f < (d.strip || 4); f++) {
    (function(fi) {
      var img = document.createElement('img');
      img.src = 'api/decompose/' + d.id + '/frame/p' + p.i + '_' + fi;
      img.alt = '帧' + (fi + 1);
      img.onerror = function() {
        this.style.display = 'none';
      };
      fb.appendChild(img);
    })(f);
  }
}

/**
 * 添加视频标签事件监听
 * 在 DOM 加载后调用
 */
function _initVideoEventHandlers() {
  var vid = document.getElementById('dcPracticeVideo');
  if (!vid) return;

  // 监听播放
  vid.addEventListener('play', function() {
    console.log('[Video Event] play');
  });

  // 监听暂停
  vid.addEventListener('pause', function() {
    console.log('[Video Event] pause');
  });

  // 监听错误
  vid.addEventListener('error', function(e) {
    console.error('[Video Error]', e);
    var top = document.getElementById('dcPracticeTop');
    if (top && vid.style.display !== 'none') {
      vid.style.display = 'none';
      var msg = document.createElement('div');
      msg.className = 'dc-practice-no-clip';
      msg.textContent = '视频加载失败（错误码: ' + (vid.error ? vid.error.code : '?') + '）';
      msg.style.cssText = 'padding:20px;text-align:center;color:#999;font-size:14px';
      top.appendChild(msg);
    }
  });

  // 监听视频能否播放
  vid.addEventListener('canplay', function() {
    console.log('[Video Event] canplay');
  });

  // 监听视频metadata加载
  vid.addEventListener('loadedmetadata', function() {
    console.log('[Video Event] loadedmetadata');
  });
}

// 在页面加载后初始化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initVideoEventHandlers);
} else {
  _initVideoEventHandlers();
}

/**
 * 修复 dcPracticeOpen() 中的播放按钮行为
 * 改为显式点击播放，而不依赖 autoplay
 */
var _dcPracticeData = null, _dcPracticeIdx = 0;

function dcPracticeOpen(id, phrases, idx, strip) {
  _dcPracticeData = {
    id: id,
    phrases: phrases,
    strip: strip || 4
  };
  _dcPracticeIdx = idx;

  var btn = event && event.target;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 加载中...';
  }

  document.getElementById('dcPracticeOverlay').classList.add('active');
  document.body.style.overflow = 'hidden';

  setTimeout(function() {
    dcPracticeRender();
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⏯ 跟练';
    }
  }, 300);
}

// 导出供 HTML 调用
window.dcPracticeRender = dcPracticeRender;
window.dcPracticeOpen = dcPracticeOpen;
window._initVideoEventHandlers = _initVideoEventHandlers;
