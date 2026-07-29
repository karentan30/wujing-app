#!/usr/bin/env python3
"""舞镜营销卡 v2 - 混合生成：AI底图+渐变叠加+高对比文字+可视CTA"""

from PIL import Image, ImageDraw, ImageFont
import os, math

OUT = "/Users/karen/projects/舞镜/docs/mockups"
W, H = 1792, 2240

# ── Brand Colors ──
GOLD    = (200, 169, 110)
GOLD_L  = (232, 201, 142)
GOLD_D  = (170, 140, 80)
GREEN   = (80,  210, 130)
BLUE    = (122, 180, 255)
PINK    = (255, 110, 180)
RED     = (255, 70,  70)
YELLOW  = (255, 209, 102)
MUTED   = (130, 140, 160)
TEXT    = (235, 238, 245)
DIM     = (90,  100, 120)
BORDER  = (40,  45,  60)
CARD_BG = (18,  20,  30)
BG_DARK = (8,   9,  15)

FONT_PATH = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"

def font(sz, idx=0):
    return ImageFont.truetype(FONT_PATH, sz, index=idx)

def blend_bg(base_path):
    """Load AI bg and brighten it with multi-point glow overlay"""
    try:
        bg = Image.open(base_path).resize((W, H)).convert('RGBA')
    except:
        bg = Image.new('RGBA', (W, H), BG_DARK + (255,))

    overlay = Image.new('RGBA', (W, H), (0,0,0,0))
    d = ImageDraw.Draw(overlay)

    # Core center glow
    for r in range(0, 1200, 10):
        a = max(0, int(28 * (1 - r/1200)))
        if a > 0:
            d.ellipse([W//2-r, H//2-r, W//2+r, H//2+r], fill=(200, 169, 110, a))

    # Bottom CTA area glow (warm)
    cx, cy_bottom = W//2, int(H * 0.88)
    for r in range(0, 900, 10):
        a = max(0, int(35 * (1 - r/900)))
        if a > 0:
            d.ellipse([cx-r, cy_bottom-r, cx+r, cy_bottom+r], fill=(232, 201, 142, a))

    # Top area highlight
    for r in range(0, 600, 10):
        a = max(0, int(20 * (1 - r/600)))
        if a > 0:
            d.ellipse([W//2-r, -100-r, W//2+r, -100+r], fill=(200, 169, 110, a))

    bg = Image.alpha_composite(bg, overlay)
    return bg.convert('RGB')

def dark_card():
    """Fallback pure dark gradient card"""
    img = Image.new('RGB', (W, H), BG_DARK)
    d = ImageDraw.Draw(img)
    # Gold glow top-right
    for i in range(300):
        alpha = max(0, 8 - i//35)
        cx, cy = W-80, -40 + i//3
        d.ellipse([cx-i, cy-i, cx+i, cy+i], fill=(190, 160, 85, alpha))
    return img

def rbox(draw, xy, r, fill=None, outline=None, w=1):
    draw.rounded_rectangle(xy, r, fill=fill, outline=outline, width=w)

def score_ring(draw, cx, cy, r, score, label, sub):
    """Gold-green gradient score ring"""
    # Glow
    for i in range(8):
        a = 10 - i
        draw.ellipse([cx-r-10-i, cy-r-10-i, cx+r+10+i, cy+r+10+i],
                     outline=(GOLD[0], GOLD[1], GOLD[2], a), width=2)

    # BG circle
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=BORDER, width=10)

    # Filled arc (conic gradient simulation)
    angle = score * 3.6 - 90
    steps = 20
    for i in range(steps):
        a0 = -90 + (i * angle / steps)
        a1 = -90 + ((i+1) * angle / steps)
        ratio = i / steps
        col = (
            int(GOLD[0] + (GREEN[0]-GOLD[0])*ratio),
            int(GOLD[1] + (GREEN[1]-GOLD[1])*ratio),
            int(GOLD[2] + (GREEN[2]-GOLD[2])*ratio),
        )
        draw.arc([cx-r, cy-r, cx+r, cy+r], a0, a1, fill=col, width=10)

    # Inner text
    f1 = font(72, 5)
    f2 = font(24)
    f3 = font(18)
    b = d.textbbox((0,0), str(score), font=f1)
    d.text((cx-(b[2]-b[0])//2, cy-60), str(score), font=f1, fill=GOLD_L)
    b = d.textbbox((0,0), label, font=f2)
    d.text((cx-(b[2]-b[0])//2, cy+5), label, font=f2, fill=TEXT)
    b = d.textbbox((0,0), sub, font=f3)
    d.text((cx-(b[2]-b[0])//2, cy+38), sub, font=f3, fill=DIM)

def dim_bar(draw, x, y, w, h, name, sc, col):
    """One dimension row"""
    d.text((x, y), name, font=font(20), fill=DIM)
    d.text((x+w-60, y-2), str(sc), font=font(30,5), fill=col)
    rbox(draw, [x, y+36, x+w, y+41], 3, fill=(30,34,50))
    if sc > 0:
        rbox(draw, [x, y+36, x+int(w*sc/100), y+41], 3, fill=col)

def cta(draw, x, y, w, h, text, extra=None):
    """CTA button - bright and visible"""
    # Backlight glow
    glow_r = max(w, h)
    for r in range(0, glow_r, 15):
        a = max(0, int(18 * (1 - r/glow_r)))
        draw.ellipse([x+w//2-r, y+h//2-r, x+w//2+r, y+h//2+r],
                     fill=(232, 201, 142, a))

    # Shadow
    for i in range(3):
        rbox(draw, [x-1, y+1+i, x+w+1, y+h+1+i], 14, fill=(0,0,0,40+i*10))

    # Button gradient (bright gold to golden)
    for i in range(h):
        ratio = i / h
        col = (
            min(255, int(GOLD_D[0] + (255-GOLD_D[0])*ratio*0.8)),
            min(255, int(GOLD_D[1] + (255-GOLD_D[1])*ratio*0.6)),
            min(255, int(GOLD_D[2] + (255-GOLD_D[2])*ratio*0.3)),
        )
        draw.rectangle([x, y+i, x+w, y+i+1], fill=col)

    rbox(draw, [x, y, x+w, y+h], 14, outline=GOLD, w=1)

    # Text
    f = font(24, 5)
    b = draw.textbbox((0,0), text, font=f)
    draw.text((x+(w-(b[2]-b[0]))//2, y+(h-(b[3]-b[1]))//2-1), text, font=f, fill=(8,9,15))

    if extra:
        draw.text((x+w//2, y+h+20), extra, font=font(16), fill=DIM, anchor="mt")


def make_card1():
    """产品入口卡"""
    img = blend_bg(os.path.join(OUT, "bg1_product.png"))
    global d
    d = ImageDraw.Draw(img)

    # Brand (top)
    d.text((40, 30), "舞镜 · WUJING", font=font(24, 5), fill=GOLD)
    d.text((40, 62), "AI 舞蹈评分", font=font(16), fill=DIM)

    # Hero title
    d.text((W//2, 180), "上传练习视频", font=font(48, 5), fill=TEXT, anchor="mm")
    d.text((W//2, 230), "AI 逐拍对比原版 · 给你评分 + 精准改正建议", font=font(20), fill=DIM, anchor="mm")

    # Step flow
    steps = ["① 上传视频", "② AI 逐帧对比", "③ 获得评分报告"]
    sw = 220
    sx = (W - len(steps)*sw)//2
    for i, s in enumerate(steps):
        cx = sx + i*sw + sw//2
        d.text((cx, 290), s, font=font(18), fill=DIM, anchor="mt")
        if i < len(steps)-1:
            ax = cx + sw//2 - 15
            d.line([(cx+40, 275), (ax, 275)], fill=BORDER, width=2)
            d.polygon([(ax-6, 269), (ax+4, 275), (ax-6, 281)], fill=BORDER)

    # Score ring (centered)
    score_ring(d, W//2, 500, 110, 87, "综合评分", "节拍92 · 延展85 · 镜像80 · 情感90")

    # Dimensions 2x2
    dims = [("节拍契合度", 92, GREEN), ("动作延展度", 85, BLUE),
            ("镜像一致性", 80, YELLOW), ("情感表达力", 90, GREEN)]
    bw, bg = 330, 16
    bx = (W - 2*bw - bg)//2
    for i, (n, s, c) in enumerate(dims):
        col, row = i%2, i//2
        dim_bar(d, bx+col*(bw+bg), 680+row*70, bw, 40, n, s, c)

    # CTA (bottom)
    cta(d, (W-480)//2, H-180, 480, 60, "📱 免费开始评分", "拍一段 · AI 看 · 立刻知道怎么改")

    # Footer
    d.text((40, H-35), "wujing.mylumee.cn", font=font(14), fill=(60,65,80))
    d.text((W-100, H-35), "01 / 03", font=font(14), fill=(60,65,80))

    p = os.path.join(OUT, "card1_final.png")
    img.save(p)
    print(f"✅ Card 1: {p}")
    return img

def make_card2():
    """三场景卡"""
    img = blend_bg(os.path.join(OUT, "bg2_scenarios.png"))
    global d
    d = ImageDraw.Draw(img)

    # Brand
    d.text((40, 30), "舞镜 · WUJING", font=font(24, 5), fill=GOLD)
    d.text((40, 62), "三场景 · 一个工具", font=font(16), fill=DIM)

    # Title
    d.text((W//2, 190), "你会在哪里用到舞镜？", font=font(44, 5), fill=GOLD_L, anchor="mm")
    rbox(d, [W//2-60, 232, W//2+60, 234], 1, fill=GOLD)

    # Three scenario cards
    scenarios = [
        ("💒", "婚礼 · 第一支舞", "排练时间不够，怕跳错？",
         "上传彩排视频 → AI 帮你对历史", (28,14,20), (255,110,180)),
        ("🎤", "年会 · 零基础节目", "记不住动作，跟不上拍？",
         "先录一段 → AI 圈出跟不上的位置", (14,20,32), (122,180,255)),
        ("💃", "K-pop 翻跳 · 想看看像不像原版", "自己跳还行，发出去怕翻车？",
         "上传你的 vs 原版 → AI 逐帧算分", (14,26,18), (80,210,130)),
    ]

    cw, cs, sy = 1200, 20, 280
    for i, (icon, title, pain, sol, bgc, acc) in enumerate(scenarios):
        cy = sy + i*145
        rbox(d, [(W-cw)//2, cy, (W+cw)//2, cy+135], 14,
             fill=(bgc[0]*255//35, bgc[1]*255//35, bgc[2]*255//35, 210),
             outline=(acc[0]//4, acc[1]//4, acc[2]//4), w=1)

        # Icon
        d.text((300, cy+18), icon, font=font(30), fill=acc)
        # Title
        d.text((360, cy+20), title, font=font(22, 5), fill=TEXT)
        # Pain
        d.text((360, cy+60), "❌ " + pain, font=font(17), fill=(255,80,80,200))
        # Solution
        d.text((360, cy+90), "✅ " + sol, font=font(17), fill=GREEN)

    # Tags
    tags = [("古典舞", GOLD), ("街舞", BLUE), ("爵士", PINK), ("拉丁", GREEN), ("韩舞", YELLOW)]
    ty = sy + 3*145 + 15
    for i, (t, c) in enumerate(tags):
        d.ellipse([300+i*120, ty+8, 300+i*120+10, ty+18], fill=c)
        d.text((318+i*120, ty+4), t, font=font(16), fill=DIM)

    # CTA (bottom)
    cta(d, (W-520)//2, H-180, 520, 60, "上传你的舞蹈 → 免费评分", "支持 抖音 / 小红书 / YouTube / Bilibili 链接")

    # Footer
    d.text((40, H-35), "wujing.mylumee.cn", font=font(14), fill=(60,65,80))
    d.text((W-100, H-35), "02 / 03", font=font(14), fill=(60,65,80))

    p = os.path.join(OUT, "card2_final.png")
    img.save(p)
    print(f"✅ Card 2: {p}")
    return img

def make_card3():
    """AI评分报告示样卡"""
    img = blend_bg(os.path.join(OUT, "bg3_score.png"))
    global d
    d = ImageDraw.Draw(img)

    # Brand
    d.text((40, 28), "舞镜 · AI 动作评分报告", font=font(22, 5), fill=GOLD)

    # Tags
    for label, bg, tc in [("示范", (18,28,50), BLUE), ("学员", (18,40,18), GREEN)]:
        b = d.textbbox((0,0), label, font=font(16))
        tw = b[2]-b[0]
        rbox(d, [370, 28, 370+tw+16, 28+28], 8, fill=bg+(180,))
        d.text((370+8, 28+6), label, font=font(16), fill=tc)
        # Only increment once
        break
    # Second tag
    b = d.textbbox((0,0), "学员", font=font(16))
    tw = b[2]-b[0]
    rbox(d, [370+tw+20, 28, 370+tw*2+36, 28+28], 8, fill=(18,40,18,180))
    d.text((370+tw+28, 28+6), "学员", font=font(16), fill=GREEN)

    # Score ring
    score_ring(d, W//2, 470, 130, 76, "整体表现良好", "古典舞 · 26秒")

    # Dimensions 2x2
    dims = [
        ("节拍契合度", 82, GREEN),
        ("动作延展度", 71, YELLOW),
        ("镜像一致性", 70, YELLOW),
        ("情感表达力", 83, GREEN),
    ]

    dw, dg = 280, 20
    dsx = (W - 2*dw - dg)//2
    for i, (n, s, c) in enumerate(dims):
        col, row = i%2, i//2
        dx = dsx + col*(dw+dg)
        dy = 630 + row*85

        rbox(d, [dx, dy, dx+dw, dy+75], 10, fill=CARD_BG+(200,), outline=BORDER, w=1)
        rbox(d, [dx+6, dy+6, dx+dw-6, dy+9], 3, fill=c)

        d.text((dx+18, dy+24), n, font=font(18), fill=DIM)
        d.text((dx+dw-24, dy+18), str(s), font=font(28,5), fill=c, anchor="rt")

        rbox(d, [dx+18, dy+58, dx+dw-18, dy+61], 2, fill=BORDER)
        if s > 0:
            rbox(d, [dx+18, dy+58, dx+18+int((dw-36)*s/100), dy+61], 2, fill=c)

    # Divider
    dv = 630 + 2*85 + 15
    rbox(d, [W//2-80, dv, W//2+80, dv+1], 1, fill=GOLD)
    d.text((W//2, dv-20), "5 处需改正  ·  2 处亮点", font=font(18), fill=GOLD, anchor="mm")

    # Problem cards
    problems = [
        ("重点改正", RED, [
            "⑥s  弓步太浅，上身未前倾跟进",
            "⑤s  收势过早，比老师提前约 1 拍",
        ]),
        ("需注意", YELLOW, [
            "③s  手型不到位，指尖缺少延伸",
            "⑧s  转身头部没领先，眼神滞后",
            "③s  左手贴腰，缺少流动感",
        ]),
    ]

    py = dv + 28
    px = 180
    pw = W - 2*px
    for i, (lbl, col, items) in enumerate(problems):
        cy = py + i * 90
        # Label badge
        rbox(d, [px, cy, px+80, cy+26], 8, fill=(col[0],col[1],col[2],30),
             outline=(col[0],col[1],col[2],80), w=1)
        d.text((px+8, cy+5), lbl, font=font(15,3), fill=col)

        for j, item in enumerate(items):
            iy = cy + 30 + j*26
            d.ellipse([px+90, iy+4, px+100, iy+14], fill=(col[0],col[1],col[2],180))
            d.text((px+110, iy), item, font=font(17), fill=TEXT)

    # Action buttons area (near bottom)
    by = py + 2*90 + 15
    rbox(d, [(W-520)//2, by, (W+520)//2, by+60], 14, fill=CARD_BG+(180,), outline=BORDER, w=1)
    d.text((W//2, by+18), "📋 按问题制定练习计划", font=font(20, 5), fill=GOLD_L, anchor="mm")
    d.text((W//2, by+40), "→ AI 自动生成 5 天专项练习", font=font(15), fill=DIM, anchor="mm")

    # CTA (bottom)
    cta(d, (W-480)//2, H-180, 480, 58, "扫码查看完整报告 →", "wujing.mylumee.cn")

    # QR placeholder
    qs = 70
    qx, qy2 = (W-480)//2 - qs - 30, H-190
    rbox(d, [qx, qy2, qx+qs, qy2+qs], 8, fill=None, outline=(GOLD[0],GOLD[1],GOLD[2],60), w=1)
    for r in range(5, 35, 7):
        rbox(d, [qx+r, qy2+r, qx+qs-r, qy2+qs-r], 4, fill=(GOLD[0],GOLD[1],GOLD[2],30))
    d.text((qx+qs//2, qy2+qs+4), "扫码", font=font(12), fill=(60,65,80), anchor="mt")

    # Footer
    d.text((40, H-35), "wujing.mylumee.cn", font=font(14), fill=(60,65,80))
    d.text((W-100, H-35), "03 / 03", font=font(14), fill=(60,65,80))

    p = os.path.join(OUT, "card3_final.png")
    img.save(p)
    print(f"✅ Card 3: {p}")
    return img

if __name__ == "__main__":
    d = None
    print("🏗️ Building 舞镜 marketing cards v2...")
    make_card1()
    make_card2()
    make_card3()
    print(f"\n✅ All done! Check {OUT}/")
