#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 埋点统一入口（PostHog）

方案依据：docs/埋点与个人库落地-0730.md §方案①。

铁律：
  - 埋点永远不许影响主流程 —— 任何异常都吞掉，绝不 raise 到业务代码。
  - 没配 POSTHOG_KEY → disabled，静默 no-op，不炸生产、不阻塞。
  - 服务端只埋「前端埋不准/会漏」的事件：支付履约成功 / 拆解完成 / practice_repeat /
    score_improved（这些发生在后台线程或回调里，前端不一定在场）。
  - 全套里最重要的两个事件是 practice_repeat 和 score_improved —— 它们 = aha。
    宁可别的漏，这俩必须准（在 my_works.submit_score 里服务端补打）。

前端埋点走 WJ.track（本文件 FRONTEND_SNIPPET 提供，供前端页面内联；参见 §2.4 的接线）。
"""
import os

try:
    from posthog import Posthog  # pip install posthog
    _POSTHOG_IMPORT_OK = True
except Exception:
    Posthog = None
    _POSTHOG_IMPORT_OK = False


# ── 单例客户端：缺 key → disabled，静默 ──
_PH = None
if _POSTHOG_IMPORT_OK:
    try:
        _PH = Posthog(
            project_api_key=os.environ.get("POSTHOG_KEY", ""),
            host=os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com"),
            disabled=not os.environ.get("POSTHOG_KEY"),  # 没配 key 就静默，不炸生产
        )
    except Exception:
        _PH = None


def track(distinct_id, event, props=None):
    """服务端埋点。

    distinct_id: 用 user_id（登录用户）；游客用 dance_id 兜底；再兜底 'guest'。
    event:       事件名（与 §1.2 事件清单一致）。
    props:       事件属性 dict。

    绝不 raise —— 埋点失败不许影响主流程（履约/拆解/写分数）。
    """
    if _PH is None:
        return
    try:
        properties = dict(props or {})
        # 服务端事件默认不给游客建 person（省 person 配额；与前端 identified_only 对齐）
        properties.setdefault("$process_person_profile",
                              bool(distinct_id) and str(distinct_id) not in ("guest", "None", ""))
        properties.setdefault("source_side", "server")
        _PH.capture(
            distinct_id=str(distinct_id or "guest"),
            event=event,
            properties=properties,
        )
    except Exception:
        pass  # 埋点永远不许影响主流程


def identify(distinct_id, props=None):
    """服务端 identify（可选）：注册/首次登录时给 person 补属性。异常吞掉。"""
    if _PH is None:
        return
    try:
        _PH.identify(distinct_id=str(distinct_id), properties=dict(props or {}))
    except Exception:
        pass


def flush():
    """进程退出前可调，确保队列里的事件发出去。异常吞掉。"""
    if _PH is None:
        return
    try:
        _PH.flush()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# 前端埋点封装（供 H5 页面内联到 <head>）
#   - 一次 posthog.init + 一个薄封装 WJ.track，自动附公共属性
#   - person_profiles=identified_only：省事件量，只给登录用户建 person
#   - autocapture=false：手动埋点为主，别乱抓
#   用法：把 render_frontend_snippet('phc_xxx') 的返回串塞进页面 <head>。
# ══════════════════════════════════════════════════════════════
FRONTEND_SNIPPET = r"""<!-- 舞镜埋点 · PostHog（注册/登录后调 WJ.setUser；游客态用匿名 distinct_id） -->
<script>
  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
  posthog.init('__POSTHOG_KEY__', {
    api_host: '__POSTHOG_HOST__',
    person_profiles: 'identified_only',   // 省事件量：只给登录用户建 person
    autocapture: false,                   // 手动埋点为主，别乱抓
    capture_pageview: true
  });

  // ── 舞镜统一埋点封装：自动附公共属性（is_logged_in / lang / platform）──
  window.WJ = {
    setUser: function(user){
      if(user && user.id){
        posthog.identify(String(user.id), { email: user.email, is_paid: !!user.is_paid });
        posthog.register({ is_logged_in: true });
      }
    },
    reset: function(){ try{ posthog.reset(); }catch(e){} },
    track: function(event, props){
      try{
        posthog.capture(event, Object.assign({
          is_logged_in: !!localStorage.getItem('wj_token'),
          lang: document.documentElement.lang || 'zh',
          platform: 'h5'
        }, props || {}));
      }catch(e){}
    }
  };
</script>"""


def render_frontend_snippet(posthog_key=None, posthog_host=None):
    """返回可直接内联进 H5 <head> 的埋点 snippet 字符串。

    posthog_key/host 缺省从环境变量读；供后端把 key 注入模板（避免前端硬编码）。
    """
    key = posthog_key or os.environ.get("POSTHOG_KEY", "")
    host = posthog_host or os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
    return (FRONTEND_SNIPPET
            .replace("__POSTHOG_KEY__", key)
            .replace("__POSTHOG_HOST__", host))
