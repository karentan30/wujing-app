# 舞镜 · 待放 Agent 队列（0729）

> 当前跑着：Agent1(前端卡片, 改 design-upgrade.html) + Agent2(舞库入库, 改 analyze.py/server.py)。
> **规则**：改同一文件的 agent 不并行。落地一个再放下一个。全用 sonnet（省token）。付费操作先给 Karen 预算。

## 冲突分类
- **A 类**（改 `server.py`/`analyze.py`，要重启）：支付、群舞、健身 → 串行，且要等 Agent2 完
- **B 类**（改 `design-upgrade.html` 静态）：登录UI、作品广场前端 → 串行，且要等 Agent1 完
- **C 类**（独立目录 `~/projects/affiliate`，不碰 wujing）：分成后台 → 可随时并行

## 放行顺序（按变现）
1. 分成后台(C, 可现在) → 2. 支付(A) → 3. 达人分销接入(B/config) → 4. 作品广场+打赏(A+B) → 5. 群舞逐人(A) → 6. 健身版(A)

---

## ① 分成后台（C 类·可先放）| sonnet
```
任务：把 `~/projects/affiliate`（现成分成后台：backend+dashboard+lib）接入舞镜，做达人分销归因。
- 读 ~/projects/affiliate 的 backend/lib，搞清它怎么记录 referrer(xs_ref)、怎么算分成、dashboard 怎么看。
- 设计：达人拿一个带 ?xs_ref=达人ID 的舞镜链接 → 用户点进来注册/付费 → affiliate 后台记一笔归因 → 按比例算达人分成。
- 参考 Lumee 的做法（memory: affiliate 用 helper+xs_ref 兼容）。
- 产出：①舞镜前端如何带上并存储 xs_ref（落 localStorage + 注册时回传后端）②后端 register 时记录 referrer ③affiliate 后台如何对账。
- 先出接入方案文档 + 改动清单，不直接改 wujing 生产（涉及 server.py 的改动列出来给主线串行执行）。
汇报：affiliate 现状、接入方案、需要在 wujing 改哪些（供排队）。别贴大段代码。
```

## ② 支付 Stripe+微信+支付宝（A 类·等 Agent2 完）| sonnet
```
任务：给舞镜后端 /www/wujing-api 加支付，抄 Lumee 现成 Stripe。
- 抄源：~/projects/lumee/server.py 里 Stripe/paywall 逻辑 + ~/projects/lumee/docs/us-launch/payment-changes.md（美国个人号已跑通，YiYi 复用过同一号）。
- 定价（已定稿）：免费体验 + ¥9.9/次深度分析 + ¥39/月会员 + 机构版。
- 实现：新建 payment.py 模块（别把 server.py 写爆），在 server.py 注册路由（最小改动）；Stripe 先接（海外），微信/支付宝留接口+TODO（需商户号，标注等 Karen）。
- ⚠️ 改 server.py 要 systemctl restart，改前备份，语法检查，重启后 curl health。⚠️ 别在代码里硬编码任何 key（走 start.sh 环境变量，参考 ARK_API_KEY 写法）。
- 付费真调用/建 Stripe 产品前先把预算和所需 key 清单给主线，别擅自产生费用。
汇报：接了哪些、需要 Karen 提供哪些 key、微信/支付宝卡点。
```

## ③ 登录/注册 UI 完善（B 类·等 Agent1 完）| sonnet
```
任务：完善舞镜 H5 登录/注册界面，抄 Lumee。
- 抄源：~/projects/lumee/index.html 的登录/注册流 + oauth_server.py（Google 登录，可选）。
- 现状：/www/wujing-api/static/design-upgrade.html 已有 showAuth()/AUTH_TOKEN/login 接口，后端 /api/login /api/register 已能用。主要是 UI 打磨（清晰、精致银色风、移动端友好、加载态转圈、错误提示友好）。
- ⚠️ 静态文件直接改，别重启；改前备份；改后 curl 首页确认没破。
汇报：改了哪些、备份路径、验证结果。
```

## ④ 作品广场 + 打赏（A+B·靠后）| sonnet
```
任务：学员发布跳得好的作品 → 作品广场大家看 → 可打赏。
- 后端：新建 community 表(作品:review_id/user/视频/点赞/是否公开) + feed 接口 + 点赞；打赏复用支付(②做完后)。
- 前端：作品广场页(feed 卡片流) + 发布按钮 + 打赏按钮。参考 lumee/_live_pull/build_square.py 的 square 思路。
- 分两步：先只读 feed + 发布 + 点赞（不含打赏），打赏等支付好。
- ⚠️ A类改server.py要排队重启；B类改html静态。
汇报：表结构、接口、前端页、验证。
```

## ⑤ 群舞逐人评分（A·靠后）| sonnet
```
任务：一段群舞/多人同框视频，识别每个人并各自打分。
- 方案：抽关键帧 → 豆包vision先问"画面里几个人、各自大致位置(左/中/右/bbox)" → 按人裁切 → 每人 vs 老师对应位置打分 → 输出每人一份评分+点评。
- 复用 vision_score.py（关思考+压图）。注意成本：多人=多次调用，控制帧数，先给Karen预算。
- 先做2-3人 demo 跑通，别一上来支持任意人数。
汇报：多人检测效果、每人评分demo、成本/帧。
```

## ⑥ 健身版（A·最后）| sonnet
```
任务：clone 舞镜管线做健身动作标准检测（AnyMotion版）。
- 抄舞镜自己：同一套 upload→vision对比→评分+指导 管线，换标准动作参考库(深蹲/硬拉/瑜伽/平板) + 健身话术prompt(关节角度/发力/代偿/受伤风险)。
- 可独立部署或加 mode 开关。参考 docs/PRD-AI健身教练.md。
汇报：复用了哪些、健身话术效果、部署方式。
```

---
**主线（我 Opus）负责**：验收每个 agent、串行调度 A/B 类、处理合规红线与付费预算、最终 QA。
