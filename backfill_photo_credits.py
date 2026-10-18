# -*- coding: utf-8 -*-
"""图片来源回填 + 存疑/小图重配。

1. 全量回填 CREDITS.json：记录每只鸟当前采用照片的摄影师/许可/原始页面/直接链接。
   （best-effort：按当前 GBIF 检索首选记录回填；个别与当初下载文件若有偏差以原页为准。）
2. 对「学名匹配偏弱」的 7 种 + 「小于 20KB」的小图，重新检索多个候选，
   下载 large.jpg 取体积最大的一张替换（体积作为清晰度代理），仍 <20KB 的记为低质。

用法：python backfill_photo_credits.py
"""
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

from import_birds_from_xlsx import BASE, UA, get_json, gbif_match, license_score

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(ROOT, "static", "img", "birds")
CREDITS = os.path.join(IMG_DIR, "CREDITS.json")
BIRDS = json.load(open(os.path.join(ROOT, "data", "birds.json"), encoding="utf-8"))
N_WORKERS = 10


def media_candidates(key, limit=60):
    """返回 (score, media) 列表，按许可分降序（lic=0 跳过）。"""
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


def size_url(ident):
    if "inaturalist-open-data.s3.amazonaws.com" in ident:
        return re.sub(r"/(original|large|medium|small|square)\.jpg$", "/large.jpg", ident)
    return ident


def fetch_bytes(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1 + i)


def save_jpg(data, out_path, max_w=800, quality=80):
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "P", "LA"):
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=quality, optimize=True)


def best_large(cands, k=4):
    """从候选里试 k 个，挑下载后体积最大的一个。返回 (media, url, bytes_len) 或 None。"""
    best = None
    for score, m in cands[:k]:
        try:
            data = fetch_bytes(size_url(m["identifier"]))
            if not data:
                continue
            if best is None or len(data) > best[2]:
                best = (m, size_url(m["identifier"]), len(data))
        except Exception:
            continue
    return best


def build_refetch_names():
    rep = json.load(open(os.path.join(ROOT, "data", "import_report.json"), encoding="utf-8"))
    fuzzy = {a["cn"] for a in rep.get("match_attention", [])}
    # 排除已修好拼写的（照匹配到的正确种取的，风险低）
    fixed = {"镰翅鸡", "半蹼鹬", "渔雕", "西红脚隼", "台湾噪鹛", "布氏丛鹛", "棕腹林鹟"}
    fuzzy -= fixed
    small = {
        f for f in os.listdir(IMG_DIR)
        if f.endswith(".jpg") and os.path.getsize(os.path.join(IMG_DIR, f)) < 20 * 1024
    }
    small_names = set()
    for b in BIRDS:
        fn = b["image"].split("/")[-1]
        if fn in small:
            small_names.add(b["name"])
    return fuzzy | small_names


def process(bird, refetch_names):
    bid, name, latin = bird["id"], bird["name"], bird["latin"]
    out = {"name": name, "latin": latin, "photographer": "", "license": "",
           "page": "", "direct": "", "status": "ok"}
    try:
        key = gbif_match(latin).get("key")
        if not key:
            out["status"] = "no-key"
            return bid, out
        cands = media_candidates(key)
        if not cands:
            out["status"] = "no-photo"
            return bid, out

        target = os.path.join(IMG_DIR, bird["image"].split("/")[-1])
        if name in refetch_names:
            best = best_large(cands)
            if best:
                m, url, size = best
                try:
                    save_jpg(fetch_bytes(url), target)
                    out["status"] = f"refetched:{size // 1024}KB"
                    now = os.path.getsize(target)
                    out["refetched_size"] = now
                except Exception as e:
                    out["status"] = "refetch-fail:" + str(e)[:80]
            else:
                out["status"] = "refetch-none"
            if len(bird["image"].split("/")[-1]) < 1:
                pass
            m = best[0] if best else cands[0][1]
        else:
            m = cands[0][1]

        out["photographer"] = (m.get("creator") or "").strip() or "iNaturalist 用户"
        out["license"] = m.get("license") or ""
        out["page"] = m.get("references") or ""
        out["direct"] = size_url(m.get("identifier") or "")
        return bid, out
    except Exception as e:
        out["status"] = "fail:" + str(e)[:100]
        return bid, out


def main():
    refetch = build_refetch_names()
    print(f"待重配（模糊+小图，按中文名）: {len(refetch)} 种")
    targets = [b for b in BIRDS[6:]]   # 新导入的 388 种
    credits = {}
    done = 0
    replaced = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = [ex.submit(process, b, refetch) for b in targets]
        for fut in as_completed(futs):
            bid, rec = fut.result()
            credits[bid] = rec
            done += 1
            if rec["status"].startswith("refetched"):
                replaced += 1
            if done % 100 == 0:
                print(f"[{done}/{len(targets)}]")
    # 头部说明
    head = {
        "_note": "图片来源回填（best-effort）：按当前 GBIF 检索首选记录记录摄影师/许可/页面；"
                 "个别与最初下载文件如有偏差请以 page 原页为准。",
        "_sources": "photos: iNaturalist 开放数据（经 GBIF API 检索，CC 授权）",
    }
    credits = {**head, **credits}
    with open(CREDITS, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)

    # 最终小图检查
    small = [f for f in os.listdir(IMG_DIR)
             if f.endswith(".jpg") and os.path.getsize(os.path.join(IMG_DIR, f)) < 20 * 1024]
    print("\n=== 完成 ===")
    print("CREDITS 记录条数:", len(credits) - 2)
    print("已重配替换:", replaced)
    print("仍<20KB:", len(small), small[:12])


if __name__ == "__main__":
    main()
