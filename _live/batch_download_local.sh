#!/bin/bash
# 在 Karen 的 Mac 上运行 - 下载视频并上传到服务器触发拆解
# 用法: bash batch_download_local.sh

SERVER="root@47.242.80.65"
API="https://wujing.mylumee.app"
TMP="/tmp/wujing_batch"
mkdir -p "$TMP"

# 颜色
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; NC='\033[0m'

log() { echo -e "${Y}[$(date +%H:%M:%S)]${NC} $1"; }
ok()  { echo -e "${G}✅ $1${NC}"; }
err() { echo -e "${R}❌ $1${NC}"; }

# 检查 yt-dlp
if ! command -v yt-dlp &>/dev/null; then
    log "安装 yt-dlp..."
    pip3 install yt-dlp -q
fi

# 舞蹈队列: "id|搜索词|标题|艺人|舞种"
DANCES=(
    # ── 古风 ──
    "vid_guofeng_zhiqi|执笔 古风舞蹈 完整版 教学|执笔|汉服古风|guofeng"
    "vid_guofeng_chiling|赤伶 古风舞蹈 完整版|赤伶|古风|guofeng"
    "vid_guofeng_bencaogangmu|本草纲目 刘畊宏 完整版 跟练|本草纲目|刘畊宏|guofeng"
    "vid_guofeng_tanchuang|探窗 古风舞蹈 完整版|探窗|古风|guofeng"
    "vid_guofeng_liangliang|凉凉 古风舞蹈 完整版|凉凉|张碧晨|guofeng"
    "vid_guofeng_wuji|无羁 陈情令 古风舞蹈 完整版|无羁|古风|guofeng"
    # ── K-pop ──
    "vid_kpop_supernova|aespa Supernova dance cover|Supernova|aespa|kpop"
    "vid_kpop_magnetic|ILLIT Magnetic dance cover|Magnetic|ILLIT|kpop"
    "vid_kpop_eta|NewJeans ETA dance cover|ETA|NewJeans|kpop"
    "vid_kpop_zoom|Jessi ZOOM dance cover|ZOOM|Jessi|kpop"
    # ── 流行 ──
    "vid_sabrina_espresso|Sabrina Carpenter Espresso Official Music Video|Espresso|Sabrina Carpenter|pop"
    "vid_pop_ketaisan|科目三 原版 抖音 舞蹈 完整|科目三|抖音热舞|pop"
    "vid_pop_wildisco|野狼disco 宝石gem 完整版|野狼disco|宝石Gem|pop"
    "vid_pop_aini|爱你 王心凌 完整版 舞蹈|爱你|王心凌|pop"
    # ── 拉丁 ──
    "vid_shakira_hips|Shakira Hips Don't Lie Official Video|Hips Don't Lie|Shakira|latin"
    "vid_latin_despacito|Despacito Luis Fonsi dance cover|Despacito|Luis Fonsi|latin"
    # ── 广场舞 ──
    "vid_guangchang_xiaopingguo|小苹果 筷子兄弟 广场舞 完整版|小苹果|筷子兄弟|guangchang"
    "vid_guangchang_zuixuan|最炫民族风 凤凰传奇 广场舞|最炫民族风|凤凰传奇|guangchang"
)

SUCCESS=0
FAIL=0

for entry in "${DANCES[@]}"; do
    IFS='|' read -r DID SEARCH TITLE ARTIST GENRE <<< "$entry"

    log "处理: $TITLE ($ARTIST)"

    OUT="$TMP/${DID}.mp4"

    # 先检查服务器上是否已拆解
    STATUS=$(curl -s "$API/api/decompose/$DID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)
    if [ "$STATUS" = "completed" ]; then
        ok "$TITLE 已拆解，跳过"
        SUCCESS=$((SUCCESS+1))
        continue
    fi

    # 下载
    if [ ! -f "$OUT" ] || [ $(stat -f%z "$OUT" 2>/dev/null || echo 0) -lt 1000000 ]; then
        log "  下载: $SEARCH"
        yt-dlp "ytsearch1:$SEARCH" \
            -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]" \
            --merge-output-format mp4 \
            -o "$OUT" \
            --no-playlist \
            --quiet \
            --progress

        if [ ! -f "$OUT" ] || [ $(stat -f%z "$OUT" 2>/dev/null || echo 0) -lt 1000000 ]; then
            err "下载失败: $TITLE"
            FAIL=$((FAIL+1))
            continue
        fi
        SIZE=$(du -sh "$OUT" | cut -f1)
        ok "下载完成 $SIZE"
    else
        ok "已有缓存: $OUT"
    fi

    # 上传到服务器 → 触发拆解
    log "  上传到服务器..."
    scp "$OUT" "$SERVER:/www/wujing-api/tmp_download/${DID}.mp4"

    # 触发拆解 (通过 Python 直接调用，因为 API 需要付款)
    ssh "$SERVER" "cd /www/wujing-api && python3 -c \"
import os, sys
sys.path.insert(0, '.')
# 加载 API keys
with open('start.sh') as f:
    for line in f:
        if line.strip().startswith('export '):
            k,v = line.strip()[7:].split('=',1)
            os.environ.setdefault(k.strip(), v.strip().strip(\\\"'\\\"))

from auto_decompose import run_decompose
import shutil, json

did = '$DID'
video_path = '/www/wujing-api/tmp_download/${DID}.mp4'
run_decompose(did=did, video_path=video_path, user_id=None,
              title='$TITLE', genre='$GENRE', song='$TITLE')

# 复制 decompose.json → breakdown.json (gen_cards 需要)
ddir = f'/www/wujing-api/data/{did}'
shutil.copy2(f'{ddir}/decompose.json', f'{ddir}/breakdown.json')

# 生成卡片
import subprocess
r = subprocess.run(['python3', '/www/wujing-api/cards/gen_cards.py', did, video_path, ddir],
                   capture_output=True, text=True, timeout=300)
print(r.stdout[-300:])
if r.returncode != 0: print('WARN:', r.stderr[-200:])

# 删除原视频
os.remove(video_path)
d = json.load(open(f'{ddir}/decompose.json'))
print(f'DONE: {d.get(\"status\")} {len(d.get(\"phrases\",[]))} phrases')
\" 2>&1 | grep -v RequestsDependency | grep -v Deprecated"

    if [ $? -eq 0 ]; then
        ok "$TITLE 完成！"
        SUCCESS=$((SUCCESS+1))
    else
        err "$TITLE 拆解失败"
        FAIL=$((FAIL+1))
    fi

    echo ""
done

echo ""
echo "================================"
echo "完成: $SUCCESS 首 | 失败: $FAIL 首"
echo ""
if [ $SUCCESS -gt 0 ]; then
    echo "去看看效果: https://wujing.mylumee.app/design-upgrade.html"
fi
