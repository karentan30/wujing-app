#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# 舞镜 · 优化 Loop Harness
# 每次改动后跑一遍，把「回归 + 静态审计 + 上线门」固化成循环：
#   L1 语法门 → L2 功能回归 → L3 静态审计（P0红线） → L4 上报
# 全绿 = 可继续；任何红 = 停下修，别带着红往下走。
# 用法：
#   ./scripts/optimize_loop.sh            # 完整跑一遍
#   ./scripts/optimize_loop.sh --check    # 只跑静态检查(快)
# ═══════════════════════════════════════════════════════════════════
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$ROOT/_live"
SERVER="root@47.242.80.65"
PASS=0; FAIL=0
ok(){ echo "  ✓ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $1"; FAIL=$((FAIL+1)); }

echo "══════════ 舞镜 优化Loop ══════════"

# ── L1 语法门 ──
echo "── L1 语法门 ──"
JS_OK=1
python3 - "$LIVE" <<'PYEOF' || JS_OK=0
import re, sys, subprocess, tempfile, os
html = open(sys.argv[1]+'/design-upgrade.html', encoding='utf-8').read()
scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
for i, s in enumerate(scripts):
    f = tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w', encoding='utf-8')
    f.write(s); f.close()
    r = subprocess.run(['node','--check',f.name], capture_output=True, text=True)
    os.unlink(f.name)
    if r.returncode != 0:
        print(f"JS block {i}: {r.stderr[:200]}"); sys.exit(1)
print(f"  {len(scripts)} JS blocks OK")
PYEOF
[ $JS_OK -eq 1 ] && ok "design-upgrade.html JS 语法" || bad "JS 语法错误"

PY_OK=1
for f in server.py pay.py my_works.py group_review.py review_compare.py auto_decompose.py; do
  python3 -c "import ast; ast.parse(open('$LIVE/$f',encoding='utf-8').read())" 2>/dev/null || { bad "$f 语法错误"; PY_OK=0; }
done
[ $PY_OK -eq 1 ] && ok "全部 py 语法"

# ── L2 功能回归（线上冒烟）──
echo "── L2 功能回归 ──"
health=$(curl -s -m 8 https://wujing.mylumee.app/api/health 2>/dev/null)
echo "$health" | grep -q '"status":"ok"' && ok "健康检查" || bad "服务不健康: $health"

page=$(curl -s -m 8 https://wujing.mylumee.app/ 2>/dev/null)
if [ -n "$page" ] && printf '%s' "$page" | grep -F 'id="tabbar"' >/dev/null 2>&1; then
  ok "首页渲染"
else
  bad "首页缺tabbar"
fi

# ── L3 静态审计（P0红线，防回归）──
echo "── L3 P0红线 ──"
# 1) 密钥不入 git
if git -C "$ROOT" grep -qE "sk_live_[A-Za-z0-9]|sk_test_[A-Za-z0-9]{10}|whsec_[A-Za-z0-9]{10}|WECHAT_API_KEY='[^']{10}" -- '_live/' 2>/dev/null; then
  bad "git 含真实密钥!"
else
  ok "git 无真实密钥"
fi
# 2) 前端无 href="#" 死链
dead=$(grep -Fc 'href="#"' "$LIVE/design-upgrade.html")
[ "$dead" -eq 0 ] && ok "无死链 href=#" || bad "发现 $dead 处 href=#"
# 3) 无"抄自Lumee"内参
leak=$(grep -c '抄自\|TODO.*Lumee' "$LIVE/design-upgrade.html" 2>/dev/null)
[ "$leak" -eq 0 ] && ok "无内参泄漏" || bad "发现 $leak 处内参"
# 4) 设备级付费解锁（防回退到全局白嫖）
if grep -q 'guest:' "$LIVE/pay.py"; then
  ok "游客设备身份"
else
  bad "pay.py 缺设备身份! 付费会全局白嫖"
fi
# 5) 免费配额门（防无上限烧钱）
if grep -q '_free_quota_ok' "$LIVE/server.py"; then
  ok "免费配额门"
else
  bad "免费配额门缺失!"
fi
# 6) 班级老师鉴权
if grep -q '_require_teacher' "$LIVE/group_review.py"; then
  ok "班级老师鉴权"
else
  bad "班级老师鉴权缺失!"
fi
# 7) 合规: 未成年声明 + AI标识
if grep -q '18' "$LIVE/design-upgrade.html" && grep -q 'AI 生成' "$LIVE/design-upgrade.html"; then
  ok "合规声明在"
else
  bad "合规声明缺失"
fi

# ── L4 上报 ──
echo ""
echo "══════════ 结果: $PASS 通过 / $FAIL 失败 ══════════"
if [ "$FAIL" -eq 0 ]; then
  echo "✅ 全绿 — 可以继续上线/迭代"
  exit 0
else
  echo "❌ 有 $FAIL 项红灯 — 停下修复再继续，别带着红往下走"
  exit 1
fi
