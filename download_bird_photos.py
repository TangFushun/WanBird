# -*- coding: utf-8 -*-
"""为图鉴里的鸟自动配真实照片：从 GBIF（iNaturalist 开放数据）检索授权图片，
下载压成 static/img/birds/<id>.jpg，并把摄影师/许可记录到 CREDITS.json。
用法：python download_bird_photos.py            # 为现有全部鸟配图
      python download_bird_photos.py 朱鹮        # 为指定鸟配图（新增鸟时直接跑）
说明：图片为 CC 授权（优先 CC0/CC BY，其次 BY-NC），用于非商业科普展示。"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image

BASE = "https://api.gbif.org/v1"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img", "birds")
CREDITS_PATH = os.path.join(OUT_DIR, "CREDITS.json")
UA = "wanbird-photos/0.1"
MAX_W = 1200


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1 + i)


def match_key(name):
    m = get_json(BASE + "/species/match?name=" + urllib.parse.quote(name) + "&verbose=true")
    return m.get("usageKey")


def license_score(lic):
    s = (lic or "").lower()
    if "publicdomain" in s or "cc0" in s or "mark/1.0" in s:
        return 3
    if re.search(r"creativecommons\.org/licenses/by[^n]", s):   # CC BY / BY-SA（无 NC）
        return 2
    if re.search(r"creativecommons\.org/licenses/by-nc", s):     # BY-NC（能不用就不用）
        return 1
    return 0


def find_photo(key):
    """返回 (score, media) 或 None。优先 iNaturalist 开放数据 CDN 的高分照片。"""
    url = (f"{BASE}/occurrence/search?speciesKey={key}&mediaType=StillImage"
           f"&limit=50&advanced=false")
    d = get_json(url)
    best = None
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
            host = urllib.parse.urlparse(ident).netloc
            # 开放数据桶的 URL 可稳定下载且支持尺寸变体
            if "inaturalist-open-data.s3.amazonaws.com" in host:
                score += 1
            item = (score, m)
            if best is None or score > best[0]:
                best = (score, m)
    return best


def size_url(ident, size="large"):
    if "inaturalist-open-data.s3.amazonaws.com" in ident:
        return re.sub(r"/(original|large|medium|small|square)\.jpg$", "/" + size + ".jpg", ident)
    return ident


def download_save(ident, out_path):
    req = urllib.request.Request(ident, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "P", "LA"):
        im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, int(im.height * MAX_W / im.width)), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=82, optimize=True)


def added_photos():
    """取现有 birds.json 里的鸟（id + 中文名）。"""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "birds.json"),
              encoding="utf-8") as f:
        return [(b["id"], b["name"]) for b in json.load(f)]


def main(names_only=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    credits = {}
    if os.path.exists(CREDITS_PATH):
        with open(CREDITS_PATH, encoding="utf-8") as f:
            credits = json.load(f)

    targets = added_photos()
    if names_only:
        want = set(names_only)
        targets = [(i, n) for i, n in targets if n in want or i in want]

    for bid, name in targets:
        # 已有照片（你自己放的 jpg/png）就不覆盖
        if any(os.path.exists(os.path.join(OUT_DIR, bid + ext)) for ext in (".jpg", ".png")):
            print(f"– {name:6s} 已有照片，跳过（如需替换请先删 static/img/birds/{bid}.png）")
            continue
        try:
            key = match_key(name)
            found = find_photo(key)
            if not found:
                print(f"✗ {name:6s} 没有找到可用的授权照片")
                continue
            score, m = found
            src = size_url(m["identifier"], "large")
            out = os.path.join(OUT_DIR, bid + ".jpg")
            download_save(src, out)
            credits[bid] = {
                "name": name,
                "photographer": (m.get("creator") or "").strip() or "iNaturalist 用户",
                "license": m.get("license") or "",
                "page": m.get("references") or "",
                "direct": src,
            }
            print(f"✓ {name:6s} <- {credits[bid]['photographer']} [{os.path.basename(out)} "
                  f"{os.path.getsize(out)//1024}KB]")
        except Exception as e:
            print(f"✗ {name:6s} 失败：{e}")
        time.sleep(0.3)

    with open(CREDITS_PATH, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
