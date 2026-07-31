"""豆包 vision 评分：对比学员帧 vs 老师帧。关思考+压图 = 快(~5s)且便宜(~¥0.007/次)。
失败返回 None，调用方回退到像素对比，绝不打断主流程。"""
import os
import json
import base64
import urllib.request

try:
    import cv2
except Exception:
    cv2 = None

ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
EP = os.environ.get("ARK_VISION_EP", "ep-20260729155405-5l7dj")


def _resize_b64(path, max_w=360):
    """压到 max_w 宽再编码，省一半图片 token。"""
    if cv2 is not None:
        img = cv2.imread(path)
        if img is not None:
            h, w = img.shape[:2]
            if w > max_w:
                img = cv2.resize(img, (max_w, int(h * max_w / w)))
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def score_pair(student_path, teacher_path, name=""):
    """返回 (score_0_100:int, problem:str, good:str)。失败返回 None。"""
    key = os.environ.get("ARK_API_KEY")
    if not key:
        return None
    prompt = (
        "第一张=学员，第二张=老师参考。对比舞蹈动作(身体角度/手臂/重心/脚步/头位)，"
        "只输出JSON不要解释："
        '{"score":整数0-100,"problem":"最主要的一个差异，一句话","good":"做得好的一点，一句话"}'
    )
    body = {
        "model": EP,
        "thinking": {"type": "disabled"},
        "max_output_tokens": 200,
        "input": [{"role": "user", "content": [
            {"type": "input_image", "image_url": _resize_b64(student_path)},
            {"type": "input_image", "image_url": _resize_b64(teacher_path)},
            {"type": "input_text", "text": prompt},
        ]}],
    }
    try:
        req = urllib.request.Request(
            ARK_URL, data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        r = json.loads(urllib.request.urlopen(req, timeout=40).read())
        out = "".join(
            c.get("text", "")
            for o in r.get("output", []) if o.get("type") == "message"
            for c in o.get("content", [])
        ).strip()
        if out.startswith("```"):
            parts = out.split("```")
            if len(parts) >= 2:
                out = parts[1]
            if out.lstrip().lower().startswith("json"):
                out = out.lstrip()[4:]
        d = json.loads(out.strip())
        sc = int(d.get("score", 0))
        return max(0, min(100, sc)), str(d.get("problem", "")), str(d.get("good", ""))
    except Exception:
        return None
