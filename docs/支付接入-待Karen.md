# 舞镜支付接入 — 待 Karen 提供（Stripe 骨架已上线）

状态：**代码骨架已部署到生产后端并验证通过（health ok），但未建任何真 Stripe 产品、未产生任何费用。** 缺 key 时所有支付接口返回明确 503/401，不崩。

## 一、定价（已定稿）
- 免费体验：每用户每月 **1 次**免费深度分析
- 单次深度分析：**¥9.9**（Stripe mode=payment）
- 月会员：**¥39/月**（Stripe mode=subscription）
- 机构版：TODO（代码里留了占位，等定价）

## 二、需要 Karen 提供的 Stripe Key（写进 `/www/wujing-api/start.sh`）

后端已在 `start.sh` 里预置了注释行，Karen 拿到 key 后**取消注释并填值**，然后 `systemctl restart wujing-api` 即生效（env_loader.py 会自动从 start.sh 读取 export 行）。

| 变量名 | 说明 | 去哪拿 |
|---|---|---|
| `STRIPE_SECRET_KEY` | 密钥 `sk_live_...`（先跑 test 用 `sk_test_...`） | Dashboard → Developers → API keys |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Dashboard → Webhooks → 建 endpoint 后显示 |
| `STRIPE_PRICE_ID_SINGLE` | `price_...` | Dashboard → Products 建「单次深度分析 ¥9.9」后拿 Price ID |
| `STRIPE_PRICE_ID_MONTHLY` | `price_...` | Dashboard → Products 建「月会员 ¥39/月」后拿 Price ID |
| `STRIPE_SUCCESS_URL` | 成功跳转（已给默认值 wujing.mylumee.app，可不填） | — |
| `STRIPE_CANCEL_URL` | 取消跳转（已给默认值，可不填） | — |

复用说明：Lumee/YiYi 用的**美国个人 Stripe 号**可直接复用（同号已跑通）。若沿用该号，只需在其 Dashboard 里新建上面两个 Product 拿 Price ID 即可。

## 三、Stripe Dashboard 需手动做的两件事（建产品才产生"配置"，非费用）
1. **建 2 个 Product**（单次 ¥9.9 / 月会员 ¥39），各拿一个 Price ID。
   - 注意：Stripe 结算币种。¥（CNY）Stripe 支持作为 presentment 货币，但**收款结算币种取决于账户**。美国个人号通常结算 USD，建议确认是否要按 USD 计价（如 $1.4 / $5.5）或坚持 CNY 展示。这一步 Karen 拍板。
2. **建 1 个 Webhook endpoint**：
   - URL：`https://api-wujing.mylumee.app/api/pay/webhook`
   - 监听事件：`checkout.session.completed` + `invoice.paid`
   - 建完拿到 `whsec_...` 填进 start.sh

> 备用：即使不建 Price（不填 PRICE_ID），代码也能用 `price_data` 动态传金额兜底建单，但**推荐用 Price ID**（订阅必须用 Price）。

## 四、预算/成本
- 建产品、建 webhook：**￥0**，不产生费用。
- 真实交易费：Stripe 抽成约 **2.9% + $0.30/笔**（跨境/货币转换另加约 1-2%）。
- 本轮完全没发起任何计费请求。

## 五、微信支付 / 支付宝 — 卡点（代码只留了 503 桩 + TODO）
| 渠道 | 卡点 | 结论 |
|---|---|---|
| 微信支付 | 需**企业**商户号 MCH_ID + APIv3 密钥 + 商户证书（cert/key.pem）；JSAPI 还需公众号 APPID + 用户 openid。个人号不可用。 | 等 Karen 提供公司主体商户信息 |
| 支付宝 | 需企业营业执照 + APPID + 商户 RSA 私钥/支付宝公钥；大陆主体。 | 同上 |

短期建议：**先只跑 Stripe 信用卡**（海外用户够用）。国内用户等公司主体拿到微信/支付宝商户号再接，接口位已留好。

## 六、拿到 key 后如何测（给 Karen 或下一个 agent）
1. test 模式先跑：start.sh 填 `sk_test_...` + test 的 price/whsec，restart。
2. 登录拿 token → `POST /api/pay/checkout` body `{"token":"...","product":"single"}` → 返回 Stripe `url`，浏览器打开用 Stripe 测试卡 `4242 4242 4242 4242` 付款。
3. webhook 回来后 `GET /api/pay/status?out_trade_no=...&token=...` 应返回 `paid`。
4. `GET /api/pay/access?token=...` 看免费/付费/会员判定。
5. 全绿再换 `sk_live_...` 上真号。

## 七、已上线的接口 & 数据
路由（8 个，已在生产 openapi 可见）：
- `POST /api/pay/checkout` — 建 Checkout Session（single/monthly）
- `POST /api/pay/webhook` — Stripe 验签 + 落库
- `GET /api/pay/status` — 轮询订单（含 Stripe 主动查兜底）
- `GET /api/pay/access` — 查用户分析权限（免费/单次/会员/付费墙）
- `POST/GET /api/pay/wechat/create|query` — 微信桩（503）
- `POST/GET /api/pay/alipay/create|query` — 支付宝桩（503）

免费门已接进 `/api/upload`：每用户每月 1 次免费，超出 `check_analysis_access` 返回不允许 → upload 返回 **402** 要求付费（付费成功后放行）。

orders 表（同 wujing.db，已建）：
`id, out_trade_no, user_id, product, amount, currency, channel, status, trade_no, consumed_at, created_at, paid_at`
- channel: `stripe` / `free` / (后续 wechat/alipay)
- product: `single` / `monthly` / `free`
- status: `pending` / `paid`
