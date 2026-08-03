# 舞镜落地页配套生图Prompt
生成日期：2026-08-03
用途：5套A/B/C/D/E落地页各3张，共15张
工具：ComfyUI + Stable Diffusion XL（RealVisXL_V5）
画面比例：9:16（竖版手机屏）

---

## 通用负向prompt（所有图共用）

```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

---

## 通用推荐参数

| 参数 | 值 |
|------|-----|
| Steps | 30–35 |
| CFG Scale | 7.0–7.5 |
| Sampler | DPM++ 2M Karras |
| Width × Height | 720 × 1280 |
| Clip Skip | 2 |

---

## Variant A：功能演示

### A1 — 封面图：舞者展示App界面

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer in traditional hanfu dance costume, holding a smartphone with a glowing UI card interface on screen, standing in a bright dance studio with wooden floors and mirror wall, soft warm natural light from large windows, elegant posture, looking at phone with focused expression, shallow depth of field, photorealistic, 85mm portrait lens, 8k detail
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 32 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 练舞不用一遍遍倒带了 📱
> 八拍一张卡，拿在手里跟着练
> 动作拆解清清楚楚，小白也能看懂
> → 舞镜AI舞蹈助手，免费领取

---

### A2 — 产品截图风：八拍卡特写

**正向prompt（英文）：**
```
Close-up of a smartphone screen displaying a clean dance tutorial card UI with Chinese text, eight-beat breakdown chart, beige warm gold background, soft studio lighting, phone resting on a light wood surface, minimal aesthetic, product photography style, sharp focus on screen, bokeh background, commercial photography, 8k
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 30 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 这才是学舞该有的工具🃏
> 每一拍是什么动作、用哪块肌肉
> 全部拆开给你看
> 舞镜八拍卡 → 练一遍顶三遍

---

### A3 — 场景图：舞者跟卡练习

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer in elegant silk dance costume, mid-movement practicing a dance pose in a mirrored dance studio, phone propped on barre showing a glowing card interface, she glances at phone while maintaining dance form, warm amber studio lights, motion captured in still frame, realistic photography, cinematic composition, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 33 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 边看边练，不用反复暂停▶️
> 把拆解卡立在镜子旁边
> 一个人练得比有老师还专注
> 试试舞镜，今天就能用

---

## Variant B：价格锚定

### B1 — 封面图：镜前AI分析

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer alone in a practice room, standing in front of a large mirror, her reflection visible, transparent AI motion analysis overlay lines projected on mirror glass highlighting joints and posture points in soft blue-gold, warm studio ambient light, confident expression, elegant hanfu-inspired dancewear, photorealistic, cinematic lighting, 9:16
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 34 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 镜子看不出问题，AI看得出 🪞
> 每个关节角度全都有数据
> 不用等老师，自己就能纠姿势
> 舞镜AI分析 ¥9.9解锁完整报告

---

### B2 — 产品截图风：价格界面特写

**正向prompt（英文）：**
```
Close-up of a smartphone screen showing a Chinese app interface with large bold text "¥9.9" price tag, dance tutorial breakdown card below, clean minimal UI design, warm cream and gold color palette, phone held in female hands with painted nails, soft bokeh background of a dance studio, sharp product photography, commercial shoot quality, 8k
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 30 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 一杯奶茶的价格💰
> 换来AI帮你逐拍拆解
> 练舞提速3倍不是吹的
> ¥9.9 → 立即解锁完整拆解

---

### B3 — 场景图：专业舞室氛围

**正向prompt（英文）：**
```
A bright professional dance studio with high ceilings, large mirror walls, wooden sprung floor, ballet barre, warm afternoon sunlight streaming through tall windows, a young Chinese female dancer in soft pose at barre, approachable and welcoming atmosphere, editorial photography style, shot with 35mm lens, warm tones, no harsh shadows, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 32 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 专业舞蹈教室的水平
> 在手机里就能实现 📲
> 动作分析·评分反馈·进度追踪
> 舞镜：你的随身AI舞蹈老师

---

## Variant C：限时免费

### C1 — 封面图：惊喜表情舞者

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer in traditional dance costume, holding a smartphone with a wide happy surprised smile, mouth slightly open in delight, eyes bright, standing in a warmly lit dance studio, natural joyful candid expression, warm golden hour light, shallow depth of field background bokeh, photorealistic portrait, 85mm lens, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 33 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 等等，这个是免费的？！🎁
> AI帮你拆解每一个动作
> 评分、节拍、技术分析全都有
> 限时免费领取 → 舞镜App

---

### C2 — 产品截图风：免费领取弹窗

**正向prompt（英文）：**
```
Close-up of smartphone screen showing a Chinese mobile app popup modal with text "免费领取" in large friendly font, below it a dance tutorial breakdown card with eight-beat notation, clean UI on warm off-white background, gold accent colors, phone on light marble surface with pink flower petals, soft natural light, crisp product photography, 8k
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 30 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 限时0元，点进来领 ⏰
> 舞镜AI拆解卡
> 24小时内有效，过期恢复原价
> 快转给也在学舞的闺蜜

---

### C3 — 场景图：倒计时紧迫感

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer in silk dance costume, holding an elegant hourglass in one hand and a glowing smartphone in the other, standing in a moonlit dance studio, dramatic chiaroscuro lighting with warm amber spotlight, sense of urgency and time passing, sand flowing through hourglass, photorealistic, cinematic mood, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 35 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 沙漏在转，机会不等人⌛
> 限时免费的舞镜拆解卡
> 今天不领，明天就没了
> → 现在点进来，0元解锁

---

## Variant D：数据结果

### D1 — 封面图：前后对比舞者

**正向prompt（英文）：**
```
Split composition showing the same 25-year-old Chinese female dancer twice: left side she stands uncertain and slouched in casual clothes, confused expression, dim grey light; right side she stands tall and confident in beautiful traditional dance costume, radiant smile, warm golden spotlight, elegant posture, dramatic transformation, cinematic diptych portrait, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 35 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 同一个人，练了30天的差距📊
> 不是天赋问题，是方法问题
> 舞镜AI每天给你精准反馈
> 看看她们是怎么进步的 →

---

### D2 — 产品截图风：评分进度条

**正向prompt（英文）：**
```
Close-up of smartphone screen displaying a dance performance analytics dashboard, showing a progress bar increasing from score 63 to score 82 with Chinese labels, clean data visualization UI, warm gold and cream color scheme, skill improvement chart, phone resting on light wood desk with a ballet shoe beside it, soft window light, sharp product photography, 8k detail
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 30 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 63分→82分，用了21天📈
> 不是瞎练，是有数据的练
> 舞镜AI评分每次都告诉你
> 哪里好了，哪里还差多少

---

### D3 — 场景图：查看AI评分报告

**正向prompt（英文）：**
```
A 25-year-old Chinese female dancer in traditional hanfu costume sitting on a barre bench, looking at her smartphone screen with a satisfied smile, phone screen glowing with a colorful AI performance report dashboard, warm dance studio background softly blurred, pride and accomplishment in her expression, candid natural light photography, 85mm lens, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 32 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 刷完视频第一反应：这分我能打？😄
> AI点评比老师还细
> 力道/节拍/手型 逐项评分
> 舞镜：让进步有迹可循

---

## Variant E：工具感/老师视角

### E1 — 封面图：老师查看班级报告

**正向prompt（英文）：**
```
A 30-year-old Chinese female dance teacher in elegant professional attire, holding a tablet showing a class performance report dashboard with multiple student scores and charts, standing in a large bright dance studio, authoritative yet warm expression, natural light, editorial portrait style, shallow depth of field, professional teacher aesthetic, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 33 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 带30个学生，每个人的进度
> 一个屏幕全看清楚了 📋
> 舞镜班级管理系统
> 老师省心，学生有数据

---

### E2 — 场景图：多手机俯拍

**正向prompt（英文）：**
```
Overhead flat lay shot of six smartphones arranged in a circle on a light wooden floor, each screen displaying a different personalized dance tutorial card with Chinese text and different student names, warm natural window light from above, elegant minimalist composition, female hands with dance bracelets visible reaching in from edges, commercial product photography, 8k detail, 9:16 vertical crop
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 30 / CFG 7.5 / DPM++ 2M Karras

**小红书配套文案：**
> 每个学生的拆解卡都不一样📱
> 根据她的动作问题定制的
> 不是模板，是真正的个性化
> 舞镜 × 舞蹈教室，合作咨询 →

---

### E3 — 场景图：课堂教学展示AI分析

**正向prompt（英文）：**
```
A 30-year-old Chinese female dance teacher standing in front of a class of four students in a bright dance studio, holding up a large tablet showing an AI motion analysis overlay of a dance pose, students watching attentively in practice clothes, warm natural studio lighting, educational atmosphere, reportage photography style, 35mm lens, authentic candid feel, 9:16 vertical
```

**负向prompt：**
```
cartoon, anime, illustration, painting, sketch, 3d render, watercolor, flat design, low quality, blurry, deformed, extra limbs, bad anatomy, text overlay, watermark, logo, ugly face, distorted, oversaturated, neon colors, western style, caucasian features
```

**参数：** Steps 32 / CFG 7.0 / DPM++ 2M Karras

**小红书配套文案：**
> 以前讲动作，靠嘴靠手比划
> 现在AI直接帮我把问题投影出来🎯
> 学生秒懂，课堂效率翻倍
> 舞镜进课堂，才是真提效

---

## 批量生成注意事项

1. **先跑A1验证风格**，确认光线/人物/色调对路再批量其他14张
2. **Seed锁定**：A系列用同一seed保证人物一致性（建议先跑A1，记录seed后A2/A3复用）
3. **D1特殊处理**：前后对比图需要分两次生成再拼接，左图seed固定确保同一人物
4. **B2/C2/D2**（UI截图风格）建议CFG调高至7.5-8.0，强化清晰度
5. **实际使用时**：App界面内容（八拍卡、¥9.9、评分数字）后期用PS/Figma叠加真实截图

---

*生成：舞镜CMO AI·2026-08-03*
