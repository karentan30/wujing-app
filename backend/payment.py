"""
舞镜支付模块 - Stripe骨架 + 微信/支付宝 TODO桩
使用环境变量注入key，缺key时接口明确报错不崩。
"""
import os
import json
import time
import uuid
import hmac as _hmac
import hashlib
import datetime
import urllib.request
import urllib.parse
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from models import get_db
from auth import decode_token
from models import get_user_by_id

router = APIRouter()

# ---- Stripe 配置（均走env，不硬编码）----
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
# 单次深度分析 ¥9.9 → Stripe Price ID（mode=payment）
STRIPE_PRICE_ID_SINGLE = os.environ.get("STRIPE_PRICE_ID_SINGLE", "").strip()
# 月会员 ¥39 → Stripe Price ID（mode=subscription）
STRIPE_PRICE_ID_MONTHLY = os.environ.get("STRIPE_PRICE_ID_MONTHLY", "").strip()

STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "https://wujing.mylumee.app/?stripe=success")
STRIPE_CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "https://wujing.mylumee.app/?stripe=cancel")

# ---- 商品定义 ----
PRODUCTS = {
    "single": {
        "name": "舞镜深度分析·单次",
        "price_fen": 990,     # ¥9.9 → 分
        "currency": "cny",
        "mode": "payment",
        "days": 0,
    },
    "monthly": {
        "name": "舞镜月会员",
        "price_fen": 3900,    # ¥39 → 分
        "currency": "cny",
        "mode": "subscription",
        "days": 30,
    },
    # TODO: 机构版 - 待Karen定价后补充
}

# ---- DB：orders表初始化 ----
def init_orders_table():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              out_trade_no TEXT UNIQUE NOT NULL,
              user_id INTEGER REFERENCES users(id),
              product TEXT NOT NULL,
              amount TEXT NOT NULL DEFAULT '',
              currency TEXT DEFAULT 'cny',
              channel TEXT DEFAULT 'stripe',
              status TEXT DEFAULT 'pending',
              trade_no TEXT DEFAULT '',
              consumed_at TIMESTAMP,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              paid_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_oid ON orders(out_trade_no);
        """)

# ---- 免费额度检查 ----
def get_monthly_free_used(user_id: int) -> int:
    """本月已用免费次数"""
    now = datetime.datetime.now()
    month_start = now.strftime("%Y-%m-01")
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM orders WHERE user_id=? AND channel='free'"
            " AND created_at >= ?",
            (user_id, month_start)
        ).fetchone()
    return row["c"] if row else 0

def is_active_member(user_id: int) -> bool:
    """检查用户是否有效月会员"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT paid_at FROM orders WHERE user_id=? AND product='monthly'"
            " AND status='paid' ORDER BY paid_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    if not row or not row["paid_at"]:
        return False
    try:
        paid_at = datetime.datetime.fromisoformat(str(row["paid_at"]))
        return (datetime.datetime.now() - paid_at).days < 30
    except Exception:
        return False

def check_analysis_access(user_id: int) -> dict:
    """
    返回 {allowed, reason, type}
    免费1次/月 → 已付单次或会员 → 拦截
    """
    if is_active_member(user_id):
        return {"allowed": True, "type": "member", "reason": "月会员"}
    free_used = get_monthly_free_used(user_id)
    if free_used == 0:
        return {"allowed": True, "type": "free", "reason": "每月首次免费"}
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM orders WHERE user_id=? AND product='single'"
            " AND status='paid' AND (consumed_at IS NULL OR consumed_at='')",
            (user_id,)
        ).fetchone()
    single_avail = row["c"] if row else 0
    if single_avail > 0:
        return {"allowed": True, "type": "single", "reason": "单次分析"}
    return {
        "allowed": False,
        "type": "paywall",
        "reason": "本月免费次数已用完，请购买单次(¥9.9)或开通月会员(¥39)"
    }

# ---- Stripe HTTP辅助 ----
def _stripe_request(method: str, path: str, form: dict = None, timeout=20):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY未配置")
    url = "https://api.stripe.com" + path
    headers = {
        "Authorization": "Bearer " + STRIPE_SECRET_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def _stripe_ready(product: str = None) -> bool:
    if not STRIPE_SECRET_KEY:
        return False
    if product == "single":
        return bool(STRIPE_PRICE_ID_SINGLE)
    if product == "monthly":
        return bool(STRIPE_PRICE_ID_MONTHLY)
    return True

def _stripe_verify_webhook(sig_header: str, raw_body: bytes, tolerance=300) -> bool:
    if not (STRIPE_WEBHOOK_SECRET and sig_header and raw_body):
        return False
    parts = {}
    for part in sig_header.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k] = v
    ts = parts.get("t", "")
    v1 = parts.get("v1", "")
    if not ts or not v1:
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
    except Exception:
        return False
    signed = f"{ts}.".encode() + raw_body
    expected = _hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, v1)

# ---- 鉴权辅助 ----
def _get_user_from_token(token: str):
    if not token:
        return None
    try:
        payload = decode_token(token)
        return get_user_by_id(payload["user_id"])
    except Exception:
        return None

# ---- 路由 ----

@router.post("/api/pay/checkout")
async def pay_checkout(data: dict):
    """
    创建Stripe Checkout Session。
    body: {token: str, product: 'single'|'monthly'}
    缺key时返回503，不崩。
    """
    token = (data.get("token") or "").strip()
    product = (data.get("product") or "").strip()

    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    if product not in PRODUCTS:
        raise HTTPException(status_code=400, detail=f"不支持的商品: {product}。可选: single, monthly")

    if not _stripe_ready():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "stripe_not_configured",
                "msg": "Stripe支付暂未开通，等待配置中",
                "needs": ["STRIPE_SECRET_KEY", "STRIPE_PRICE_ID_SINGLE", "STRIPE_PRICE_ID_MONTHLY"]
            }
        )

    prod = PRODUCTS[product]
    price_id = STRIPE_PRICE_ID_SINGLE if product == "single" else STRIPE_PRICE_ID_MONTHLY
    oid = "WJ" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]
    expires_at = int(time.time()) + 1860

    form = {
        "mode": prod["mode"],
        "success_url": STRIPE_SUCCESS_URL + f"&oid={oid}&sess={{CHECKOUT_SESSION_ID}}",
        "cancel_url": STRIPE_CANCEL_URL,
        "client_reference_id": str(user["id"]),
        "expires_at": str(expires_at),
        "metadata[out_trade_no]": oid,
        "metadata[product]": product,
        "metadata[user_id]": str(user["id"]),
    }

    if price_id:
        form["line_items[0][price]"] = price_id
        form["line_items[0][quantity]"] = "1"
    else:
        form["line_items[0][price_data][currency]"] = prod["currency"]
        form["line_items[0][price_data][unit_amount]"] = str(prod["price_fen"])
        form["line_items[0][price_data][product_data][name]"] = prod["name"]
        form["line_items[0][quantity]"] = "1"

    if prod["mode"] == "subscription":
        form["subscription_data[metadata][out_trade_no]"] = oid

    try:
        code, j = _stripe_request("POST", "/v1/checkout/sessions", form)
    except RuntimeError as e:
        return JSONResponse(status_code=503, content={"ok": False, "msg": str(e)})
    except Exception as e:
        print(f"[pay/checkout] Stripe异常: {e}")
        raise HTTPException(status_code=502, detail="发起支付失败，请稍后重试")

    if code not in (200, 201) or not (j or {}).get("url"):
        print(f"[pay/checkout] 建单失败 code={code} {str(j)[:200]}")
        raise HTTPException(status_code=502, detail="发起支付失败，请稍后重试")

    now = datetime.datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO orders(out_trade_no,user_id,product,amount,currency,channel,status,trade_no,created_at)"
            " VALUES(?,?,?,?,?,  'stripe','pending',?,?)",
            (oid, user["id"], product, str(prod["price_fen"] / 100),
             prod["currency"], j.get("id", ""), now)
        )

    return {"ok": True, "out_trade_no": oid, "url": j["url"], "session_id": j.get("id", "")}


@router.post("/api/pay/webhook")
async def pay_webhook(request: Request):
    """
    Stripe webhook。
    Dashboard → Webhooks → 填: https://api-wujing.mylumee.app/api/pay/webhook
    监听: checkout.session.completed, invoice.paid
    """
    raw = await request.body()
    sig = request.headers.get("Stripe-Signature", "")

    if not _stripe_verify_webhook(sig, raw):
        print("[pay/webhook] 验签失败")
        return JSONResponse(status_code=400, content={"error": "invalid signature"})

    try:
        evt = json.loads(raw or "{}")
    except Exception:
        return JSONResponse(status_code=200, content={"ok": True})

    etype = evt.get("type", "")
    obj = ((evt.get("data") or {}).get("object")) or {}

    try:
        if etype == "checkout.session.completed":
            if (obj.get("payment_status") or "") == "paid":
                oid = (obj.get("metadata") or {}).get("out_trade_no") or ""
                if oid:
                    _stripe_settle(oid, obj.get("subscription") or "",
                                   obj.get("amount_total"), obj.get("currency", "cny"))
        elif etype == "invoice.paid":
            if (obj.get("billing_reason") or "") == "subscription_cycle":
                _stripe_apply_renewal(
                    obj.get("subscription") or "",
                    obj.get("id") or "",
                    obj.get("amount_paid"),
                    obj.get("currency", "cny")
                )
    except Exception as e:
        print(f"[pay/webhook] 处理 {etype} 异常: {e}")

    return JSONResponse(status_code=200, content={"ok": True})


@router.get("/api/pay/status")
async def pay_status(out_trade_no: str = "", token: str = ""):
    """前端轮询订单状态 + Stripe主动查兜底"""
    if not out_trade_no:
        raise HTTPException(status_code=400, detail="缺少out_trade_no")
    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")

    with get_db() as conn:
        row = conn.execute(
            "SELECT status,product,trade_no FROM orders WHERE out_trade_no=? AND user_id=?",
            (out_trade_no, user["id"])
        ).fetchone()

    if not row:
        return {"status": "unknown"}

    status, product, sess = row["status"], row["product"], row["trade_no"]
    if status == "paid":
        return {"status": "paid", "product": product, "msg": "支付成功 🎉"}

    if STRIPE_SECRET_KEY and sess and str(sess).startswith("cs_"):
        try:
            code, j = _stripe_request("GET", "/v1/checkout/sessions/" + str(sess))
            if code in (200, 201) and (j.get("payment_status") or "") == "paid":
                _stripe_settle(out_trade_no, j.get("subscription") or "",
                               j.get("amount_total"), j.get("currency", "cny"))
                return {"status": "paid", "product": product, "msg": "支付成功 🎉"}
        except Exception as e:
            print(f"[pay/status] 查询异常: {e}")

    return {"status": "pending"}


@router.get("/api/pay/access")
async def pay_access(token: str = ""):
    """
    查当前用户分析权限。前端据此决定是否显示付费墙。
    返回: {allowed, type, reason, is_member, free_used_this_month}
    """
    user = _get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    access = check_analysis_access(user["id"])
    return {
        **access,
        "is_member": is_active_member(user["id"]),
        "free_used_this_month": get_monthly_free_used(user["id"]),
    }


# ---- 内部结算 ----

def _stripe_settle(oid: str, sub_id: str, amount_minor, currency: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id,product,status FROM orders WHERE out_trade_no=?", (oid,)
        ).fetchone()
        if not row or row["status"] == "paid":
            return False
        try:
            amt = f"{(float(amount_minor) or 0) / 100:.2f}"
        except Exception:
            amt = ""
        now = datetime.datetime.now().isoformat()
        conn.execute(
            "UPDATE orders SET status='paid', trade_no=?, amount=?, currency=?, paid_at=?"
            " WHERE out_trade_no=?",
            (sub_id or "", amt, (currency or "cny").upper(), now, oid)
        )
    print(f"[pay/settle] PAID {oid} sub={sub_id} amt={amt}")
    return True


def _stripe_apply_renewal(sub_id: str, invoice_id: str, amount_minor, currency: str):
    if not sub_id:
        return
    with get_db() as conn:
        if invoice_id and conn.execute(
            "SELECT 1 FROM orders WHERE trade_no=? LIMIT 1", (invoice_id,)
        ).fetchone():
            return
        row = conn.execute(
            "SELECT user_id,product FROM orders WHERE trade_no=? AND channel='stripe'"
            " AND status='paid' ORDER BY created_at DESC LIMIT 1", (sub_id,)
        ).fetchone()
        if not row:
            print(f"[pay/renewal] 未知订阅 {sub_id}")
            return
        oid = "WJR" + datetime.datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]
        now = datetime.datetime.now().isoformat()
        try:
            amt = f"{(float(amount_minor) or 0) / 100:.2f}"
        except Exception:
            amt = ""
        conn.execute(
            "INSERT INTO orders(out_trade_no,user_id,product,amount,currency,channel,status,trade_no,created_at,paid_at)"
            " VALUES(?,?,?,?,?,  'stripe','paid',?,?,?)",
            (oid, row["user_id"], row["product"], amt,
             (currency or "cny").upper(), invoice_id, now, now)
        )
    print(f"[pay/renewal] RENEWAL {sub_id} inv={invoice_id}")


# ---- 微信支付（TODO，需商户号）----
# TODO: 接微信支付需要:
#   - 微信商户号 MCH_ID + APIv3密钥
#   - 商户证书 cert.pem / key.pem
#   - JSAPI需公众号APPID + 用户openid
# 预留路由占位，Karen提供商户信息后实现

@router.post("/api/pay/wechat/create")
async def wechat_create(data: dict):
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "wechat_not_configured",
                 "msg": "微信支付暂未开通，需商户号和API密钥"}
    )

@router.get("/api/pay/wechat/query")
async def wechat_query(out_trade_no: str = ""):
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "wechat_not_configured", "msg": "微信支付暂未开通"}
    )


# ---- 支付宝（TODO，需商户号）----
# TODO: 接支付宝需要:
#   - 支付宝APPID + 商户RSA私钥 + 支付宝公钥
#   - 大陆主体备案 + 营业执照
# 预留路由占位，Karen提供商户信息后实现

@router.post("/api/pay/alipay/create")
async def alipay_create(data: dict):
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "alipay_not_configured",
                 "msg": "支付宝暂未开通，需商户APPID和密钥"}
    )

@router.get("/api/pay/alipay/query")
async def alipay_query(out_trade_no: str = ""):
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "alipay_not_configured", "msg": "支付宝暂未开通"}
    )
