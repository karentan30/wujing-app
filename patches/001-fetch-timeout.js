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

// 保存原始 fetch（在 window.fetch 被重写前调用）
var _origFetchForTimeout = window.fetch;

// 为 fetch 添加超时保护
function _wrapFetchWithTimeout() {
  window.fetch = function(url, opts) {
    opts = opts || {};

    // 保留原有的设备 ID 添加逻辑
    try {
      var dev = localStorage.getItem('wj_device_id');
      if (dev) {
        if (!opts.headers) opts.headers = {};
        if (!opts.headers['X-Device-Id']) opts.headers['X-Device-Id'] = dev;
      }
    } catch (e) {}

    // 包装所有 fetch 调用为带超时的 Promise.race
    return _withTimeout(_origFetchForTimeout(url, opts), _FETCH_TIMEOUT)
      .catch(function(err) {
        // 显示用户友好的错误提示
        if (err.message && err.message.indexOf('超时') !== -1) {
          console.warn('[Fetch Timeout]', url, err);
          if (typeof toast === 'function') {
            toast('⏱ ' + err.message);
          }
        }
        throw err;
      });
  };
}

// 立即执行包装
_wrapFetchWithTimeout();

// 辅助函数：支持自动重试的 fetch
function fetchWithRetry(url, opts, retries) {
  retries = retries !== undefined ? retries : 2;

  return fetch(url, opts)
    .catch(function(err) {
      if (retries > 0 && err.message && err.message.indexOf('超时') !== -1) {
        console.log('[Fetch Retry]', url, '剩余重试次数:', retries);
        return fetchWithRetry(url, opts, retries - 1);
      }
      throw err;
    });
}
