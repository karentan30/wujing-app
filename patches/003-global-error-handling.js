/* ═══ 全局错误处理 ═══ */

/**
 * 1. 捕获同步 JS 错误
 */
window.onerror = function(message, source, lineno, colno, error) {
  console.error('[JS Error]', {
    message: message,
    source: source,
    line: lineno,
    col: colno,
    stack: error && error.stack
  });

  // 上报到埋点系统
  try {
    if (typeof WJ !== 'undefined' && WJ && WJ.track) {
      WJ.track('js_error', {
        message: String(message).slice(0, 100),
        source: String(source || '').slice(0, 100),
        lineno: lineno,
        colno: colno,
        stack: error ? String(error.stack).slice(0, 500) : ''
      });
    }
  } catch (e) {
    console.error('[Analytics] 埋点失败', e);
  }

  // 显示用户友好提示（仅在严重错误时）
  if (
    message &&
    (message.indexOf('Cannot read') !== -1 ||
      message.indexOf('is not a function') !== -1 ||
      message.indexOf('Cannot set') !== -1)
  ) {
    if (typeof toast === 'function') {
      toast('⚠️ 应用遇到问题，请刷新重试');
    }
  }

  // 返回 true 阻止默认错误处理
  return true;
};

/**
 * 2. 捕获未处理的 Promise rejection
 */
window.onunhandledrejection = function(event) {
  var err = event.reason;
  console.error('[Unhandled Promise Rejection]', err);

  // 上报到埋点
  try {
    if (typeof WJ !== 'undefined' && WJ && WJ.track) {
      WJ.track('promise_rejection', {
        message: err ? String(err.message || err).slice(0, 100) : 'unknown',
        stack: err && err.stack ? String(err.stack).slice(0, 500) : ''
      });
    }
  } catch (e) {
    console.error('[Analytics] 埋点失败', e);
  }

  // 重要：preventDefault() 阻止浏览器默认崩溃处理
  // 否则 Chrome 会显示 "Uncaught (in promise)" 错误并停止脚本执行
  event.preventDefault();
};

/**
 * 3. 包装所有 setTimeout/setInterval，捕获执行时错误
 */
var _origSetTimeout = window.setTimeout;
window.setTimeout = function(fn, delay, args) {
  return _origSetTimeout(function() {
    try {
      if (typeof fn === 'function') {
        fn.apply(this, arguments);
      }
    } catch (err) {
      console.error('[setTimeout Error]', err);
      window.onerror(
        err.message || 'unknown',
        'setTimeout',
        0,
        0,
        err
      );
    }
  }, delay, args);
};

var _origSetInterval = window.setInterval;
window.setInterval = function(fn, delay, args) {
  return _origSetInterval(function() {
    try {
      if (typeof fn === 'function') {
        fn.apply(this, arguments);
      }
    } catch (err) {
      console.error('[setInterval Error]', err);
      window.onerror(
        err.message || 'unknown',
        'setInterval',
        0,
        0,
        err
      );
    }
  }, delay, args);
};

/**
 * 4. 为所有 fetch 添加错误上报（装饰原有的 fetch 包装器）
 * 注意：这需要放在 fetch 超时保护代码之后执行
 */
(function() {
  var _fetchBeforeErrorHandler = window.fetch;

  window.fetch = function(url, opts) {
    return _fetchBeforeErrorHandler(url, opts)
      .catch(function(err) {
        console.error('[Fetch Error]', {
          url: url,
          error: err.message
        });

        // 上报到埋点
        try {
          if (typeof WJ !== 'undefined' && WJ && WJ.track) {
            WJ.track('fetch_error', {
              url: String(url || '').slice(0, 200),
              message: err ? String(err.message || err) : 'unknown'
            });
          }
        } catch (e) {
          console.error('[Analytics] 埋点失败', e);
        }

        // 重新抛出，让调用方处理
        throw err;
      });
  };
})();

/**
 * 5. 保护 JSON.parse（常见错误源）
 */
var _origJsonParse = JSON.parse;
JSON.parse = function(text, reviver) {
  try {
    return _origJsonParse(text, reviver);
  } catch (err) {
    console.error('[JSON.parse Error]', {
      text: String(text || '').slice(0, 100),
      error: err.message
    });
    throw err;
  }
};

/**
 * 6. 捕获 Console 错误（方便调试）
 */
var _origConsoleError = console.error;
console.error = function() {
  var args = Array.prototype.slice.call(arguments);
  _origConsoleError.apply(console, args);

  // 如果错误信息包含特定字段，上报
  var msg = args.join(' ');
  if (msg && (msg.indexOf('[') === 0 || msg.indexOf('Error') !== -1)) {
    try {
      if (typeof WJ !== 'undefined' && WJ && WJ.track) {
        WJ.track('console_error', {
          message: msg.slice(0, 200)
        });
      }
    } catch (e) {}
  }
};

/**
 * 7. 全局异常处理初始化日志
 */
console.log('[Error Handler] 全局错误处理已启用');
