# 舞镜 · 首条封面 Prompt（ComfyUI · RealVisXL_V5）

> 封面用于小红书图文版首图 + 抖音视频封面。取「真人 + 金色测量线 + 角度数字」的量化测量视觉，直打护城河。
> ⚠️ 只列 prompt，**不生图**。等 Karen 确认后本机跑（铁律 image-prompt-first）。
> 跑法（对齐 `营销发放包-0730/小红书卡片方案.md`）：`cd ~/ComfyUI && venv/bin/python main.py --port 8188` → RealVisXL_V5 → 竖版 832×1216（放大 1080×1440）→ steps 30 / cfg 5 / DPM++ 2M Karras。文字用 HTML/PIL 叠加，生图只出底图人物。
> 人物必填 6 项 vs 本 prompt：年龄=22 ✅  /  Chinese=✅ / 发型=低发髻 ✅ / 情绪=笃定 ✅ / 风格=写实古典舞 ✅ / 负面词=✅

---

## 封面 · 量化测量·打脸型（主推）

**成图叠加文案（用 HTML/PIL，非生图）：**
- 顶部小标签「AI 量给你看」（金底黑字）
- 右侧红金半透明标注框：「左肘 68° → 该 170°」
- 底部大标题（衬线 Noto Serif SC，金高亮"量"字）：「别人说你不到位，舞镜量给你看」

**ComfyUI prompt：**

```text
positive: RAW photo, masterpiece, best quality, ultra detailed, photorealistic, a beautiful young Chinese woman classical dancer, 22 years old, natural authentic East Asian face, delicate features, long straight black hair in a neat low bun, focused confident serene expression, looking to the side, elegant classical Chinese dance pose with one arm gracefully extended and one hand raised in a poised gesture, detailed hands, five fingers, slender elegant fingers, wearing flowing beige silk hanfu dance costume, warm cream studio backdrop with a subtle faint golden angular measurement line motif on the right side, soft warm cream key light, cinematic lighting, three-quarter body shot, 85mm portrait lens, shallow depth of field, f2.0, professional photography, natural skin texture, subsurface scattering, graceful poised posture, film grain

negative: cartoon, anime, illustration, painting, 3d render, cgi, doll, plastic skin, airbrushed, deformed hands, malformed hands, mutated hands, fused fingers, extra fingers, missing fingers, too many fingers, six fingers, bad hands, poorly drawn hands, extra limbs, extra arms, missing limbs, floating limbs, disconnected limbs, twisted body, bad anatomy, deformed face, poorly drawn face, cloned face, asymmetric eyes, cross-eyed, long neck, distorted proportions, blurry, lowres, jpeg artifacts, grainy, watermark, signature, text, logo, oversaturated, western face, caucasian, heavy makeup, ugly, disfigured
```

---

## 备选 · 进步弧线型（配「改前→改后」文案）

**叠加文案：** 底部「左肘 改前 68° → 改后 170°」，顶部「AI 量你一周的进步」

```text
positive: RAW photo, masterpiece, best quality, ultra detailed, photorealistic, a beautiful young Chinese woman dancer, 24 years old, natural authentic East Asian face, shoulder-length straight black hair, determined hopeful encouraging expression, graceful confident dance pose mid-movement with both arms elegantly lifted, detailed hands, five fingers, wearing a soft cream and gold dance practice outfit, bright warm off-white gym or studio background, warm natural key light, cinematic lighting, three-quarter body shot, 50mm lens, shallow depth of field, professional photography, natural skin texture, sense of progress and energy, film grain

negative: cartoon, anime, illustration, painting, 3d render, cgi, doll, plastic skin, airbrushed, motion blur, deformed hands, malformed hands, mutated hands, fused fingers, extra fingers, missing fingers, too many fingers, six fingers, bad hands, poorly drawn hands, extra limbs, extra arms, missing limbs, floating limbs, disconnected limbs, twisted body, bad anatomy, deformed face, poorly drawn face, cloned face, asymmetric eyes, cross-eyed, long neck, distorted proportions, blurry, lowres, jpeg artifacts, grainy, watermark, signature, text, logo, oversaturated, western face, caucasian, ugly, disfigured
```

---

## 自评
主推 8.5/10（人物必填 6 项齐全、风格贴合产品浅米金 UI、直打测量护城河）；扣分=测量线文字由 HTML 叠加、非生图直出，需 Karen 确认叠加排版。备选 8/10。
