#!/bin/bash
# 舞镜 部署脚本 (v2.0 · 0811重写·修正错误架构)
#
# ⚠️ 真架构（旧脚本全写错了）：
#   - 服务器【非git】·不能 git pull·改动直接 scp
#   - 后端 systemd 托管（wujing-api.service）·【非pm2】
#   - 前端 HTML → /www/wujing-api/static/
#   - 后端 .py  → /www/wujing-api/  然后 systemctl restart wujing-api
#   - 本地真源 = ~/projects/舞镜/_live/ 顶层（非 _live/static/ 子目录·那是旧残留）
#
# 用法：
#   bash 部署脚本-一键上线-20260810.sh                # 部署默认前端集
#   bash 部署脚本-一键上线-20260810.sh design-upgrade.html home-v2.html   # 只部署指定文件
#   bash 部署脚本-一键上线-20260810.sh server.py       # 部署后端(自动重启systemd)
#
# 🚫 pay.py 碰钱：不走本脚本·必须 staging 测通+微信0.01真扫+Karen同意才单独部署

set -e

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

SRV="root@47.242.80.65"
REMOTE_STATIC="/www/wujing-api/static"
REMOTE_ROOT="/www/wujing-api"
LOCAL="$HOME/projects/舞镜/_live"
STAMP=$(date '+%Y%m%d-%H%M')

# 默认部署的前端文件集（不含 pay.py）
DEFAULT_FILES="design-upgrade.html home-v2.html class_teacher.html class_join.html auth-pay.html privacy.html terms.html"

FILES="${@:-$DEFAULT_FILES}"

echo -e "${YELLOW}🚀 舞镜部署 · $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo "   文件: $FILES"
echo ""

# 拦截 pay.py（碰钱不走本脚本）
for f in $FILES; do
  if [ "$f" = "pay.py" ]; then
    echo -e "${RED}✗ pay.py 碰钱·禁止用本脚本部署（需staging+真扫复测+同意）${NC}"; exit 1
  fi
done

NEED_RESTART=0

for f in $FILES; do
  LOCAL_FILE="$LOCAL/$f"
  if [ ! -f "$LOCAL_FILE" ]; then
    echo -e "${RED}✗ 本地没有 $f · 跳过${NC}"; continue
  fi

  # .py → 根目录+需重启；其余 → static/
  case "$f" in
    *.py) REMOTE_DIR="$REMOTE_ROOT"; NEED_RESTART=1 ;;
    *)    REMOTE_DIR="$REMOTE_STATIC" ;;
  esac

  echo -e "${YELLOW}[$f]${NC}"
  # 1. 服务器备份现版
  ssh "$SRV" "[ -f $REMOTE_DIR/$f ] && cp $REMOTE_DIR/$f $REMOTE_DIR/$f.bak-$STAMP || true"
  # 2. scp 上传
  scp "$LOCAL_FILE" "$SRV:$REMOTE_DIR/$f" >/dev/null
  # 3. md5 校验
  L_MD5=$(md5 -q "$LOCAL_FILE")
  R_MD5=$(ssh "$SRV" "md5sum $REMOTE_DIR/$f | cut -d' ' -f1")
  if [ "$L_MD5" = "$R_MD5" ]; then
    echo -e "  ${GREEN}✓ 上传+校验一致${NC} ($L_MD5)"
  else
    echo -e "  ${RED}✗ md5不一致! 本地=$L_MD5 服务器=$R_MD5${NC}"; exit 1
  fi
done

# 后端改动 → 重启 systemd
if [ "$NEED_RESTART" = "1" ]; then
  echo ""
  echo -e "${YELLOW}后端改动 · 重启 wujing-api.service...${NC}"
  ssh "$SRV" "systemctl restart wujing-api && sleep 2 && systemctl is-active wujing-api"
  echo -e "${GREEN}✓ 已重启${NC}"
fi

# 验证线上
echo ""
echo -e "${YELLOW}验证线上...${NC}"
for url in "/" "/app"; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://wujing.mylumee.app$url")
  [ "$CODE" = "200" ] && echo -e "  ${GREEN}✓ $url = $CODE${NC}" || echo -e "  ${RED}✗ $url = $CODE${NC}"
done

echo ""
echo -e "${GREEN}════════════════════════════════${NC}"
echo -e "${GREEN}✅ 部署完成${NC}"
echo -e "${GREEN}════════════════════════════════${NC}"
echo "   服务器备份: *.bak-$STAMP"
echo "   回滚: ssh $SRV \"cp \$REMOTE_DIR/文件.bak-$STAMP \$REMOTE_DIR/文件\""
echo ""
echo "⏰ $(date '+%Y-%m-%d %H:%M:%S')"
