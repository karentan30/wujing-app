/* ═══ 页面卸载清理（防内存泄漏）═══ */

/**
 * 全局定时器和事件监听器注册表
 * 用于在页面卸载时自动清理所有资源
 */
var _cleanupRegistry = {
  timers: [],      // { type: 'timeout'|'interval', id: number }
  listeners: [],   // { element, event, handler, options }
  intervals: {},   // { id: { fn, timer } } 用于强制中止
  pendingRequests: [] // 待清理的 fetch 请求
};

/**
 * 1. 覆盖原生 setTimeout/setInterval，自动追踪
 */
var _origSetTimeout = window.setTimeout;
window.setTimeout = function(fn, delay) {
  var id = _origSetTimeout(fn, delay);
  _cleanupRegistry.timers.push({ type: 'timeout', id: id });
  return id;
};

var _origSetInterval = window.setInterval;
window.setInterval = function(fn, delay) {
  var id = _origSetInterval(fn, delay);
  _cleanupRegistry.timers.push({ type: 'interval', id: id });
  return id;
};

/**
 * 2. 覆盖 clearTimeout/clearInterval
 */
var _origClearTimeout = window.clearTimeout;
window.clearTimeout = function(id) {
  _cleanupRegistry.timers = _cleanupRegistry.timers.filter(function(t) {
    return t.id !== id;
  });
  return _origClearTimeout(id);
};

var _origClearInterval = window.clearInterval;
window.clearInterval = function(id) {
  _cleanupRegistry.timers = _cleanupRegistry.timers.filter(function(t) {
    return t.id !== id;
  });
  return _origClearInterval(id);
};

/**
 * 3. 创建追踪式的 addEventListener
 */
var _origAddEventListener = Element.prototype.addEventListener;
Element.prototype.addEventListener = function(event, handler, options) {
  _origAddEventListener.call(this, event, handler, options);
  _cleanupRegistry.listeners.push({
    element: this,
    event: event,
    handler: handler,
    options: options
  });
};

/**
 * 4. 创建追踪式的 removeEventListener（自动清理注册表）
 */
var _origRemoveEventListener = Element.prototype.removeEventListener;
Element.prototype.removeEventListener = function(event, handler, options) {
  _origRemoveEventListener.call(this, event, handler, options);
  _cleanupRegistry.listeners = _cleanupRegistry.listeners.filter(function(l) {
    return !(l.element === this && l.event === event && l.handler === handler);
  });
};

/**
 * 5. 监听页面卸载，清理所有资源
 */
window.addEventListener('beforeunload', function(e) {
  console.log('[Cleanup] beforeunload 事件触发，开始清理资源...');

  try {
    // 清理所有定时器
    _cleanupRegistry.timers.forEach(function(t) {
      if (t.type === 'timeout') {
        _origClearTimeout(t.id);
      } else if (t.type === 'interval') {
        _origClearInterval(t.id);
      }
    });
    _cleanupRegistry.timers = [];
    console.log('[Cleanup] ✓ 已清理所有定时器');
  } catch (e) {
    console.error('[Cleanup] 定时器清理失败', e);
  }

  try {
    // 移除所有事件监听器
    _cleanupRegistry.listeners.forEach(function(l) {
      try {
        l.element.removeEventListener(l.event, l.handler, l.options);
      } catch (e) {
        console.warn('[Cleanup] 移除监听失败', e);
      }
    });
    _cleanupRegistry.listeners = [];
    console.log('[Cleanup] ✓ 已清理所有事件监听器');
  } catch (e) {
    console.error('[Cleanup] 事件监听清理失败', e);
  }

  try {
    // 清理全局对象引用
    if (typeof _dcPracticeData !== 'undefined') {
      _dcPracticeData = null;
    }
    if (typeof DC_DATA !== 'undefined') {
      DC_DATA = null;
    }
    if (typeof CURRENT_USER !== 'undefined') {
      CURRENT_USER = null;
    }
    console.log('[Cleanup] ✓ 已清理全局对象');
  } catch (e) {
    console.error('[Cleanup] 全局对象清理失败', e);
  }

  try {
    // 中止所有待清理的 fetch 请求
    if (window.AbortController) {
      _cleanupRegistry.pendingRequests.forEach(function(controller) {
        try {
          controller.abort();
        } catch (e) {}
      });
      _cleanupRegistry.pendingRequests = [];
    }
    console.log('[Cleanup] ✓ 已中止待清理的请求');
  } catch (e) {
    console.error('[Cleanup] 请求清理失败', e);
  }
});

/**
 * 6. 页面卸载后清理（unload 事件）
 */
window.addEventListener('unload', function(e) {
  console.log('[Cleanup] unload 事件触发，进行最终清理...');

  try {
    // 停止所有音视频播放
    document.querySelectorAll('video, audio').forEach(function(el) {
      try {
        el.pause();
        el.src = '';
        el.load();
      } catch (e) {}
    });
    console.log('[Cleanup] ✓ 已停止所有媒体播放');
  } catch (e) {
    console.error('[Cleanup] 媒体清理失败', e);
  }

  try {
    // 发送最后一条埋点（同步，确保能发出去）
    if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
      var data = JSON.stringify({
        event: 'page_unload',
        timestamp: Date.now(),
        source: 'wujing'
      });
      // 使用 sendBeacon 确保在页面卸载前发送
      navigator.sendBeacon('/api/analytics', data);
    }
    console.log('[Cleanup] ✓ 已发送卸载埋点');
  } catch (e) {
    console.error('[Cleanup] 埋点发送失败', e);
  }
});

/**
 * 7. 监听标签页/窗口失焦（visibilitychange）
 * 在页面失焦时暂停资源消耗（可选优化）
 */
document.addEventListener('visibilitychange', function() {
  if (document.hidden) {
    // 页面失焦：暂停视频、音乐播放，减少资源消耗
    console.log('[Visibility] 页面失焦，暂停媒体播放');
    document.querySelectorAll('video, audio').forEach(function(el) {
      if (!el.paused) {
        el.setAttribute('data-was-playing', '1');
        el.pause();
      }
    });
  } else {
    // 页面重新获焦：可选择恢复播放
    console.log('[Visibility] 页面获焦');
  }
});

/**
 * 8. 监听页面刷新（beforeunload）
 * 给用户刷新的最后机会
 */
var _hasUnsavedChanges = false;

function _markUnsavedChanges() {
  _hasUnsavedChanges = true;
}

window.addEventListener('beforeunload', function(e) {
  if (_hasUnsavedChanges) {
    e.preventDefault();
    e.returnValue = '你有未保存的更改，确定要离开吗？';
    return e.returnValue;
  }
});

/**
 * 9. 创建带中止功能的 fetch（用于长时间请求）
 */
function fetchWithAbort(url, opts) {
  var controller = new (typeof AbortController !== 'undefined' ? AbortController : function() {
    this.signal = {};
  })();

  opts = opts || {};
  opts.signal = controller.signal;

  // 记录待清理的请求
  if (typeof AbortController !== 'undefined') {
    _cleanupRegistry.pendingRequests.push(controller);
  }

  return fetch(url, opts)
    .then(function(res) {
      // 请求成功，从待清理列表移除
      var idx = _cleanupRegistry.pendingRequests.indexOf(controller);
      if (idx !== -1) {
        _cleanupRegistry.pendingRequests.splice(idx, 1);
      }
      return res;
    })
    .catch(function(err) {
      // 请求失败或被中止
      var idx = _cleanupRegistry.pendingRequests.indexOf(controller);
      if (idx !== -1) {
        _cleanupRegistry.pendingRequests.splice(idx, 1);
      }
      throw err;
    });
}

/**
 * 10. 内存泄漏检测（开发时可用）
 */
function _logCleanupStats() {
  console.log('[Cleanup Stats]', {
    activeTimers: _cleanupRegistry.timers.length,
    activeListeners: _cleanupRegistry.listeners.length,
    pendingRequests: _cleanupRegistry.pendingRequests.length
  });
}

// 定时打印清理统计（可选，仅用于开发调试）
if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
  setInterval(_logCleanupStats, 30000);
}

console.log('[Cleanup Handler] 页面卸载清理处理器已启用');

// 导出供全局使用
window._markUnsavedChanges = _markUnsavedChanges;
window._logCleanupStats = _logCleanupStats;
window.fetchWithAbort = fetchWithAbort;
