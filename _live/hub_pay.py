# ════════════════════════════════════════════════════════════════════
# Payment Hub 瘦客户端（Python 版） —— 子项目通过 Lumee 收款中台下单
# 用法：
#   from hub_pay import HubPay
#   hp = HubPay('wujing', 'https://www.mylumee.app')
#   order = hp.create('wechat', '舞蹈拆解', 9.9, 'WJ-REF-001')
#   status = hp.status(order['order_no'])
# ════════════════════════════════════════════════════════════════════
import os, json, hmac, hashlib, urllib.request, urllib.parse

class HubPay:
    def __init__(self, project_id, hub_base=None):
        self.project_id = project_id
        self.hub_base = (hub_base or os.environ.get("HUB_BASE_URL", "https://www.mylumee.app")).rstrip("/")
        secret_env = "HUB_SECRET_" + project_id.upper()
        self.api_secret = os.environ.get(secret_env, "").strip()
        if not self.api_secret:
            print(f"[hub_pay] WARN: {secret_env} not set — hub payments disabled")

    def ready(self):
        return bool(self.api_secret)

    def _sign(self, payload):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return hmac.new(self.api_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def create(self, method, product, amount, out_ref=None):
        """下单。method=wechat|alipay, amount=元(float), out_ref=项目方业务单号"""
        if not self.ready():
            raise RuntimeError("Hub payment not configured (missing HUB_SECRET)")
        body = json.dumps({"method": method, "product": product, "amount": float(amount), "out_ref": out_ref or ""}).encode("utf-8")
        req = urllib.request.Request(
            self.hub_base + "/hub/pay/create",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Project-Id": self.project_id,
                "X-Sign": self._sign(body),
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "hub pay create failed"))
        return resp

    def status(self, order_no):
        """查单。返回 {ok, order_no, status: paid|pending|failed}"""
        if not self.ready():
            raise RuntimeError("Hub payment not configured")
        canonical = f"project_id={urllib.parse.quote(self.project_id)}&order_no={urllib.parse.quote(order_no)}"
        qs = f"project_id={urllib.parse.quote(self.project_id)}&order_no={urllib.parse.quote(order_no)}"
        req = urllib.request.Request(
            self.hub_base + "/hub/pay/status?" + qs,
            headers={
                "X-Project-Id": self.project_id,
                "X-Sign": self._sign(canonical),
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "hub pay status failed"))
        return resp
