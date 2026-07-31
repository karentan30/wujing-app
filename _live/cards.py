"""三张卡生成：八拍卡 / 故事卡 / 记忆卡。用 DeepSeek(纯文字, 便宜)。
成本≈¥0.002/次。不碰火山。"""
import os
import json
import urllib.request

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _chat(prompt, max_tokens=1500, temperature=0.7):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return resp["choices"][0]["message"]["content"]


def _strip_fences(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    return raw.strip()


def generate_cards(breakdown, score=None):
    """从老师分段拆解生成三张卡。失败时返回带 error 的兜底，绝不抛异常打断主流程。"""
    try:
        phrases = breakdown.get("phrases", []) or []
        title = breakdown.get("title", "这支舞")
        lines = []
        for p in phrases:
            lines.append(
                "{i}.{name}｜动作:{action}｜脚:{feet}｜意境:{intent}｜口诀:{kou}".format(
                    i=p.get("i", ""), name=p.get("name", ""),
                    action=p.get("action", ""), feet=p.get("feet", ""),
                    intent=p.get("intent", ""), kou=p.get("kou", ""),
                )
            )
        ctx = "\n".join(lines) if lines else "（无详细分段，按通用舞蹈处理）"
        score_hint = f"学员本次评分约{score}分。" if score else ""
        prompt = (
            f"你是资深舞蹈老师，温柔专业。下面是《{title}》的分段拆解：\n{ctx}\n\n"
            f"{score_hint}请生成三张卡片帮学员记住并跳好这支舞。"
            "只输出严格JSON(不要markdown代码块、不要多余解释)，格式：\n"
            "{\n"
            ' "eight_beat":[{"beat":"第X个八拍","name":"段名","move":"一句话动作要点","tip":"发力/口诀提示"}],\n'
            ' "story":{"title":"故事标题","body":"120字以内的情感叙事，帮舞者跳出感觉和眼神"},\n'
            ' "memory":{"title":"记忆口诀","chain":"把整支舞串成一句好记的联想口诀","tips":["3条记忆技巧"]}\n'
            "}"
        )
        raw = _chat(prompt)
        data = json.loads(_strip_fences(raw))
        # 兜底字段
        data.setdefault("eight_beat", [])
        data.setdefault("story", {"title": "", "body": ""})
        data.setdefault("memory", {"title": "", "chain": "", "tips": []})
        return data
    except Exception as e:
        return {
            "eight_beat": [],
            "story": {"title": "", "body": ""},
            "memory": {"title": "", "chain": "", "tips": []},
            "error": str(e)[:200],
        }


_KB_CACHE = None


def _load_kb():
    global _KB_CACHE
    if _KB_CACHE is None:
        try:
            with open(os.path.join(os.path.dirname(__file__), "data", "dance_kb.json")) as f:
                _KB_CACHE = json.load(f)
        except Exception:
            _KB_CACHE = {}
    return _KB_CACHE


def _kb_hint(text):
    """从问题文本里匹配舞蹈术语，带上标准要点/纠正，让点评更专业。只注入命中的，省token。"""
    kb = _load_kb()
    if not isinstance(kb, dict):
        return ""
    hits = []
    for term, info in kb.items():
        if term in text and isinstance(info, dict):
            key = info.get("要点") or info.get("纠正") or ""
            if key:
                hits.append(f"【{term}】{key}")
        if len(hits) >= 4:
            break
    return ("\n专业术语参考(可引用)：\n" + "\n".join(hits)) if hits else ""


def generate_coach_note(score, problems, title="这支舞"):
    """老师给学员的评分指导：一段温柔专业点评 + 3条针对性建议。DeepSeek, ≈¥0.002。"""
    try:
        probs = []
        for p in (problems or [])[:5]:
            t = p.get("problem") or p.get("detail") or ""
            if t:
                probs.append("- " + t)
        probs_txt = "\n".join(probs) if probs else "（无明显问题，整体到位）"
        kb_hint = _kb_hint(probs_txt + title)
        prompt = (
            f"你是温柔专业的舞蹈老师。学员跳《{title}》得分 {score} 分。"
            f"发现的主要问题：\n{probs_txt}\n{kb_hint}\n\n"
            "请像老师当面点评一样，先肯定再指出问题、给方向，不打击。"
            "只输出严格JSON(不要markdown)："
            '{"comment":"80字以内的整体点评，温暖真诚","tips":["3条针对上面问题的具体可练的指导"]}'
        )
        raw = _chat(prompt, max_tokens=600)
        data = json.loads(_strip_fences(raw))
        data.setdefault("comment", "")
        data.setdefault("tips", [])
        return data
    except Exception as e:
        return {"comment": "", "tips": [], "error": str(e)[:200]}
