#!/usr/bin/env python3
"""
舞镜AI对比视频 v5 — 10分版
布局：1080x1920
  上半(960px)：左=博主 右=学员（自动增亮）
  下半(960px)：AI鼓励点评面板（全满）
新增：首帧钩子、动态评分动画、增亮学员、丰满结尾
"""
import subprocess, os, shutil
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

BLOGGER = "/Users/karen/Documents/338691435.mp4"
LEARNER = "/Users/karen/Documents/1144995230.mp4"
OUT_DIR = os.path.expanduser("~/Downloads/舞镜推广视频")
TMP = "/tmp/wjv4"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TMP, exist_ok=True)

W, H = 1080, 1920
VIDEO_H = 960
PANEL_H = 960
VIDEO_W = 540
FPS = 15
DUR = 20

GOLD  = (181, 146, 42)
GOLD2 = (220, 185, 80)     # 亮金
RED   = (220, 60, 60)
YEL   = (240, 170, 50)
GRN   = (70, 200, 110)
WHITE = (255, 255, 255)
GRAY  = (160, 155, 145)
BG_PANEL = (18, 14, 9)
BG_VIDEO = (8, 6, 4)

# 钩子显示帧数（0~1.5s = 0~22帧）
HOOK_END_FRAME = int(FPS * 1.5)
# 结尾帧数（最后2s）
OUTRO_START_FRAME = int((DUR - 2) * FPS)

# (开始s, 结束s, 动作名, 具体夸赞, 进阶建议, 鼓励收尾, 五维分数tuple)
CORRECTIONS = [
    (0,  4,  "起势·沉肩",
     "你的节奏感超过 85% 的自学者！第一拍落点精准，完全踩在音乐心跳上",
     "试试呼气时双肩主动往下'沉'，像卸下一份重量",
     "这个起势，已经有古典舞的骨架了",
     (88, 73, 81, 90, 85)),
    (4,  8,  "倾腰·探手",
     "手臂延伸方向完全对！你的指尖意识比大多数人好，有古典感",
     "让腰先动，再带手出去，像'水袖'被风轻轻牵住",
     "探手有了古风韵味，再多练两遍就会让人忍不住截图",
     (82, 78, 77, 88, 84)),
    (8,  13, "举臂·展手",
     "眼神和头部转向配合自然，气质出来了！这是最难的部分，你做到了",
     "左臂再往外打开一些，想象'把整片天空托起来'",
     "这个动作有难度，你已经抓住了精髓，剩下是细化",
     (85, 71, 83, 92, 83)),
    (13, 17, "定势·立身",
     "收势干净利落，呼吸和音乐完全吻合。这种节奏控制很难得",
     "感受双脚均匀踩地的感觉，像'树根扎入地面'",
     "定势有了，整支舞的气场就成型了",
     (90, 80, 76, 89, 87)),
    (17, 21, "收势·含胸",
     "整体流畅度高，结尾有韵味！你的整体进步幅度非常明显",
     "含胸时肩膀保持舒展，想象'胸口轻轻夹住一朵花'",
     "跳完这支舞，你已经成功了",
     (88, 83, 82, 91, 89)),
]

TOTAL_SCORE = 82  # 最终综合评分

def find_font(size):
    for p in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def get_corr(t):
    for c in CORRECTIONS:
        if c[0] <= t < c[1]:
            return c
    return CORRECTIONS[-1]

def wrap_text(draw, text, font, x, y, max_w, fill, line_h=34):
    line = ""
    for ch in text:
        test = line + ch
        try: tw = draw.textbbox((0,0), test, font=font)[2]
        except: tw = len(test) * 16
        if tw > max_w:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h
            line = ch
        else:
            line = test
    if line:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y

def draw_beat_bar(draw, t, y, x0=32, x1=W-32):
    BPM = 72
    beat_dur = 60 / BPM
    total_beats = 8
    beat_w = (x1 - x0) // total_beats
    current_beat = int((t % (beat_dur * total_beats)) / beat_dur)
    draw.text((x0, y-20), "拍点同步", font=find_font(17), fill=(90, 80, 60))
    for i in range(total_beats):
        bx = x0 + i * beat_w
        is_cur = (i == current_beat)
        is_strong = (i % 4 == 0)
        col = GOLD2 if is_cur else ((80, 65, 35) if is_strong else (42, 35, 22))
        h = 24 if is_strong else 16
        if is_cur:
            draw.rectangle([bx+1, y-2, bx+beat_w-1, y+h+2], fill=(60, 48, 18))
        draw.rectangle([bx+2, y, bx+beat_w-2, y+h], fill=col)
        draw.text((bx+beat_w//2-4, y+h+3), str(i+1), font=find_font(13), fill=(70,60,40))

def animated_dim_score(base_score, t, seg_start):
    """0.8秒内从80%跑到目标分（不从0开始，避免一开始全-）"""
    elapsed = t - seg_start
    if elapsed < 0.8:
        start = int(base_score * 0.80)
        return start + int((base_score - start) * elapsed / 0.8)
    return base_score

def draw_hook_overlay(canvas, draw, frame_idx):
    """首1.5秒：全屏半透明黑底 + 大字钩子"""
    alpha = max(0.0, 1.0 - frame_idx / HOOK_END_FRAME)
    # 半透明层
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(200 * alpha)))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(overlay, (0, 0), overlay)
    result = canvas_rgba.convert("RGB")

    d = ImageDraw.Draw(result)
    f_big = find_font(72)
    f_sub = find_font(36)
    f_small = find_font(28)

    # 主标题
    title = "AI 正在分析你的舞蹈"
    try: tw = d.textbbox((0,0), title, font=f_big)[2]
    except: tw = 600
    d.text(((W-tw)//2, H//2 - 120), title, font=f_big, fill=GOLD2)

    # 副标题
    sub = "· 逐动作鼓励点评 ·"
    try: sw = d.textbbox((0,0), sub, font=f_sub)[2]
    except: sw = 300
    d.text(((W-sw)//2, H//2 - 30), sub, font=f_sub, fill=(200,180,100))

    # 品牌
    brand = "舞镜 WuJing AI"
    try: bw = d.textbbox((0,0), brand, font=f_small)[2]
    except: bw = 200
    d.text(((W-bw)//2, H//2 + 60), brand, font=f_small, fill=(120,100,60))

    return result

def draw_outro(canvas, draw, t):
    """最后2秒：全屏结尾总结"""
    elapsed = t - (DUR - 2)
    alpha = min(1.0, elapsed / 0.5)  # 0.5秒淡入

    overlay = Image.new("RGBA", (W, H), (12, 9, 4, int(220 * alpha)))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.paste(overlay, (0, 0), overlay)
    result = canvas_rgba.convert("RGB")

    d = ImageDraw.Draw(result)
    f_huge = find_font(110)
    f_big  = find_font(56)
    f_mid  = find_font(36)
    f_sm   = find_font(26)

    # 评分大圆
    cx, cy = W//2, H//2 - 180
    r = 140
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(30,24,14), outline=GOLD, width=5)

    sc = str(int(TOTAL_SCORE * min(1.0, elapsed / 0.8)))
    try: sw = d.textbbox((0,0), sc, font=f_huge)[2]
    except: sw = 80
    d.text((cx - sw//2, cy - 66), sc, font=f_huge, fill=GOLD)
    d.text((cx - 40, cy + 60), "综合评分", font=f_sm, fill=GRAY)

    # 主标语
    msg = "继续练，你在进步！"
    try: mw = d.textbbox((0,0), msg, font=f_big)[2]
    except: mw = 400
    d.text(((W-mw)//2, cy + r + 30), msg, font=f_big, fill=WHITE)

    # 副标语
    sub2 = "你的眼神气质得了 91 分"
    try: s2w = d.textbbox((0,0), sub2, font=f_mid)[2]
    except: s2w = 350
    d.text(((W-s2w)//2, cy + r + 100), sub2, font=f_mid, fill=GRN)

    # 五维小结
    dims = [("节奏感", 88), ("手臂延伸", 73), ("重心", 81), ("眼神气质", 91), ("整体流畅", 87)]
    bar_y = cy + r + 180
    for idx, (dname, dval) in enumerate(dims):
        bx = 80 + idx * 184
        col = GRN if dval >= 85 else (GOLD if dval >= 75 else YEL)
        d.text((bx, bar_y), dname, font=f_sm, fill=GRAY)
        d.rectangle([bx, bar_y+30, bx+100, bar_y+44], fill=(35,28,16))
        d.rectangle([bx, bar_y+30, bx+int(100*dval/100), bar_y+44], fill=col)
        d.text((bx+28, bar_y+50), str(dval), font=f_sm, fill=col)

    # 激励语
    cheer = "已解锁古典舞蹈 Level 2"
    cheer_y = cy + r + 380
    try: cw = d.textbbox((0,0), cheer, font=f_mid)[2]
    except: cw = 400
    d.rectangle([(W-cw)//2-20, cheer_y-10, (W+cw)//2+20, cheer_y+50], fill=(30,24,14), outline=GOLD, width=2)
    d.text(((W-cw)//2, cheer_y+8), cheer, font=f_mid, fill=GOLD)

    # CTA
    hook2 = "上传你的视频，看你的AI报告"
    hook2_y = cheer_y + 90
    try: h2w = d.textbbox((0,0), hook2, font=f_mid)[2]
    except: h2w = 450
    d.text(((W-h2w)//2, hook2_y), hook2, font=f_mid, fill=WHITE)

    # 品牌
    brand_y = H - 140
    d.line([(120, brand_y), (W-120, brand_y)], fill=(50,42,28), width=1)
    b_txt = "wujing.mylumee.app"
    try: btw = d.textbbox((0,0), b_txt, font=f_sm)[2]
    except: btw = 300
    d.text(((W-btw)//2, brand_y+16), b_txt, font=f_sm, fill=(90,76,48))
    b2 = "舞镜 WuJing AI · 上传你的舞，AI帮你进步"
    try: b2w = d.textbbox((0,0), b2, font=f_sm)[2]
    except: b2w = 500
    d.text(((W-b2w)//2, brand_y+52), b2, font=f_sm, fill=(70,58,36))

    return result

def draw_panel(draw, canvas, t, y_off, frame_idx):
    """极简暖奶白面板 — 优雅卡片风"""
    c = get_corr(t)
    seg_elapsed = t - c[0]
    dims_base = c[6]
    anim_scores = [animated_dim_score(d, t, c[0]) for d in dims_base]

    # 动态综合评分（从80%跑到目标，避免显示0）
    score = int(62 + min(20, t * 1.0))
    if seg_elapsed < 1.5:
        start = int(score * 0.80)
        score = start + int((score - start) * seg_elapsed / 1.5)

    M = 36  # margin

    # ── 面板底色：暖奶白 ──
    CREAM    = (250, 246, 238)
    INK      = (30,  22,  12)    # 近黑，主文
    GOLD_D   = (160, 120, 28)    # 深金，动作名
    GOLD_L   = (200, 162, 60)    # 亮金，装饰
    SEP      = (228, 216, 192)   # 分割线
    SAGE     = (45,  110, 65)    # 森林绿，夸赞
    TAUPE    = (120, 100, 68)    # 暖棕，进阶提示
    SCORE_BG = (245, 238, 218)   # 评分圆底

    # 画面板背景
    panel_img = Image.new("RGB", (W, PANEL_H), CREAM)
    pd = ImageDraw.Draw(panel_img)

    # 顶部金色细线
    pd.rectangle([0, 0, W, 4], fill=GOLD_D)
    # 顶部细腻渐变感（用3层递减不透明度模拟）
    pd.rectangle([0, 4, W, 8], fill=(235, 224, 196))

    y = 22

    # ── 动作名（左） + 评分圆（右） ──
    f_act   = find_font(56)
    f_score = find_font(72)
    f_lg    = find_font(36)
    f_md    = find_font(29)
    f_sm    = find_font(22)
    f_xs    = find_font(19)

    pd.text((M, y), c[2], font=f_act, fill=GOLD_D)

    # 评分圆（右侧）
    r = 62
    cx, cy_c = W - M - r, y + r + 6
    pd.ellipse([cx-r, cy_c-r, cx+r, cy_c+r], fill=SCORE_BG, outline=GOLD_D, width=2)
    sc_str = str(score)
    try: sw = pd.textbbox((0,0), sc_str, font=f_score)[2]
    except: sw = 52
    pd.text((cx - sw//2, cy_c - 40), sc_str, font=f_score, fill=GOLD_D)
    pd.text((cx - 24, cy_c + 30), "AI评分", font=f_xs, fill=TAUPE)
    y += r*2 + 28

    # 进度细线
    prog = min(1.0, t / DUR)
    bw = W - M*2 - 120
    pd.rectangle([M, y, M+bw, y+4], fill=SEP)
    pd.rectangle([M, y, M+int(bw*prog), y+4], fill=GOLD_L)
    pd.text((M+bw+14, y-6), f"{int(prog*100)}%", font=f_xs, fill=TAUPE)
    y += 28

    pd.line([(M, y), (W-M, y)], fill=SEP, width=1)
    y += 26

    # ── 夸赞（主角，绿色大字）──
    pd.text((M, y), "◆  做得好", font=f_md, fill=SAGE)
    y += 42
    y = wrap_text(pd, c[3], f_lg, M+4, y, W - M*2, SAGE, line_h=48)
    y += 28

    pd.line([(M, y), (W-M, y)], fill=SEP, width=1)
    y += 26

    # ── 进阶提示 ──
    pd.text((M, y), "进阶一步", font=f_sm, fill=TAUPE)
    y += 34
    y = wrap_text(pd, c[4], f_md, M+4, y, W - M*2, TAUPE, line_h=38)
    y += 28

    # ── 五维评分圆（大一点，填满空间）──
    pd.line([(M, y), (W-M, y)], fill=SEP, width=1)
    y += 20
    pd.text((M, y), "本段评估", font=f_xs, fill=TAUPE)
    y += 30

    dim_labels = ["节奏", "手臂", "重心", "眼神", "流畅"]
    cell_w = (W - M*2) // 5
    dot_r = 36  # 更大的圆
    for j, (dname, dval) in enumerate(zip(dim_labels, anim_scores)):
        cx2 = M + j * cell_w + cell_w // 2
        col = SAGE if dval >= 85 else (GOLD_D if dval >= 75 else (180, 140, 60))
        pd.ellipse([cx2-dot_r, y, cx2+dot_r, y+dot_r*2], fill=SCORE_BG, outline=col, width=2)
        sc2 = str(dval)
        try: sw2 = pd.textbbox((0,0), sc2, font=f_md)[2]
        except: sw2 = 22
        pd.text((cx2-sw2//2, y+dot_r-16), sc2, font=f_md, fill=col)
        try: lw = pd.textbbox((0,0), dname, font=f_xs)[2]
        except: lw = len(dname)*11
        pd.text((cx2-lw//2, y+dot_r*2+8), dname, font=f_xs, fill=TAUPE)
    y += dot_r*2 + 48

    # ── 鼓励收尾 ──
    pd.line([(M, y), (W-M, y)], fill=SEP, width=1)
    y += 26
    y = wrap_text(pd, c[5], f_lg, M, y, W - M*2, GOLD_D, line_h=42)
    y += 16

    # ── 底部导航标签 ──
    nav_y = PANEL_H - 52
    pd.line([(M, nav_y), (W-M, nav_y)], fill=SEP, width=1)
    nav_y += 10
    xb = M
    for ci in CORRECTIONS:
        is_cur = (ci == c)
        lbl = ci[2]
        try: tw = pd.textbbox((0,0), lbl, font=f_xs)[2] + 20
        except: tw = len(lbl)*11+20
        if xb + tw > W - M: break
        bg = (240, 228, 196) if is_cur else CREAM
        ol = GOLD_D if is_cur else SEP
        pd.rectangle([xb, nav_y, xb+tw, nav_y+28], fill=bg, outline=ol)
        pd.text((xb+9, nav_y+5), lbl, font=f_xs, fill=GOLD_D if is_cur else TAUPE)
        xb += tw + 8

    # 品牌
    brand = "舞镜 WuJing AI"
    try: btw = pd.textbbox((0,0), brand, font=f_xs)[2]
    except: btw = 140
    pd.text((W//2 - btw//2, PANEL_H - 20), brand, font=f_xs, fill=(180, 165, 130))

    # 贴回主画布
    canvas.paste(panel_img, (0, y_off))

# ─── Step 1: 提取帧 ───
print("[1/4] 提取帧...")
subprocess.run([
    "ffmpeg", "-y", "-i", BLOGGER,
    "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}",
    "-q:v", "2", f"{TMP}/b_%05d.jpg"
], capture_output=True)

subprocess.run([
    "ffmpeg", "-y", "-i", LEARNER,
    # 增亮滤镜：学员视频亮度×1.35，对比度×1.1
    "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},eq=brightness=0.06:contrast=1.1:saturation=1.1",
    "-q:v", "2", f"{TMP}/l_%05d.jpg"
], capture_output=True)

b_frames = sorted([f for f in os.listdir(TMP) if f.startswith("b_")])
l_frames = sorted([f for f in os.listdir(TMP) if f.startswith("l_")])
n = min(len(b_frames), len(l_frames), DUR * FPS)
print(f"  博主{len(b_frames)}帧，学员{len(l_frames)}帧，取{n}帧")

# ─── Step 2: 合成每帧 ───
print("[2/4] PIL合成中...")
FRAMES_OUT = os.path.join(TMP, "out")
os.makedirs(FRAMES_OUT, exist_ok=True)

fn_label = find_font(26)

for i in range(n):
    t = i / FPS
    bf = Image.open(os.path.join(TMP, b_frames[i])).convert("RGB")
    lf = Image.open(os.path.join(TMP, l_frames[i])).convert("RGB")

    canvas = Image.new("RGB", (W, H), BG_VIDEO)
    draw = ImageDraw.Draw(canvas)

    canvas.paste(bf, (0, 0))
    canvas.paste(lf, (VIDEO_W, 0))

    # 分割线
    draw.line([(VIDEO_W-1, 0), (VIDEO_W-1, VIDEO_H)], fill=GOLD, width=3)
    draw.line([(VIDEO_W+1, 0), (VIDEO_W+1, VIDEO_H)], fill=(80, 64, 20), width=1)

    # 顶部标签
    draw.rectangle([0, 0, VIDEO_W, 50], fill=(12, 9, 4))
    draw.text((16, 12), "◆ 博主示范", font=fn_label, fill=GOLD)
    draw.rectangle([VIDEO_W, 0, W, 50], fill=(12, 9, 4))
    draw.text((VIDEO_W+16, 12), "▷ 学员跟练", font=fn_label, fill=GRAY)

    # 面板背景
    draw.rectangle([0, VIDEO_H, W, H], fill=BG_PANEL)

    # 是否是结尾
    if i >= OUTRO_START_FRAME:
        canvas = draw_outro(canvas, draw, t)
    else:
        draw_panel(draw, canvas, t, VIDEO_H, i)
        # 首帧钩子（前1.5秒）
        if i < HOOK_END_FRAME:
            canvas = draw_hook_overlay(canvas, draw, i)

    canvas.save(os.path.join(FRAMES_OUT, f"f_{i:05d}.jpg"), quality=90)
    if i % 30 == 0:
        print(f"  {i}/{n} ({t:.1f}s)")

print("[2/4] 合成完成")

# ─── Step 3: 编码 ───
print("[3/4] 编码视频...")
no_audio = os.path.join(TMP, "no_audio.mp4")
subprocess.run([
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", f"{TMP}/out/f_%05d.jpg",
    "-c:v", "libx264", "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
    no_audio
], capture_output=True)

# ─── Step 4: 加音频 ───
print("[4/4] 加原声...")
output = os.path.join(OUT_DIR, "wujing_compare_v5.mp4")
r = subprocess.run([
    "ffmpeg", "-y",
    "-i", no_audio, "-i", BLOGGER,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
    "-shortest", output
], capture_output=True, text=True)

if r.returncode != 0:
    shutil.copy(no_audio, output)
    print("  (音频合并失败，输出无声版)")

size = os.path.getsize(output)/1024/1024
print(f"\n✅ {output}")
print(f"   {size:.1f}MB | {DUR}s | {W}x{H} | {FPS}fps | v5")
