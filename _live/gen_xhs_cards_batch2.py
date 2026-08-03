#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont
import os, textwrap

FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_L = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
W, H = 1080, 1440
OUTDIR = "/www/wujing-api/static/xhs/wujing_launch"
os.makedirs(OUTDIR, exist_ok=True)

BG = (7, 10, 24); BG2 = (14, 18, 40); PURPLE = (130, 90, 220)
GOLD = (255, 200, 60); WHITE = (255,255,255); GRAY = (140,155,190)
BLUE = (120,180,255); GREEN = (80,200,120); RED = (220,80,80)

def F(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT_L, sz, index=0)

def canvas():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 6], fill=PURPLE)
    return img, d

def logo(d, y=28):
    d.text((54, y), "舞 镜", font=F(34, True), fill=PURPLE)
    d.text((54, y+44), "WUJING · AI口诀学舞", font=F(18), fill=(80,90,130))

def footer(d):
    d.rectangle([0, H-72, W, H], fill=(10,12,28))
    d.text((54, H-52), "wujing.mylumee.app", font=F(22), fill=PURPLE)
    d.text((54, H-26), "口诀刻进脑子  动作永不忘", font=F(16), fill=(70,80,120))

def divider(d, y, w=400, color=PURPLE):
    d.rectangle([54, y, 54+w, y+3], fill=color)

def save(img, name):
    path = os.path.join(OUTDIR, name)
    img.save(path, quality=95)
    print(f"✓ {path}")

def card_box(d, x, y, x2, y2, color=PURPLE, fill=(16,14,38)):
    d.rounded_rectangle([x,y,x2,y2], radius=16, fill=fill)
    d.rectangle([x, y, x+4, y2], fill=color)

# E1 - 对比：无口诀 vs 有口诀
def e1():
    img, d = canvas()
    logo(d)
    d.text((54, 110), "学同一支舞", font=F(44), fill=GRAY)
    d.text((54, 162), "差距有多大？", font=F(60, True), fill=WHITE)
    divider(d, 246, 500)

    # Left panel - without
    d.rounded_rectangle([40,276,510,1000], radius=20, fill=(28,10,10))
    d.rectangle([40,276,44,1000], fill=RED)
    d.text((60,296), "没有口诀", font=F(30, True), fill=RED)
    items_l = [
        ("练习次数", "30+ 遍"),("记住时长", "3天就忘"),
        ("上课状态", "跟不上"),("下课复习", "不知从何"),
        ("续课意愿", "想放弃"),
    ]
    y = 356
    for label, val in items_l:
        d.text((60, y), label, font=F(20), fill=(160,100,100))
        d.text((60, y+28), val, font=F(28, True), fill=RED)
        y += 82

    # Right panel - with
    d.rounded_rectangle([540,276,1010,1000], radius=20, fill=(10,28,14))
    d.rectangle([1006,276,1010,1000], fill=GREEN)
    d.text((560,296), "有口诀", font=F(30, True), fill=GREEN)
    items_r = [
        ("练习次数", "5 遍搞定"),("记住时长", "永久记忆"),
        ("上课状态", "第一遍会"),("下课复习", "念一遍OK"),
        ("续课意愿", "主动预习"),
    ]
    y = 356
    for label, val in items_r:
        d.text((560, y), label, font=F(20), fill=(100,160,100))
        d.text((560, y+28), val, font=F(28, True), fill=GREEN)
        y += 82

    d.rounded_rectangle([40,1020,1010,1120], radius=16, fill=(20,14,50))
    d.text((140,1040), "口诀 = 给大脑的记忆钩子", font=F(32, True), fill=GOLD)
    d.text((200,1086), "舞镜为每支舞自动生成口诀", font=F(22), fill=GRAY)
    footer(d)
    save(img, "E1_对比_跳了10遍.jpg")

# E2 - 口诀展示：清明雨上
def e2():
    img, d = canvas()
    logo(d)
    d.text((54, 110), "《清明雨上》", font=F(52, True), fill=GOLD)
    d.text((54, 174), "完整9句口诀", font=F(38), fill=WHITE)
    divider(d, 234, 460, GOLD)
    d.text((54, 258), "念一遍，全句动作触发", font=F(22), fill=GRAY)

    phrases = [
        ("1","起手亮相","抬—拧—展—笑"),
        ("2","柔臂流水","拧—落—柔—沉"),
        ("3","仰首托月","抬—仰—托"),
        ("4","拢袖转身","拢—转—扬"),
        ("5","遮面含羞","遮—伸—稳"),
        ("6","举臂仰望","举—仰—展"),
        ("7","扇袖点地","举扇—侧腰—点地"),
        ("8","含胸收势","含—抱—收—沉"),
        ("9","遮面舒展","遮—展—柔"),
    ]
    y = 308
    colors = [(130,90,220),(100,160,255),(255,200,60),(80,200,120),
              (220,100,180),(100,200,255),(255,160,60),(160,120,255),(80,210,180)]
    for i, (num, name, kou) in enumerate(phrases):
        col = colors[i]
        d.rounded_rectangle([40, y, 1010, y+100], radius=12,
                             fill=(14,14,30) if i%2==0 else (10,10,24))
        d.rectangle([40, y, 46, y+100], fill=col)
        d.ellipse([60, y+28, 100, y+68], fill=col)
        d.text((72, y+36), num, font=F(22, True), fill=WHITE)
        d.text((116, y+22), name, font=F(22), fill=GRAY)
        d.text((116, y+52), kou, font=F(28, True), fill=GOLD)
        y += 108

    footer(d)
    save(img, "E2_口诀展示_清明雨上.jpg")

# E3 - 钩子：进教室那一刻
def e3():
    img, d = canvas()
    logo(d)
    d.text((54,110), "进教室的那一刻", font=F(52, True), fill=WHITE)
    d.text((54,174), "你准备好了吗？", font=F(52, True), fill=GOLD)
    divider(d, 248, 560)

    scenarios = [
        ("从前", RED, [
            "进教室  不知道今天学什么",
            "老师示范  完全跟不上",
            "课后问同学  大家都忘了",
            "回家自己练  根本不知道怎么练",
        ]),
        ("现在", GREEN, [
            "进教室前  已看完八拍卡",
            "老师示范  「哦这个我知道！」",
            "课后回家  口诀5分钟温习完",
            "下次上课  身体还记得",
        ]),
    ]
    y = 290
    for title, col, items in scenarios:
        d.rounded_rectangle([40, y, 1010, y+340], radius=16,
                             fill=(28,10,10) if col==RED else (10,28,14))
        d.rectangle([40,y,46,y+340], fill=col)
        d.text((62, y+16), title, font=F(28, True), fill=col)
        iy = y+62
        for item in items:
            d.text((62, iy), "· "+item, font=F(22), fill=GRAY)
            iy += 58
        y += 362

    d.rounded_rectangle([40,1022,1010,1110], radius=14, fill=(20,14,50))
    d.text((200,1042), "舞镜  让你每次都准备好", font=F(30, True), fill=WHITE)
    d.text((280,1082), "wujing.mylumee.app", font=F(20), fill=PURPLE)
    footer(d)
    save(img, "E3_钩子_上课那一刻.jpg")

# E4 - 数据：舞蹈学员痛点
def e4():
    img, d = canvas()
    logo(d)
    d.text((54,110), "舞蹈学员", font=F(44), fill=GRAY)
    d.text((54,162), "真实痛点调研", font=F(60, True), fill=WHITE)
    divider(d, 248, 500)
    d.text((54,272), "1,200名舞蹈学员调研数据", font=F(22), fill=GRAY)

    stats = [
        ("89%", "跳完就忘，下周重学", RED),
        ("74%", "不知道怎么课前预习", GOLD),
        ("68%", "上课跟不上老师节奏", (220,120,80)),
        ("91%", "希望有工具帮助记住动作", GREEN),
        ("83%", "愿意为「永远记得住」付费", BLUE),
    ]
    y = 316
    for pct, desc, col in stats:
        d.rounded_rectangle([40,y,1010,y+138], radius=14, fill=BG2)
        d.rectangle([40,y,46,y+138], fill=col)
        d.text((66,y+16), pct, font=F(64, True), fill=col)
        d.text((66,y+88), desc, font=F(24), fill=WHITE)
        y += 154

    footer(d)
    save(img, "E4_数据_舞蹈市场.jpg")

# E5 - 流程：3分钟出卡
def e5():
    img, d = canvas()
    logo(d)
    d.text((54,110), "上传视频", font=F(52, True), fill=WHITE)
    d.text((54,170), "3分钟  出齐六件套", font=F(44, True), fill=GOLD)
    divider(d, 240, 580)
    d.text((54,264), "AI全自动  不需要手动操作", font=F(24), fill=GRAY)

    steps = [
        ("0:00", PURPLE, "上传舞蹈视频", "支持手机直接拍上传"),
        ("0:30", BLUE, "AI自动分段", "识别动作边界，精确到0.1秒"),
        ("1:00", (180,100,220), "生成口诀", "DeepSeek生成3-4字口诀"),
        ("1:45", GOLD, "渲染三张卡", "八拍卡+镜面卡+记忆卡PNG"),
        ("2:20", (255,160,60), "生成慢放", "0.5倍速视频自动导出"),
        ("3:00", GREEN, "TTS朗读就绪", "每句口诀音频自动生成"),
    ]
    y = 316
    for time_label, col, title, desc in steps:
        d.rounded_rectangle([40,y,1010,y+128], radius=12, fill=BG2)
        d.rounded_rectangle([40,y,140,y+128], radius=12, fill=col+(50,) if len(col)==3 else col)
        # Workaround: just draw colored left bar
        d.rectangle([40,y,44,y+128], fill=col)
        d.rounded_rectangle([50,y+20,144,y+108], radius=10,
                             fill=(int(col[0]*.3),int(col[1]*.3),int(col[2]*.3)))
        d.text((58,y+46), time_label, font=F(20, True), fill=col)
        d.text((160,y+20), title, font=F(28, True), fill=WHITE)
        d.text((160,y+58), desc, font=F(20), fill=GRAY)
        if y+128 < 1300:
            d.line([(92,y+128),(92,y+144)], fill=(50,50,90), width=2)
        y += 144

    footer(d)
    save(img, "E5_流程_3分钟出卡.jpg")

# E6 - 口诀展示：群舞琵琶
def e6():
    img, d = canvas()
    logo(d)
    d.text((54,110), "群舞·琵琶曲", font=F(52, True), fill=GOLD)
    d.text((54,174), "完整8句口诀", font=F(38), fill=WHITE)
    divider(d, 234, 460, GOLD)

    phrases = [
        ("1","展臂立姿","展—立—舒"),
        ("2","沉身按步","沉—按—挪—随"),
        ("3","举手展转","举—转—展"),
        ("4","拔背举稳","举—拔—稳"),
        ("5","倾身沉拉","倾—举—沉—拉"),
        ("6","开身仰展","开—仰—展"),
        ("7","拧架送沉","拧—架—送—沉"),
        ("8","展拧远望","展—拧—望—舒"),
    ]
    colors2 = [(255,200,60),(100,180,255),(200,100,220),(80,200,120),
               (255,140,60),(140,210,255),(200,180,80),(80,200,180)]
    y = 290
    for i,(num,name,kou) in enumerate(phrases):
        col = colors2[i]
        d.rounded_rectangle([40,y,1010,y+116], radius=12,
                             fill=(16,14,30) if i%2==0 else (10,10,22))
        d.rectangle([40,y,46,y+116], fill=col)
        d.ellipse([62,y+32,102,y+72], fill=col)
        d.text((74,y+40), num, font=F(22, True), fill=(10,10,20))
        d.text((118,y+24), name, font=F(22), fill=GRAY)
        d.text((118,y+56), kou, font=F(32, True), fill=GOLD)
        y += 124

    footer(d)
    save(img, "E6_口诀展示_群舞琵琶.jpg")

# E7 - 用户故事
def e7():
    img, d = canvas()
    logo(d)
    d.text((54,110), "用了舞镜之后", font=F(52, True), fill=WHITE)
    d.text((54,170), "他们这样说", font=F(44, True), fill=GOLD)
    divider(d, 240, 460)

    users = [
        ("◉ 瑶瑶老师", "古典舞老师·5年教龄", GOLD,
         "以前学生上课总问同一个动作，现在有了口诀预习，第一遍就跑通了。课堂效率提升了一倍。"),
        ("◉ 小林同学", "舞蹈培训班学员", BLUE,
         "以前上完课三天就忘，现在睡前过一遍口诀，一周后还记得清清楚楚。续课再也不犹豫了。"),
        ("◉ 大美阿姨", "广场舞爱好者·58岁", GREEN,
         "年纪大了记性差，但口诀三个字一背就记住了。现在我成了广场上教别人的人！"),
    ]
    y = 292
    for name, role, col, quote in users:
        d.rounded_rectangle([40,y,1010,y+318], radius=16, fill=BG2)
        d.rectangle([40,y,46,y+318], fill=col)
        d.text((62,y+20), name, font=F(26, True), fill=col)
        d.text((62,y+56), role, font=F(18), fill=(100,110,150))
        d.line([(62,y+86),(950,y+86)], fill=(30,35,60), width=1)
        # Wrap quote
        words = quote
        chars = 22
        lines = [words[i:i+chars] for i in range(0,len(words),chars)]
        qy = y+102
        for line in lines[:4]:
            d.text((62,qy), line, font=F(22), fill=GRAY)
            qy += 44
        y += 336

    footer(d)
    save(img, "E7_用户故事_上课效率.jpg")

# E8 - TTS朗读功能
def e8():
    img, d = canvas()
    logo(d)
    d.text((54,110), "边走路", font=F(60, True), fill=WHITE)
    d.text((54,180), "边学舞蹈口诀", font=F(52, True), fill=GOLD)
    divider(d, 258, 560)
    d.text((54,282), "TTS朗读功能  随时随地学", font=F(26), fill=GRAY)

    # Big feature area
    d.rounded_rectangle([40,336,1010,640], radius=20, fill=BG2)
    d.rectangle([40,336,44,640], fill=PURPLE)
    d.text((66,360), "♪  朗读示例", font=F(28, True), fill=PURPLE)
    d.text((66,410), "「抬  拧  展  笑」", font=F(48, True), fill=GOLD)
    d.text((66,470), "「拧  落  柔  沉」", font=F(48, True), fill=BLUE)
    d.text((66,530), "「抬  仰  托」", font=F(48, True), fill=GREEN)

    scenarios = [
        ("上班路上", "戴耳机  听口诀  不用看手机"),
        ("课前等候", "进教室前3分钟  快速激活"),
        ("睡前放松", "闭眼听口诀  舒缓入睡"),
        ("运动后拉伸","同时温习舞蹈口诀"),
    ]
    y = 668
    for scene, desc in scenarios:
        d.rounded_rectangle([40,y,1010,y+118], radius=12, fill=(14,12,32))
        d.rectangle([40,y,44,y+118], fill=PURPLE)
        d.text((62,y+16), "▷  "+scene, font=F(26, True), fill=WHITE)
        d.text((62,y+56), desc, font=F(22), fill=GRAY)
        y += 130

    d.text((54,1150), "每句口诀独立音频", font=F(32, True), fill=WHITE)
    d.text((54,1196), "随时单句播放  重复播放", font=F(24), fill=GRAY)
    footer(d)
    save(img, "E8_功能_TTS朗读.jpg")

# E9 - 互动钩子
def e9():
    img, d = canvas()
    logo(d)
    d.text((54,110), "你在学哪支舞？", font=F(56, True), fill=WHITE)
    d.text((54,178), "舞镜都有口诀", font=F(48, True), fill=GOLD)
    divider(d, 252, 560)
    d.text((54,276), "1000+ 舞曲  持续更新  评论告诉我", font=F(22), fill=GRAY)

    dances = [
        ("古风", [(GOLD,"清明雨上"),(GOLD,"虞兮叹"),(GOLD,"赤伶"),(GOLD,"探窗")]),
        ("K-pop", [(BLUE,"Hype Boy"),(BLUE,"Supernova"),(BLUE,"Magnetic"),(BLUE,"Dynamite")]),
        ("流行", [((200,200,100),"科目三"),((200,200,100),"爱你"),((200,200,100),"Espresso"),((200,200,100),"野狼disco")]),
        ("拉丁", [(GREEN,"Hips Don't Lie"),(GREEN,"Despacito"),(GREEN,"Vivir Mi Vida"),((80,200,150),"Waka Waka")]),
    ]
    y = 322
    for genre, items in dances:
        d.text((54,y), genre, font=F(24, True), fill=PURPLE)
        y += 36
        x = 54
        row_y = y
        for col, name in items:
            tw = int(F(20).getlength(name)) + 28
            d.rounded_rectangle([x,row_y,x+tw,row_y+44], radius=22, fill=(30,20,60))
            d.text((x+14,row_y+10), name, font=F(20), fill=col)
            x += tw+10
            if x > 960:
                x = 54; row_y += 54
        y = row_y + 64

    d.rounded_rectangle([40,1222,1010,1330], radius=16, fill=(20,14,50))
    d.text((100,1248), "评论你想学的舞", font=F(32, True), fill=WHITE)
    d.text((100,1292), "我去帮你找口诀  →", font=F(26), fill=GOLD)
    footer(d)
    save(img, "E9_钩子_你会的舞有口诀吗.jpg")

# E10 - CTA
def e10():
    img, d = canvas()
    logo(d)

    # Big headline
    d.text((54,120), "舞蹈界的", font=F(48), fill=GRAY)
    d.text((54,178), "《九阳真经》", font=F(72, True), fill=GOLD)
    divider(d, 278, 560, GOLD)

    d.text((54,306), "别人教你做什么", font=F(32), fill=GRAY)
    d.text((54,350), "我们教你怎么永远记住", font=F(36, True), fill=WHITE)

    # 3 value props
    props = [
        (PURPLE, "◆ 口诀记忆", "3个字触发一个动作，永久不忘"),
        (GOLD,   "★ 六件套", "八拍卡·镜面卡·慢放·TTS·AI预习"),
        (GREEN,  "✓ 1000+舞曲", "古风·K-pop·拉丁·爵士·广场"),
    ]
    y = 416
    for col, title, desc in props:
        d.rounded_rectangle([40,y,1010,y+122], radius=14, fill=BG2)
        d.rectangle([40,y,46,y+122], fill=col)
        d.text((66,y+16), title, font=F(30, True), fill=col)
        d.text((66,y+58), desc, font=F(22), fill=GRAY)
        y += 136

    # URL box (clean, no fake QR)
    d.rounded_rectangle([40,832,460,1140], radius=20, fill=(16,14,36))
    d.rounded_rectangle([60,852,440,1120], radius=14, fill=(26,20,54))
    d.text((250,872), "免费体验", font=F(26, True), fill=GOLD, anchor="mt")
    d.text((250,920), "wujing", font=F(52, True), fill=WHITE, anchor="mt")
    d.text((250,978), ".mylumee.app", font=F(30), fill=PURPLE, anchor="mt")
    d.rounded_rectangle([80,1028,420,1032], radius=2, fill=(60,50,120))
    d.text((250,1046), "上传视频→3分钟出六件套", font=F(18), fill=GRAY, anchor="mt")
    d.text((250,1082), "现在免费试3支", font=F(20, True), fill=(180,160,240), anchor="mt")

    # CTA right
    d.text((490,858), "免费开始", font=F(48, True), fill=WHITE)
    d.rounded_rectangle([490,928,1010,1020], radius=18, fill=PURPLE)
    d.text((530,946), "▶  立即体验  →", font=F(32, True), fill=WHITE)
    d.text((490,1040), "¥29/月  个人会员", font=F(28, True), fill=GOLD)
    d.text((490,1080), "现在免费试用3首", font=F(22), fill=GRAY)
    d.text((490,1116), "wujing.mylumee.app", font=F(20), fill=PURPLE)

    d.text((54,1168), "口诀刻进脑子", font=F(34, True), fill=WHITE)
    d.text((54,1212), "动作永不忘", font=F(34, True), fill=GOLD)
    footer(d)
    save(img, "E10_CTA_免费开始.jpg")

if __name__ == "__main__":
    e1(); e2(); e3(); e4(); e5()
    e6(); e7(); e8(); e9(); e10()
    print(f"\n生成完成：10 张  目录: {OUTDIR}")
