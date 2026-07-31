# ════════════════════════════════════════════════════════════════════
# Payment Hub 路由 —— Wujing 通过 Lumee 收款中台下单
# 用法：app.include_router(hub_router)
# ════════════════════════════════════════════════════════════════════
import os, json, hmac, hashlib, uuid
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from hub_pay import HubPay

router = APIRouter(prefix="/api/pay/hub", tags=["hub-pay"])

PROJECT_ID = os.environ.get("HUB_PROJECT_ID", "wujing")
HUB_BASE = os.environ.get("HUB_BASE_URL", "https://www.mylumee.app")
hp = HubPay(PROJECT_ID, HUB_BASE)


@router.post("/create")
async def hub_create(payload: dict):
    """下单。body: {method, product, amount, out_ref}
    返回 {ok, order_no, code_url|qr_code, amount, method}"""
    method = (payload.get("method") or "").strip().lower()
    product = (payload.get("product") or "").strip()
    amount = payload.get("amount")
    out_ref = (payload.get("out_ref") or "").strip()

    if method not in ("wechat", "alipay", "stripe"):
        return JSONResponse({"error": "method 仅支持 wechat / alipay / stripe"}, 400)
    if not product:
        return JSONResponse({"error": "缺少 product"}, 400)
    try:
        amount = round(float(amount), 2)
        if amount <= 0 or amount > 100000:
            raise ValueError
    except (TypeError, ValueError):
        return JSONResponse({"error": "amount 必须在 0–100000 元之间"}, 400)

    try:
        order = hp.create(method, product, amount, out_ref)
        order["out_ref"] = out_ref
        return JSONResponse(order)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, 502)


@router.get("/status")
async def hub_status(order_no: str):
    """查单。?order_no=xxx  → {ok, order_no, status: paid|pending|failed}"""
    if not order_no:
        return JSONResponse({"error": "缺少 order_no"}, 400)
    try:
        return JSONResponse(hp.status(order_no))
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, 502)
