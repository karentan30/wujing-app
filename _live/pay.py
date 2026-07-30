#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""舞镜 · 支付模块（¥9.9/一支舞 → 解锁并生成完整拆解卡）

渠道：
  - 微信支付 NATIVE 扫码（境内，免 ICP/H5 域名）
  - 支付宝当面付（face-to-face precreate → 扫码）
  - 海外 Stripe Checkout Session（信用卡）

铁律（这是真实收款，钱相关）：
  - 绝不硬编任何密钥；全部 os.environ 读；缺 key → 该渠道返回 503，不崩、不 mock 白嫖。
  - 幂等：所有回调用 `WHERE status!='paid'` 原子翻转 + rowcount 判定，重复回调不重复履约。
  - 验签：微信 MD5、支付宝 RSA2、Stripe HMAC-SHA256 timestamp+body，全部服务端验，绝不信前端。
  - 订单锁：SQLite 单连接 + 进程内 _ORDER_LOCK 串行化「翻 paid → 履约」临界区。
  - 金额校验：回调金额必须与本地下单金额一致，不符即拒。

移植自 Lumee server.online.py（微信/支付宝签名、统一下单、验签、幂等模式），
Stripe 为标准 Checkout Session + webhook 新建。会员逻辑未搬——舞镜是「一支舞一次解锁」。
"""
import os
import json
import time
import uuid
import hmac
import base64
import hashlib
import sqlite3
import datetime
import threading
import urllib.parse
import urllib.request
import urllib.error

from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

# 与 server.py / auto_decompose.py 保持同一路径
BASE_DIR = os.environ.get("WUJING_BASE_DIR", "/www/wujing-api")
DB_PATH = os.environ.get("WUJING_DB_PATH", os.path.join(BASE_DIR, "wujing.db"))
DATA_DIR = os.path.join(BASE_DIR, "data")

PRICE_CNY = float(os.environ.get("WJ_DANCE_PRICE_CNY", "9.9"))     # 境内 ¥9.9
PRICE_USD = float(os.environ.get("WJ_DANCE_PRICE_USD", "1.99"))    # 海外 Stripe 计价
PRODUCT_NAME = "舞镜 · 完整拆解卡（1 支舞）"

router = APIRouter(prefix="/api/pay", tags=["pay"])

# ── 订单锁：串行化「翻 paid → 履约」临界区，防并发回调重复履约 ──
_ORDER_LOCK = threading.Lock()


# ══════════════════════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════════════════════
def get_db():
    """短连接。isolation_level=None 手动 BEGIN；WAL 减少锁冲突。调用方负责 with 关闭。"""
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
    except Exception:
        pass
    return con


def init_orders_table():
    """舞镜订单表（一支舞一单）。幂等建表。"""
    con = get_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS orders(
            out_trade_no      TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL,
            dance_id          TEXT NOT NULL,
            amount            TEXT NOT NULL,          -- 元，字符串精确
            status            TEXT DEFAULT 'pending', -- pending / paid / failed
            channel           TEXT,                   -- wechat / alipay / stripe
            currency          TEXT DEFAULT 'CNY',     -- CNY / USD
            trade_no          TEXT,                   -- 渠道流水号
            breakdown_status  TEXT,                   -- '' / queued / processing / completed / failed
            created_at        TEXT,
            paid_at           TEXT
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_wj_orders_user ON orders(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_wj_orders_dance ON orders(user_id,dance_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_wj_orders_status ON orders(status)")
        # 存量表（付费门骨架建的）可能缺列 → 幂等补列，不破坏已有数据
        for ddl in (
            "ALTER TABLE orders ADD COLUMN dance_id TEXT",
            "ALTER TABLE orders ADD COLUMN breakdown_status TEXT",
            "ALTER TABLE orders ADD COLUMN currency TEXT DEFAULT 'CNY'",
            "ALTER TABLE orders ADD COLUMN channel TEXT",
            "ALTER TABLE orders ADD COLUMN trade_no TEXT",
        ):
            try:
                con.execute(ddl)
            except Exception:
                pass
        con.commit()
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════
# 鉴权：从 Authorization: Bearer <token> 解出 user_id（复用 auth.decode_token）
# ══════════════════════════════════════════════════════════════
def _user_id_from_auth(authorization):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization format")
    try:
        from auth import decode_token
        payload = decode_token(token)
        uid = payload.get("user_id")
        if not uid:
            raise ValueError("no user_id")
        return str(uid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def _user_id_optional(authorization):
    """可选登录：产品是「上传免费无需登录 → 要拆才付」，游客也能下单付费。
    有合法 token → 真实 user_id；无/非法 token → 匿名占位 'guest'（订单仍按 dance_id 履约解锁）。"""
    if not authorization:
        return "guest"
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return "guest"
    try:
        from auth import decode_token
        payload = decode_token(token)
        return str(payload.get("user_id") or "guest")
    except Exception:
        return "guest"


def _new_oid(prefix):
    return prefix + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]


def _now_iso():
    return datetime.datetime.now().isoformat()


def _client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return (request.client.host if request.client else "") or "127.0.0.1"


# ══════════════════════════════════════════════════════════════
# 履约钩子：付款成功 → 标记解锁 → 触发生成完整拆解卡（异步）
# ══════════════════════════════════════════════════════════════
def _dance_input_path(dance_id):
    """该 dance 的原始上传视频。免费预览拆解时已存 data/<id>/input.mp4。"""
    return os.path.join(DATA_DIR, dance_id, "input.mp4")


def _run_dance_breakdown(user_id, dance_id, out_trade_no, title="我的舞", genre="guofeng"):
    """后台任务：调用 auto_decompose 生成完整拆解卡，全程兜底并回写 breakdown_status。
    幂等：BackgroundTask 只在回调翻 paid 成功那一次被投递；此处再按 dance 产物存在性兜底一层。"""
    def _set_bd(st):
        try:
            with _ORDER_LOCK:
                con = get_db()
                con.execute("UPDATE orders SET breakdown_status=? WHERE out_trade_no=?",
                            (st, out_trade_no))
                con.commit()
                con.close()
        except Exception:
            pass

    _set_bd("processing")
    try:
        from auto_decompose import run_decompose
        video_path = _dance_input_path(dance_id)
        if not os.path.exists(video_path):
            # 没有源视频无法生成——标记 failed，前端提示重新上传该舞
            _set_bd("failed")
            print(f"[pay/fulfill] no source video for dance={dance_id} order={out_trade_no}")
            return
        # 用上传时落的 awaiting_payment 卡里的真实 title/genre/user_id（游客上传无 token）
        try:
            _aw = os.path.join(DATA_DIR, dance_id, "decompose.json")
            if os.path.exists(_aw):
                with open(_aw, "r", encoding="utf-8") as _f:
                    _meta = json.load(_f)
                if _meta.get("status") == "awaiting_payment":
                    title = _meta.get("title") or title
                    genre = _meta.get("genre") or genre
                    # 保留上传时的真实归属：游客上传为 None（匿名可读），别用订单里的 'guest' 占位覆盖
                    if "user_id" in _meta:
                        user_id = _meta.get("user_id")
        except Exception:
            pass
        # 同步跑（本函数已在后台线程/BackgroundTask 里），run_decompose 内部全程兜底写 decompose.json
        run_decompose(dance_id, video_path, user_id, title, genre)
        # 以产物落地为准判定成功/失败
        dj = os.path.join(DATA_DIR, dance_id, "decompose.json")
        st = "failed"
        try:
            with open(dj, "r", encoding="utf-8") as f:
                st = "completed" if json.load(f).get("status") == "completed" else "failed"
        except Exception:
            pass
        _set_bd(st)
        print(f"[pay/fulfill] dance={dance_id} order={out_trade_no} breakdown={st}")
    except Exception as e:
        _set_bd("failed")
        print(f"[pay/fulfill] error dance={dance_id} order={out_trade_no}: {e}")


def _apply_paid_dance_unlock(con, user_id, dance_id, out_trade_no, background_tasks=None,
                             title="我的舞", genre="guofeng"):
    """付款成功统一履约（必须在 _ORDER_LOCK 内、且已确认订单本次刚翻 paid 后调用）。
    - 标记 breakdown_status=queued（占位，前端可立即轮询到"排队中"）
    - 投递后台任务生成完整拆解卡
    返回简短摘要供日志。
    """
    con.execute("UPDATE orders SET breakdown_status='queued' WHERE out_trade_no=?", (out_trade_no,))
    # 投递异步生成。BackgroundTasks（FastAPI）优先；notify 回调无 BackgroundTasks 时用裸线程兜底。
    if background_tasks is not None:
        background_tasks.add_task(_run_dance_breakdown, user_id, dance_id, out_trade_no, title, genre)
    else:
        threading.Thread(
            target=_run_dance_breakdown,
            args=(user_id, dance_id, out_trade_no, title, genre),
            daemon=True,
        ).start()
    return f"unlock dance={dance_id} user={str(user_id)[:8]} order={out_trade_no}"


def _mark_paid_and_fulfill(out_trade_no, trade_no, channel, paid_amount_check,
                           background_tasks=None):
    """幂等翻 paid + 履约的统一临界区。
    paid_amount_check: 回调传回的已付金额（渠道原始单位）→ 与本地下单金额比对。
        - wechat: 分(int) → 与 amount*100 比
        - alipay/stripe: 元(str/float) → 与 amount 比
    返回 (result_str, http_ok)：
        'already'  幂等命中（此前已 paid）
        'ok'       本次翻 paid 并投递履约
        'unknown'  订单不存在
        'amount_mismatch' 金额不符
    """
    with _ORDER_LOCK:
        con = get_db()
        try:
            row = con.execute(
                "SELECT user_id,dance_id,amount,status,currency FROM orders WHERE out_trade_no=?",
                (out_trade_no,)).fetchone()
            if not row:
                return "unknown"
            user_id, dance_id, amount, status, currency = (
                row["user_id"], row["dance_id"], row["amount"], row["status"], row["currency"])

            # 金额校验（防伪造/篡改回调）
            try:
                if channel == "wechat":
                    ok_amt = (int(round(float(amount) * 100)) == int(paid_amount_check))
                else:
                    ok_amt = (abs(float(paid_amount_check) - float(amount)) < 0.005)
            except Exception:
                ok_amt = False
            if not ok_amt:
                print(f"[pay/{channel}] amount mismatch {paid_amount_check} != {amount} oid={out_trade_no}")
                return "amount_mismatch"

            if status == "paid":
                return "already"  # 幂等

            # 原子翻 paid：WHERE status!='paid'，rowcount==1 才是本次赢得履约的调用
            changed = con.execute(
                "UPDATE orders SET status='paid', trade_no=?, channel=?, paid_at=? "
                "WHERE out_trade_no=? AND status!='paid'",
                (trade_no or "", channel, _now_iso(), out_trade_no)).rowcount
            if not changed:
                con.commit()
                return "already"

            summary = _apply_paid_dance_unlock(
                con, user_id, dance_id, out_trade_no, background_tasks=background_tasks)
            con.commit()
            print(f"[pay/{channel}] PAID {out_trade_no} {summary}")
            return "ok"
        finally:
            con.close()


# ══════════════════════════════════════════════════════════════
# 微信支付 NATIVE  （移植自 Lumee _wx_* 工具 + create/notify/query）
# ══════════════════════════════════════════════════════════════
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID", "")
WECHAT_MCH_ID = os.environ.get("WECHAT_MCH_ID", "")
WECHAT_API_KEY = os.environ.get("WECHAT_API_KEY", "")          # APIv2 商户密钥
WECHAT_NOTIFY_URL = os.environ.get(
    "WECHAT_NOTIFY_URL", "https://wujing.mylumee.app/api/pay/wechat/notify")


def _wechat_ready():
    return bool(WECHAT_APP_ID and WECHAT_MCH_ID and WECHAT_API_KEY)


def _wx_sign(params, key):
    items = sorted((k, v) for k, v in params.items() if k != "sign" and v not in ("", None))
    raw = "&".join("%s=%s" % (k, v) for k, v in items) + "&key=" + key
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def _wx_to_xml(params):
    return "<xml>" + "".join("<%s><![CDATA[%s]]></%s>" % (k, v, k)
                             for k, v in params.items()) + "</xml>"


def _wx_from_xml(text):
    import xml.etree.ElementTree as _ET
    try:
        root = _ET.fromstring(text)
        return {c.tag: (c.text or "") for c in root}
    except Exception:
        return {}


def _wx_unifiedorder(out_trade_no, total_fee_cents, body_desc, client_ip):
    import random as _rd
    import string as _st
    nonce = "".join(_rd.choices(_st.ascii_letters + _st.digits, k=24))
    params = {
        "appid": WECHAT_APP_ID, "mch_id": WECHAT_MCH_ID, "nonce_str": nonce,
        "body": body_desc, "out_trade_no": out_trade_no,
        "total_fee": str(int(total_fee_cents)),
        "spbill_create_ip": client_ip or "127.0.0.1",
        "notify_url": WECHAT_NOTIFY_URL, "trade_type": "NATIVE",
        "product_id": out_trade_no,
    }
    params["sign"] = _wx_sign(params, WECHAT_API_KEY)
    req = urllib.request.Request(
        "https://api.mch.weixin.qq.com/pay/unifiedorder",
        _wx_to_xml(params).encode("utf-8"),
        {"Content-Type": "application/xml"})
    return _wx_from_xml(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))


def _wx_orderquery(out_trade_no):
    import random as _rd
    import string as _st
    nonce = "".join(_rd.choices(_st.ascii_letters + _st.digits, k=24))
    params = {"appid": WECHAT_APP_ID, "mch_id": WECHAT_MCH_ID,
              "out_trade_no": out_trade_no, "nonce_str": nonce}
    params["sign"] = _wx_sign(params, WECHAT_API_KEY)
    req = urllib.request.Request(
        "https://api.mch.weixin.qq.com/pay/orderquery",
        _wx_to_xml(params).encode("utf-8"),
        {"Content-Type": "application/xml"})
    return _wx_from_xml(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))


@router.post("/wechat/create")
async def wechat_create(payload: dict, authorization: str = Header(None)):
    """微信 NATIVE 下单。body: {dance_id}。返回 {code_url} 供前端生成二维码。"""
    user_id = _user_id_optional(authorization)
    dance_id = str(payload.get("dance_id", "") or "").strip()
    if not dance_id:
        raise HTTPException(status_code=400, detail="缺少 dance_id")
    if not _wechat_ready():
        raise HTTPException(status_code=503, detail="微信支付暂未开放")
    oid = _new_oid("WJWX")
    con = get_db()
    try:
        con.execute(
            "INSERT INTO orders(out_trade_no,user_id,dance_id,amount,status,channel,currency,breakdown_status,created_at)"
            " VALUES(?,?,?,?, 'pending','wechat','CNY','',?)",
            (oid, user_id, dance_id, ("%.2f" % PRICE_CNY), _now_iso()))
        con.commit()
    finally:
        con.close()
    try:
        # spbill_create_ip 无法在此拿到 request（用占位；微信 NATIVE 对 IP 校验宽松）
        r = _wx_unifiedorder(oid, int(round(PRICE_CNY * 100)), PRODUCT_NAME, "127.0.0.1")
    except Exception as e:
        print(f"[pay/wechat/create] 下单异常 {e}")
        raise HTTPException(status_code=502, detail="发起支付失败，请稍后再试")
    if r.get("return_code") == "SUCCESS" and r.get("result_code") == "SUCCESS" and r.get("code_url"):
        return {"ok": True, "out_trade_no": oid, "code_url": r["code_url"], "amount": PRICE_CNY}
    msg = r.get("err_code_des") or r.get("return_msg") or "未知错误"
    print(f"[pay/wechat/create] 下单失败 {r}")
    raise HTTPException(status_code=400, detail="微信下单失败：" + msg)


@router.post("/wechat/notify")
async def wechat_notify(request: Request):
    """微信异步回调（XML）。验签 → 幂等翻 paid → 履约。必须返回微信要求的 XML。"""
    ok_xml = _wx_to_xml({"return_code": "SUCCESS", "return_msg": "OK"})
    fail_xml = _wx_to_xml({"return_code": "FAIL", "return_msg": "verify failed"})
    if not _wechat_ready():
        return PlainTextResponse(fail_xml, media_type="application/xml")
    raw = (await request.body()).decode("utf-8", "replace")
    data = _wx_from_xml(raw)
    sign = data.pop("sign", "")
    if not (sign and _wx_sign(data, WECHAT_API_KEY) == sign):
        print("[pay/wechat/notify] 验签失败")
        return PlainTextResponse(fail_xml, media_type="application/xml")
    if data.get("return_code") != "SUCCESS" or data.get("result_code") != "SUCCESS":
        return PlainTextResponse(ok_xml, media_type="application/xml")
    oid = data.get("out_trade_no", "")
    res = _mark_paid_and_fulfill(
        oid, data.get("transaction_id", ""), "wechat", data.get("total_fee", ""),
        background_tasks=None)  # notify 无 BackgroundTasks → 裸线程履约
    if res in ("ok", "already"):
        return PlainTextResponse(ok_xml, media_type="application/xml")
    return PlainTextResponse(fail_xml, media_type="application/xml")


@router.get("/wechat/query")
async def wechat_query(out_trade_no: str, authorization: str = Header(None)):
    """前端轮询：本地 pending 时主动向微信查单兜底（回调可能延迟/丢失）。"""
    _user_id_optional(authorization)
    return _pay_status_query(out_trade_no, channel="wechat")


# ══════════════════════════════════════════════════════════════
# 支付宝当面付  （移植自 Lumee get_alipay + _pay_alipay_qr/notify/query）
# ══════════════════════════════════════════════════════════════
ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
ALIPAY_PRIV_PATH = os.environ.get("ALIPAY_PRIVATE_KEY_PATH", "")
ALIPAY_PUB_PATH = os.environ.get("ALIPAY_PUBLIC_KEY_PATH", "")
ALIPAY_GATEWAY = os.environ.get("ALIPAY_GATEWAY", "https://openapi.alipay.com/gateway.do")
ALIPAY_NOTIFY_URL = os.environ.get(
    "ALIPAY_NOTIFY_URL", "https://wujing.mylumee.app/api/pay/alipay/notify")
ALIPAY_DEBUG = os.environ.get("ALIPAY_DEBUG", "").strip().lower() in ("1", "true", "yes")
_ALIPAY_CACHE = {}


def get_alipay():
    """懒加载支付宝客户端；密钥/SDK 缺失 → None（接口回退 503，不 mock）。"""
    if "c" in _ALIPAY_CACHE:
        return _ALIPAY_CACHE["c"]
    if not (ALIPAY_APP_ID and ALIPAY_PRIV_PATH and ALIPAY_PUB_PATH):
        return None
    try:
        from alipay import AliPay
        with open(ALIPAY_PRIV_PATH) as f:
            priv = f.read()
        with open(ALIPAY_PUB_PATH) as f:
            pub = f.read()
        _ALIPAY_CACHE["c"] = AliPay(
            appid=ALIPAY_APP_ID, app_notify_url=ALIPAY_NOTIFY_URL,
            app_private_key_string=priv, alipay_public_key_string=pub,
            sign_type="RSA2", debug=ALIPAY_DEBUG)
        print("[alipay] client ready (debug=%s)" % ALIPAY_DEBUG)
        return _ALIPAY_CACHE["c"]
    except Exception as e:
        print(f"[alipay] init failed: {e}")
        return None


@router.post("/alipay/create")
async def alipay_create(payload: dict, authorization: str = Header(None)):
    """支付宝当面付：alipay.trade.precreate → 返回 qr_code 给前端生成二维码。"""
    user_id = _user_id_optional(authorization)
    dance_id = str(payload.get("dance_id", "") or "").strip()
    if not dance_id:
        raise HTTPException(status_code=400, detail="缺少 dance_id")
    client = get_alipay()
    if not client:
        raise HTTPException(status_code=503, detail="支付宝暂未开放")
    oid = _new_oid("WJAL")
    con = get_db()
    try:
        con.execute(
            "INSERT INTO orders(out_trade_no,user_id,dance_id,amount,status,channel,currency,breakdown_status,created_at)"
            " VALUES(?,?,?,?, 'pending','alipay','CNY','',?)",
            (oid, user_id, dance_id, ("%.2f" % PRICE_CNY), _now_iso()))
        con.commit()
    finally:
        con.close()
    try:
        resp = client.api_alipay_trade_precreate(
            subject=PRODUCT_NAME, out_trade_no=oid, total_amount=("%.2f" % PRICE_CNY))
    except Exception as e:
        print(f"[pay/alipay/create] precreate 异常 {e}")
        raise HTTPException(status_code=502, detail="发起支付失败，请稍后再试")
    if str(resp.get("code")) != "10000" or not resp.get("qr_code"):
        print(f"[pay/alipay/create] 失败 {resp}")
        raise HTTPException(status_code=400,
                            detail="支付宝下单失败：" + (resp.get("sub_msg") or resp.get("msg") or "未知错误"))
    return {"ok": True, "out_trade_no": oid, "qr_code": resp["qr_code"], "amount": PRICE_CNY}


@router.post("/alipay/notify")
async def alipay_notify(request: Request):
    """支付宝异步回调（form-urlencoded）。RSA2 验签 → 幂等翻 paid → 履约。返回纯文本 success/fail。"""
    client = get_alipay()
    if not client:
        return PlainTextResponse("fail")
    form = await request.form()
    data = {k: v for k, v in form.items()}
    sign = data.pop("sign", None)
    data.pop("sign_type", None)
    try:
        verified = bool(sign and client.verify(data, sign))
    except Exception as e:
        print(f"[pay/alipay/notify] verify err {e}")
        verified = False
    if not verified:
        print("[pay/alipay/notify] 验签失败")
        return PlainTextResponse("fail")
    if data.get("trade_status", "") not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return PlainTextResponse("success")   # 非终态（如 WAIT_BUYER_PAY）先 ack
    oid = data.get("out_trade_no", "")
    res = _mark_paid_and_fulfill(
        oid, data.get("trade_no", ""), "alipay", data.get("total_amount", ""),
        background_tasks=None)
    # 支付宝要求验真+入账成功才回 success；不成功回 fail 让其重试（幂等已保证不重复履约）
    return PlainTextResponse("success" if res in ("ok", "already") else "fail")


@router.get("/alipay/query")
async def alipay_query(out_trade_no: str, authorization: str = Header(None)):
    _user_id_optional(authorization)
    return _pay_status_query(out_trade_no, channel="alipay")


# ══════════════════════════════════════════════════════════════
# Stripe Checkout Session + webhook  （标准实现·新建）
# ══════════════════════════════════════════════════════════════
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_SUCCESS_URL = os.environ.get(
    "STRIPE_SUCCESS_URL", "https://wujing.mylumee.app/?pay=success&oid={CHECKOUT_SESSION_ID}")
STRIPE_CANCEL_URL = os.environ.get(
    "STRIPE_CANCEL_URL", "https://wujing.mylumee.app/?pay=cancel")


def _stripe_ready():
    return bool(STRIPE_SECRET_KEY)


def _stripe_request(method, path, form=None, timeout=20):
    """Stripe REST：Bearer sk_…，x-www-form-urlencoded。返回 (code, json)。"""
    url = "https://api.stripe.com" + path
    data = urllib.parse.urlencode(form, doseq=True).encode("utf-8") if form else None
    headers = {"Authorization": "Bearer " + STRIPE_SECRET_KEY,
               "Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode(), json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw or "{}")
        except Exception:
            detail = {"raw": raw[:300]}
        return e.code, detail


@router.post("/stripe/create")
async def stripe_create(payload: dict, authorization: str = Header(None)):
    """海外 Stripe Checkout Session（mode=payment，price_data 动态计价 PRICE_USD）。
    返回 {url} 前端跳转 Stripe 托管收银台。out_trade_no 写入 metadata + client_reference_id 供回调对账。"""
    user_id = _user_id_optional(authorization)
    dance_id = str(payload.get("dance_id", "") or "").strip()
    if not dance_id:
        raise HTTPException(status_code=400, detail="缺少 dance_id")
    if not _stripe_ready():
        raise HTTPException(status_code=503, detail="Stripe 暂未开放")
    oid = _new_oid("WJST")
    con = get_db()
    try:
        con.execute(
            "INSERT INTO orders(out_trade_no,user_id,dance_id,amount,status,channel,currency,breakdown_status,created_at)"
            " VALUES(?,?,?,?, 'pending','stripe','USD','',?)",
            (oid, user_id, dance_id, ("%.2f" % PRICE_USD), _now_iso()))
        con.commit()
    finally:
        con.close()
    form = {
        "mode": "payment",
        "success_url": STRIPE_SUCCESS_URL,
        "cancel_url": STRIPE_CANCEL_URL,
        "client_reference_id": oid,
        "metadata[out_trade_no]": oid,
        "metadata[dance_id]": dance_id,
        "metadata[user_id]": user_id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(int(round(PRICE_USD * 100))),  # 分
        "line_items[0][price_data][product_data][name]": PRODUCT_NAME,
    }
    code, j = _stripe_request("POST", "/v1/checkout/sessions", form)
    if code != 200 or not j.get("url"):
        print(f"[pay/stripe/create] 失败 code={code} {str(j)[:200]}")
        raise HTTPException(status_code=502, detail="Stripe 下单失败")
    # 记录 session id 便于查单兜底
    con = get_db()
    try:
        con.execute("UPDATE orders SET trade_no=? WHERE out_trade_no=?", (j.get("id", ""), oid))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "out_trade_no": oid, "url": j["url"], "amount": PRICE_USD, "currency": "USD"}


def _stripe_verify_sig(payload_bytes, sig_header, secret, tolerance=300):
    """Stripe webhook 验签：Stripe-Signature: t=<ts>,v1=<hmac_sha256(secret, "t.body")>。
    返回 True/False。防重放：|now-t| 超 tolerance 秒拒。"""
    if not (sig_header and secret):
        return False
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not (ts and v1):
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
    except Exception:
        return False
    signed = ts.encode() + b"." + payload_bytes
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """Stripe webhook：验签 → checkout.session.completed → 幂等翻 paid → 履约。"""
    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"received": False}, status_code=503)
    body = await request.body()
    if not _stripe_verify_sig(body, stripe_signature, STRIPE_WEBHOOK_SECRET):
        print("[pay/stripe/webhook] 验签失败")
        raise HTTPException(status_code=400, detail="invalid signature")
    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="bad payload")
    etype = event.get("type", "")
    if etype != "checkout.session.completed":
        return {"received": True, "ignored": etype}
    sess = event.get("data", {}).get("object", {})
    if sess.get("payment_status") != "paid":
        return {"received": True, "unpaid": True}
    md = sess.get("metadata", {}) or {}
    oid = md.get("out_trade_no") or sess.get("client_reference_id", "")
    if not oid:
        print("[pay/stripe/webhook] 缺 out_trade_no")
        return {"received": True, "no_oid": True}
    # Stripe amount_total 为分(USD) → 转元校验
    paid = (sess.get("amount_total", 0) or 0) / 100.0
    res = _mark_paid_and_fulfill(oid, sess.get("payment_intent", "") or sess.get("id", ""),
                                 "stripe", paid, background_tasks=None)
    return {"received": True, "result": res}


# ══════════════════════════════════════════════════════════════
# 统一订单状态查询（前端轮询：下单→支付→解锁→出卡）
# ══════════════════════════════════════════════════════════════
def _pay_status_query(out_trade_no, channel=None):
    """本地状态；若仍 pending 且是微信/支付宝 → 主动向渠道查单兜底（防回调延迟/丢失）。"""
    con = get_db()
    try:
        row = con.execute(
            "SELECT user_id,dance_id,amount,status,channel,breakdown_status "
            "FROM orders WHERE out_trade_no=?", (out_trade_no,)).fetchone()
    finally:
        con.close()
    if not row:
        return {"status": "unknown"}
    ch = row["channel"] or channel

    def _resp():
        con2 = get_db()
        try:
            r2 = con2.execute(
                "SELECT status,breakdown_status,dance_id FROM orders WHERE out_trade_no=?",
                (out_trade_no,)).fetchone()
        finally:
            con2.close()
        return {"status": r2["status"], "breakdown_status": r2["breakdown_status"] or "",
                "dance_id": r2["dance_id"], "out_trade_no": out_trade_no}

    if row["status"] == "paid":
        return _resp()

    # pending → 主动查单兜底
    try:
        if ch == "wechat" and _wechat_ready():
            q = _wx_orderquery(out_trade_no)
            if (q.get("return_code") == "SUCCESS" and q.get("result_code") == "SUCCESS"
                    and q.get("trade_state") == "SUCCESS"):
                _mark_paid_and_fulfill(out_trade_no, q.get("transaction_id", ""), "wechat",
                                       q.get("total_fee", ""), background_tasks=None)
        elif ch == "alipay":
            client = get_alipay()
            if client:
                q = client.api_alipay_trade_query(out_trade_no=out_trade_no)
                if (str(q.get("code")) == "10000"
                        and q.get("trade_status") in ("TRADE_SUCCESS", "TRADE_FINISHED")):
                    _mark_paid_and_fulfill(out_trade_no, q.get("trade_no", ""), "alipay",
                                           q.get("total_amount", ""), background_tasks=None)
        elif ch == "stripe" and _stripe_ready():
            # trade_no 存的是 session id → 查 session 支付状态
            sid = None
            con3 = get_db()
            try:
                rr = con3.execute("SELECT trade_no FROM orders WHERE out_trade_no=?",
                                  (out_trade_no,)).fetchone()
                sid = rr["trade_no"] if rr else None
            finally:
                con3.close()
            if sid and sid.startswith("cs_"):
                code, j = _stripe_request("GET", "/v1/checkout/sessions/" + sid)
                if code == 200 and j.get("payment_status") == "paid":
                    paid = (j.get("amount_total", 0) or 0) / 100.0
                    _mark_paid_and_fulfill(out_trade_no, j.get("payment_intent", "") or sid,
                                           "stripe", paid, background_tasks=None)
    except Exception as e:
        print(f"[pay/status] 查单兜底异常 {out_trade_no}: {e}")
    return _resp()


@router.get("/status")
async def pay_status(out_trade_no: str, authorization: str = Header(None)):
    """前端统一轮询接口：返回订单状态 + 拆解卡生成进度 breakdown_status。
    breakdown_status: '' / queued / processing / completed / failed
    完成后前端调 GET /api/decompose/{dance_id} 取完整拆解卡。"""
    _user_id_optional(authorization)
    return _pay_status_query(out_trade_no)


@router.get("/dance/{dance_id}/unlocked")
async def dance_unlocked(dance_id: str, authorization: str = Header(None)):
    """查某支舞是否已为当前用户解锁（存在一条 paid 订单即解锁）。前端用于门控下载完整拆解卡。"""
    user_id = _user_id_optional(authorization)
    con = get_db()
    try:
        row = con.execute(
            "SELECT out_trade_no,breakdown_status FROM orders "
            "WHERE user_id=? AND dance_id=? AND status='paid' "
            "ORDER BY paid_at DESC LIMIT 1", (user_id, dance_id)).fetchone()
    finally:
        con.close()
    if not row:
        return {"unlocked": False}
    return {"unlocked": True, "out_trade_no": row["out_trade_no"],
            "breakdown_status": row["breakdown_status"] or ""}
