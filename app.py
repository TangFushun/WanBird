# -*- coding: utf-8 -*-
"""
懂鸟动物识别 API —— Flask 代理服务
====================================
网页后端：隐藏 API key，转发识别请求。
- 前端上传鸟图 → POST /classify → Flask 调懂鸟 API（上传→轮询→百科）→ 返回 JSON。
- 未设置 DONGNIAO_API_KEY 时走 mock（假数据），用于调试 UI，不消耗免费额度。

运行：
    pip install flask requests python-dotenv
    python app.py
然后浏览器打开 http://127.0.0.1:5000
设置 DONGNIAO_API_KEY 后自动切换为真实识别。
"""
import os
import re
import time
import socket
import json

import requests
from flask import Flask, jsonify, request, render_template

try:
    from dotenv import load_dotenv
    load_dotenv()  # 从项目根目录的 .env 读取
except ImportError:
    pass

app = Flask(__name__)

# 懂鸟 API
DONGNIAO_BASE = "https://ai.open.hhodata.com/api/v2"
DONGNIAO_DONGNIAO = f"{DONGNIAO_BASE}/dongniao"

# 图片大小限制（懂鸟要求不超过 2MB）
MAX_IMAGE_BYTES = 2 * 1024 * 1024

# 轮询识别结果的参数（秒）
POLL_INTERVAL = 1.5
POLL_TIMEOUT = 30


# ---------------------------------------------------------------------------
# 静态数据：鸟类图鉴 / 短剧（data/*.json）
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

IUCN_CN = {
    "EX": "已灭绝", "EW": "野外灭绝", "CR": "极危", "EN": "濒危",
    "VU": "易危", "NT": "近危", "LC": "无危", "DD": "数据缺乏", "NE": "未评估",
}


def _load_json(name: str, default):
    """从 data/ 目录读取 JSON，失败时回落到 default 并打印警告。"""
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[警告] 无法加载 {path}：{exc}")
        return default


BIRDS = _load_json("birds.json", [])
DRAMAS = _load_json("dramas.json", [])

# 图片核对页开关：只在本地/测试时开，公网部署默认关闭
REVIEW_ENABLED = os.environ.get("REVIEW_ENABLED", "0") == "1"


def real_mode() -> bool:
    """是否处于真实识别模式（配置了 API key）。"""
    return bool(os.environ.get("DONGNIAO_API_KEY", "").strip())


# ---------------------------------------------------------------------------
# 懂鸟 API 调用
# ---------------------------------------------------------------------------
def _post_dongniao(form: dict, files: dict = None):
    """向懂鸟 /dongniao 发一次请求。key 放在 header（或同名表单字段），二选一。"""
    headers = {"api_key": os.environ["DONGNIAO_API_KEY"].strip()}
    return requests.post(DONGNIAO_DONGNIAO, headers=headers, data=form,
                         files=files, timeout=30)


def upload_image(image_bytes: bytes) -> str:
    """上传图片，返回 resultid（任务受理时返回的字符串）。"""
    resp = _post_dongniao(
        form={"upload": "1", "class": "B"},
        files={"image": ("bird.jpg", image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    code, payload = resp.json()
    if code == 1000 and isinstance(payload, str):
        return payload  # resultid，例如 "HH-B_2026..."
    raise RuntimeError(f"图片上传失败：[{code}] {payload}")


def poll_result(resultid: str):
    """轮询识别结果，直到完成返回解析出的 [(confidence, name, animalid, cls), ...] 列表。
    未识别到动物返回空列表。超时抛异常。"""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        resp = _post_dongniao(form={"resultid": resultid})
        resp.raise_for_status()
        code, payload = resp.json()
        if code == 1001:  # 处理中，稍后重试
            time.sleep(POLL_INTERVAL)
            continue
        if code in (1010, 1008):  # 未识别到动物 / 未检测到动物框：都按无结果处理，给友好提示
            return []
        if code == 1000 and isinstance(payload, list):
            # payload: [[{"box":[...], "list":[["置信度%","名|英文|学名","animalid","类别"], ...]}, ...]]
            candidates = []
            for obj in _flatten(payload):
                for item in obj.get("list", []):
                    if len(item) >= 3:
                        try:
                            confidence = float(item[0])
                        except (TypeError, ValueError):
                            confidence = 0.0
                        candidates.append({
                            "confidence": confidence,
                            "name": item[1],
                            "animalid": item[2],
                            "cls": item[3] if len(item) > 3 else "B",
                            "box": obj.get("box"),  # [x,y,w,h] 相对原图像素
                        })
            candidates.sort(key=lambda c: c["confidence"], reverse=True)
            return candidates
        # 其它状态码，视为失败
        raise RuntimeError(f"识别结果异常：[{code}] {payload}")
    raise TimeoutError("识别超时，请稍后重试")


def fetch_encyclopedia(animalid: str, cls: str = "B") -> dict:
    """获取百科资料，返回结构化档案 dict。失败时返回空档案，不阻断主流程。"""
    try:
        resp = _post_dongniao(form={"animalid": animalid, "class": cls})
        resp.raise_for_status()
        code, payload = resp.json()
        if code == 1000:
            return _build_profile(payload)
    except Exception:
        pass
    return _empty_profile()


def _flatten(payload: list):
    """payload 内层可能是嵌套列表，递归展开出含 box 的字典。"""
    out = []
    for item in payload or []:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, list):
            out.extend(_flatten(item))
    return out


# 百科资料字段名未经官方文档明确列出，这里按「关键词模糊匹配」提取：
# 先把 payload 摊平成 {键: 文本}，再用一组候选关键词去命中键名或小节标题。
# 这样无论懂鸟返回的是结构化字段（taxonomy/order/family…）还是中文分节正文都能兼容。

# 每个档案板块：输出键 → 用于匹配的候选关键词（小写，按优先级）
SECTION_KEYS = {
    "summary":      ["summary", "description", "intro", "overview", "概述", "综述", "简介", "百科", "content"],
    "appearance":   ["appearance", "feature", "morpholog", "外形", "形态", "特征"],
    "identification": ["identify", "identification", "difference", "区别", "辨识", "鉴别"],
    "call":         ["call", "vocal", "voice", "song", "鸣叫", "鸣声", "叫声"],
    "distribution": ["distribution", "range", "geograph", "地理分布", "分布"],
    "habitat":      ["habitat", "栖息地", "栖息环境", "栖息", "生境", "habitats"],
    "habits":       ["habit", "behavio", "behaviour", "ecology", "习性", "生态", "行为"],
    "breeding":     ["breeding", "reproduc", "nest", "繁殖", "生长", "育雏"],
    "conservation": ["conservation", "protection", "status", "iucn", "保护", "现状", "濒危"],
}

# 显示用的中文标签
SECTION_LABELS = {
    "summary": "综述",
    "appearance": "外形特征",
    "identification": "区别辨识",
    "call": "鸣叫特征",
    "distribution": "地理分布",
    "habitat": "栖息环境",
    "habits": "生活习性",
    "breeding": "生长繁殖",
    "conservation": "保护现状",
}

# 分类阶元：输出键 → 候选关键词（纲目科属等）
RANK_KEYS = {
    "class":  ["class", "classname", "纲"],
    "order":  ["order", "ordername", "目"],
    "family": ["family", "familyname", "科"],
    "genus":  ["genus", "genusname", "属"],
}


def _empty_profile() -> dict:
    """空档案：字段缺失时前端按「暂无」展示。"""
    return {
        "summary": "",
        "sections": [],   # [{label, text}, ...] 有内容的分节
        "taxonomy": [],   # [{rank, cn, latin}, ...] 纲→目→科→属
        "iucn": "",       # 如 "LC" / "无危"
        "english": "",    # 英文名
        "aliases": [],    # 俗名/别名
    }


def _flatten_texts(payload, prefix: str = ""):
    """把嵌套的百科 payload 摊平成 [(完整键路径, 文本), ...]，便于关键词匹配。"""
    out = []
    if isinstance(payload, str):
        if payload.strip():
            out.append((prefix, payload.strip()))
    elif isinstance(payload, dict):
        for k, v in payload.items():
            out.extend(_flatten_texts(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            out.extend(_flatten_texts(v, f"{prefix}.{i}" if prefix else str(i)))
    return out


def _first_match(items, keywords):
    """在 [(键, 文本)] 中返回第一个「键名包含任一关键词」的文本。
    无键名（裸字符串 payload）的条目不参与关键词匹配，只由兜底逻辑处理。"""
    for key, text in items:
        if not key:
            continue
        low = key.lower()
        if any(kw in low for kw in keywords):
            return text
    return ""


def _looks_like_taxonomy(text: str) -> bool:
    """识别「鸟纲Aves › 雀形目PASSERIFORMES › 鹟科Muscicapidae › 红尾鸲属Phoenicurus」式分类串。"""
    return ("›" in text or ">" in text) and ("纲" in text or "目" in text or "科" in text or "属" in text)


def _parse_taxonomy(text: str):
    """把分类串拆成 [{rank, cn, latin}]。中英混排如「鹟科Muscicapidae」拆为中/拉丁两段。"""
    parts = [p.strip() for p in re.split(r"[›>]", text) if p.strip()]
    ranks = []
    for part in parts:
        # 中文名 + 拉丁名（拉丁名以大写字母开头）
        m = re.match(r"^(.*?[\u4e00-\u9fff])\s*([A-Z][A-Za-z]+)?$", part)
        if m:
            cn = (m.group(1) or "").strip()
            latin = (m.group(2) or "").strip()
        else:
            cn, latin = part, ""
        # 从中文名里推阶元（鸟纲→纲）
        rank = ""
        for suffix in ("纲", "目", "科", "属", "种"):
            if cn.endswith(suffix):
                rank = suffix
                break
        if cn:
            ranks.append({"rank": rank, "cn": cn, "latin": latin})
    return ranks


def _build_profile(payload) -> dict:
    """把百科 payload 整理成结构化物种档案。拿不到就留空，绝不抛异常阻断识别主流程。"""
    profile = _empty_profile()
    try:
        items = _flatten_texts(payload)
        if not items:
            return profile

        # ---- 1. 各分节正文 ----
        # 同一个文本只归入一个板块（避免 summary/description 互为别名时重复展示）
        used_texts = set()
        for out_key, keywords in SECTION_KEYS.items():
            text = _first_match(items, keywords)
            # 过滤噪声短文本与已用过的文本
            if text and len(text) > 8 and text not in used_texts:
                # 小节标题（如「地理分布」）本身就是键名时，文本需更长才算正文
                profile["sections"].append({
                    "key": out_key,
                    "label": SECTION_LABELS[out_key],
                    "text": text,
                })
                used_texts.add(text)

        # 综述优先取 summary；没有则用第一段正文兜底
        if profile["sections"]:
            profile["summary"] = profile["sections"][0]["text"]
        else:
            # 完全没有命中关键词：取最长的一段文本作为综述
            texts = sorted((t for _, t in items), key=len, reverse=True)
            if texts:
                profile["summary"] = texts[0]

        # ---- 2. 分类阶元（纲目科属）----
        # 优先找一次给全的分类串
        for _, text in items:
            if _looks_like_taxonomy(text):
                profile["taxonomy"] = _parse_taxonomy(text)
                if profile["taxonomy"]:
                    break
        if not profile["taxonomy"]:
            # 退而求其次：逐个阶元字段单独取
            for rank, keywords in RANK_KEYS.items():
                text = ""
                for key, val in items:
                    if not key:
                        continue
                    low = key.lower()
                    # 中文单字阶元（纲/目/科/属）要求键名以其结尾，避免命中「目录」「本科」
                    if any((low.endswith(kw) if len(kw) == 1 else kw in low) for kw in keywords):
                        text = val
                        break
                if text and len(text) < 40:
                    m = re.match(r"^(.*?[\u4e00-\u9fff])\s*([A-Z][A-Za-z]+)?$", text.strip())
                    cn = (m.group(1) if m else text).strip()
                    latin = (m.group(2) if m else "") or ""
                    if cn:
                        profile["taxonomy"].append({"rank": rank, "cn": cn, "latin": latin})

        # ---- 3. IUCN 保护等级 ----
        iucn = _first_match(items, ["iucn", "红色名录", "保护等级", "protection_level"])
        if iucn:
            m = re.search(r"\b(EX|EW|CR|EN|VU|NT|LC|DD|NE)\b", iucn.upper())
            profile["iucn"] = m.group(1) if m else iucn.strip()[:12]
        else:
            # 没有独立字段时，从「保护现状」小节正文里捞出等级代码
            for s in profile["sections"]:
                if s["key"] == "conservation":
                    m = re.search(r"\b(EX|EW|CR|EN|VU|NT|LC|DD|NE)\b", s["text"].upper())
                    if m:
                        profile["iucn"] = m.group(1)
                    break

        # ---- 4. 英文名 / 俗名 ----
        profile["english"] = _first_match(items, ["english", "en_name", "英文名", "英文"])
        if len(profile["english"]) > 60:
            profile["english"] = ""
        alias = _first_match(items, ["alias", "synonym", "俗名", "别名", "别称", "亦称"])
        if alias:
            profile["aliases"] = [a.strip() for a in re.split(r"[、,，;；/]", alias) if a.strip()][:6]
    except Exception:
        # 任何解析异常都退回已拿到的部分，不影响识别结果
        pass
    return profile


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", active="index")


@app.route("/guide")
def guide():
    """鸟类图鉴首页：搜索/筛选的物种卡片网格。"""
    return render_template("guide.html", active="guide",
                           birds_json=json.dumps(BIRDS, ensure_ascii=False))


@app.route("/guide/<bird_id>")
def bird(bird_id):
    """单个鸟种的详情档案页，附前后种切换。"""
    idx = next((i for i, b in enumerate(BIRDS) if b.get("id") == bird_id), None)
    if idx is None:
        return "未找到该鸟种", 404
    bird = BIRDS[idx]
    prev_bird = BIRDS[idx - 1] if idx > 0 else None
    next_bird = BIRDS[idx + 1] if idx + 1 < len(BIRDS) else None
    return render_template(
        "bird.html", active="guide", bird=bird,
        prev=prev_bird, next=next_bird, IUCN_CN=IUCN_CN,
        bird_json=json.dumps(bird, ensure_ascii=False),
    )


@app.route("/drama")
def drama():
    """鸟类短剧频道：剧集列表 + 播放器。"""
    return render_template("drama.html", active="drama",
                           dramas_json=json.dumps(DRAMAS, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 图片核对页（REVIEW_ENABLED=1 时可用）：候选图点选替换，降低人工核对成本
# ---------------------------------------------------------------------------
# 学名匹配偏弱、图片身份需重点人工确认的物种（其余 iNaturalist 图也建议抽查）
_SUSPECT_NAMES = {"霍氏蛙口夜鹰", "斑胁田鸡", "黑嘴鸥", "黑鹰",
                  "栗腹八色鸫", "栗背短脚鹛", "灰头噪鹛"}


def _review_flags():
    """返回 (suspect_ids, small_ids)：存疑种与低质小图种的 id 集合。"""
    import os as _os
    imgdir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "static", "img", "birds")
    id_by_name = {b.get("name"): b.get("id") for b in BIRDS}
    suspect = {id_by_name[n] for n in _SUSPECT_NAMES if n in id_by_name}
    small = set()
    for b in BIRDS:
        fn = (b.get("image") or "").split("/")[-1]
        path = _os.path.join(imgdir, fn)
        if b.get("id") in suspect:
            continue  # 存疑优先，不重复标记
        if fn.endswith(".jpg") and _os.path.exists(path) and _os.path.getsize(path) < 20 * 1024:
            small.add(b.get("id"))
    return sorted(suspect), sorted(small)


@app.route("/review")
def review_page():
    if not REVIEW_ENABLED:
        return "图片核对页未启用：设置环境变量 REVIEW_ENABLED=1 后重启可用。", 404
    suspect, small = _review_flags()
    return render_template("review.html", active=None,
                           birds_json=json.dumps(BIRDS, ensure_ascii=False),
                           suspect_json=json.dumps(suspect),
                           small_json=json.dumps(small))


@app.route("/review/candidates/<bird_id>")
def review_candidates(bird_id):
    if not REVIEW_ENABLED:
        return jsonify({"error": "未启用"}), 404
    bird = next((b for b in BIRDS if b.get("id") == bird_id), None)
    if not bird:
        return jsonify({"error": "未找到该鸟"}), 404
    try:
        import photo_review as phrv
        return jsonify({"candidates": phrv.candidates(bird), "current": bird.get("image")})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/review/pick/<bird_id>", methods=["POST"])
def review_pick(bird_id):
    if not REVIEW_ENABLED:
        return jsonify({"error": "未启用"}), 404
    bird = next((b for b in BIRDS if b.get("id") == bird_id), None)
    if not bird:
        return jsonify({"error": "未找到该鸟"}), 404
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    if not url.startswith("http"):
        return jsonify({"error": "非法链接"}), 400
    meta = {"photographer": d.get("photographer", ""), "license": d.get("license", ""),
            "page": d.get("page", "")}
    try:
        import photo_review as phrv
        ok, kb, err = phrv.pick(bird, url, meta)
        return jsonify({"ok": ok, "size_kb": kb, "error": err})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/classify", methods=["POST"])
def classify():
    image = request.files.get("image")
    if not image:
        return jsonify({"error": "未收到图片文件"}), 400

    data = image.read()
    if len(data) == 0:
        return jsonify({"error": "图片内容为空"}), 400
    if len(data) > MAX_IMAGE_BYTES:
        return jsonify({"error": "图片不能超过 2MB"}), 400

    if not real_mode():
        # ---------- mock 模式 ----------
        return jsonify({
            "source": "mock",
            "species": "北红尾鸲",
            "latin": "Phoenicurus auroreus",
            "confidence": 0.97,
            # 演示检测框：0-1 相对值（居中占约 60%），前端按显示区相对处理
            "box": [0.22, 0.2, 0.56, 0.6],
            "description": (
                "这是演示数据（未配置懂鸟 API key）。北红尾鸲是一种常见的小型鸣禽，"
                "雄鸟头顶至背为蓝灰色，腹部橙红色，常栖息于林缘与城市绿地。"
            ),
            # 演示档案：字段与真实模式一致，便于未配置 key 时也能查看完整版面
            "profile": {
                "summary": (
                    "北红尾鸲（英文名：Daurian Redstart，学名：Phoenicurus auroreus），"
                    "是雀形目鹟科红尾鸲属的鸟类。分布于亚洲温带地区的开阔空间，"
                    "如开放森林边缘、灌木丛、茶园、公园和人类居住地附近。"
                ),
                "english": "Daurian Redstart",
                "aliases": ["灰顶茶鸲", "红尾溜"],
                "iucn": "LC",
                "taxonomy": [
                    {"rank": "纲", "cn": "鸟纲", "latin": "Aves"},
                    {"rank": "目", "cn": "雀形目", "latin": "PASSERIFORMES"},
                    {"rank": "科", "cn": "鹟科", "latin": "Muscicapidae"},
                    {"rank": "属", "cn": "红尾鸲属", "latin": "Phoenicurus"},
                ],
                "sections": [
                    {"key": "habitat", "label": "栖息环境",
                     "text": "栖息于稀疏的亚高山林、河岸灌丛、次生林、灌木丛、开阔地、"
                             "靠近人类住区的区域、花园和公园。活动于海拔 2800-3700 米之间，"
                             "冬季降至海平面至 2000 米。"},
                    {"key": "distribution", "label": "地理分布",
                     "text": "繁殖区包括中国中部与东部、俄罗斯东南部、蒙古东北部和韩国；"
                             "非繁殖区覆盖中国南部、印度东北部，迁徙至日本、中国东南沿海、"
                             "台湾及东南亚部分地区过冬。"},
                    {"key": "habits", "label": "生活习性",
                     "text": "迁徙物种。常在灌丛与地面间短距离跳跃觅食，主食昆虫及少量浆果；"
                             "雄鸟常在高枝鸣唱并抖动橙红色尾羽。"},
                ],
            },
        })

    # ---------- 真实模式 ----------
    try:
        resultid = upload_image(data)
        candidates = poll_result(resultid)
    except Exception as exc:
        return jsonify({"error": f"识别失败：{exc}"}), 502

    if not candidates:
        return jsonify({
            "source": "real",
            "species": "未识别到动物",
            "latin": "",
            "confidence": 0,
            "box": None,
            "description": "图片中没有检测到可识别的动物，请换一张更清晰的鸟图试试。",
            "profile": _empty_profile(),
        })

    top = candidates[0]
    # 解析 "中文名|英文|学名"，取第一段作中文名，最后一段作学名
    parts = top["name"].split("|")
    cn_name = parts[0].strip() if parts else top["name"]
    latin = parts[-1].strip() if len(parts) > 1 else ""
    profile = fetch_encyclopedia(top["animalid"], top.get("cls", "B"))
    description = profile.get("summary") or "（本物种暂无百科简介）"

    return jsonify({
        "source": "real",
        "species": cn_name,
        "latin": latin,
        "confidence": round(top["confidence"] / 100.0, 3),  # API 给的是百分比
        "box": top.get("box"),
        "description": description,
        "profile": profile,
        # Top-5 候选，供前端展示备选鸟种
        "candidates": [
            {
                "name": c["name"].split("|")[0].strip(),
                "latin": (c["name"].split("|")[-1].strip() if "|" in c["name"] else ""),
                "confidence": round(c["confidence"] / 100.0, 3),
            }
            for c in candidates[:5]
        ],
    })


@app.route("/mode")
def mode():
    """给前端查询当前是 mock 还是真实模式。"""
    return jsonify({"real": real_mode()})


def _is_port_free(port: int) -> bool:
    """检查端口是否可绑定。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int) -> int:
    """优先用 preferred；若被占用则探测到下一个空闲端口。
    避免旧的残留 Flask 进程占用默认端口时，新进程悄悄连到旧实例（加载旧配置）造成困惑。"""
    if _is_port_free(preferred):
        return preferred
    for port in range(preferred + 1, preferred + 200):
        if _is_port_free(port):
            print(f"[提示] 端口 {preferred} 被占用，改用空闲端口 {port}。"
                  f"请用浏览器打开 http://127.0.0.1:{port}")
            return port
    return preferred


if __name__ == "__main__":
    preferred = int(os.environ.get("PORT", "5000"))
    port = _pick_port(preferred)
    # 默认只监听本机（安全）；要分享给局域网/公网的人看时，用 HOST=0.0.0.0 启动。
    host = os.environ.get("HOST", "127.0.0.1")
    # 仅本机调试开 debug；对外时自动关闭，避免泄露堆栈。
    debug = os.environ.get("DEBUG", "1" if host == "127.0.0.1" else "0") == "1"
    print("当前模式：" + ("真实识别(懂鸟 API)" if real_mode() else "演示(mock)，配置 DONGNIAO_API_KEY 后重启切换为真实识别"))
    print(f"监听地址：http://{host}:{port}  （分享外部访问请用 HOST=0.0.0.0 启动）")
    # debug 模式会启用文件监听自动重载，但对 Windows 下残留进程不友好；
    # 这里关闭 reloader，避免多进程/持久占端口，也保证 .env 改动重启即生效。
    app.run(host=host, port=port, debug=debug, use_reloader=False)

