# -*- coding: utf-8 -*-
"""图片核对页的服务端逻辑（配合 app.py 的 /review 路由，REVIEW_ENABLED=1 时启用）。

- candidates(bird): 从 GBIF/iNaturalist 检索该物种的候选图（摄影师/许可/原页/直链）。
- pick(bird, url): 把选定图下载压存为 static/img/birds/<原文件名>，并回写 CREDITS.json。
"""
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

from PIL import Image

from import_birds_from_xlsx import BASE, UA, get_json, gbif_match, license_score

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(ROOT, "public", "static", "img", "birds")
CREDITS = os.path.join(IMG_DIR, "CREDITS.json")


def size_url(ident):
    if "inaturalist-open-data.s3.amazonaws.com" in ident:
        return re.sub(r"/(original|large|medium|small|square)\.jpg$", "/large.jpg", ident)
    return ident


def _fetch_bytes(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1 + i)


def _save_jpg(data, out_path, max_w=800, quality=80):
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "P", "LA"):
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=quality, optimize=True)


def _media_list(key, limit=60):
    url = f"{BASE}/occurrence/search?speciesKey={key}&mediaType=StillImage&limit={limit}"
    try:
        d = get_json(url, tries=2)
    except Exception:
        return []
    out = []
    for o in d.get("results", []):
        for m in (o.get("media") or []):
            if m.get("type") != "StillImage":
                continue
            ident = (m.get("identifier") or "").strip()
            if not ident.startswith("http"):
                continue
            score = license_score(m.get("license"))
            if score == 0:
                continue
            if "inaturalist-open-data.s3.amazonaws.com" in urllib.parse.urlparse(ident).netloc:
                score += 1
            out.append((score, m))
    out.sort(key=lambda x: -x[0])
    return out


def candidates(bird, n=8):
    key = gbif_match(bird["latin"]).get("key")
    if not key:
        return []
    out = []
    for score, m in _media_list(key):
        ident = m.get("identifier") or ""
        if not ident.startswith("http"):
            continue
        out.append({
            "url": size_url(ident),
            "photographer": (m.get("creator") or "").strip() or "iNaturalist 用户",
            "license": m.get("license") or "",
            "page": m.get("references") or "",
            "score": score,
        })
        if len(out) >= n:
            break
    return out


def pick(bird, url, meta=None):
    """下载选定的图替换当前图片文件，回写 CREDITS。meta: {photographer, license, page}。"""
    meta = meta or {}
    data = _fetch_bytes(url)
    if not data:
        return (False, 0, "下载失败")
    filename = bird["image"].split("/")[-1]
    out_path = os.path.join(IMG_DIR, filename)
    try:
        _save_jpg(data, out_path)
    except Exception as e:
        return (False, 0, f"保存失败：{e}")
    size_kb = os.path.getsize(out_path) // 1024

    credits = {}
    if os.path.exists(CREDITS):
        try:
            credits = json.load(open(CREDITS, encoding="utf-8"))
        except Exception:
            credits = {}
    credits[bird["id"]] = {
        "name": bird["name"],
        "latin": bird["latin"],
        "photographer": meta.get("photographer") or "iNaturalist 用户",
        "license": meta.get("license") or "",
        "page": meta.get("page") or "",
        "direct": url,
        "status": "picked-manual",
    }
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)
    return (True, size_kb, "")

