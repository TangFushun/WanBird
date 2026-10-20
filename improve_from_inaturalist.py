# -*- coding: utf-8 -*-
"""依据开放权威数据改进图鉴（对 388 种自动导入的鸟）：

1) 用 iNaturalist 物种精选图（default_photo，社区精选的代表性照片）替换图片——
   通常主体清晰、明确含鸟，比随机观测照片可靠；
2) 用 GBIF 国家分布统计重写「地理分布」（真实、可读）；
3) 用 iNaturalist 补英文名（locale=en）；
4) 更新 CREDITS（摄影师/许可/原页）。

用法：python improve_from_inaturalist.py
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

from import_birds_from_xlsx import BASE, UA, get_json, gbif_match

ROOT = os.path.dirname(os.path.abspath(__file__))
BIRDS_PATH = os.path.join(ROOT, "data", "birds.json")
IMG_DIR = os.path.join(ROOT, "public", "static", "img", "birds")
CREDITS_PATH = os.path.join(IMG_DIR, "CREDITS.json")
INAT = "https://api.inaturalist.org/v1"
N_WORKERS = 8

COUNTRY_CN = {
    "CN": "中国", "RU": "俄罗斯", "JP": "日本", "IN": "印度", "MN": "蒙古",
    "KR": "韩国", "KP": "朝鲜", "VN": "越南", "TH": "泰国", "MM": "缅甸",
    "LA": "老挝", "NP": "尼泊尔", "BT": "不丹", "PK": "巴基斯坦",
    "KZ": "哈萨克斯坦", "KG": "吉尔吉斯斯坦", "TJ": "塔吉克斯坦",
    "UZ": "乌兹别克斯坦", "TM": "土库曼斯坦", "AF": "阿富汗",
    "US": "美国", "CA": "加拿大", "MX": "墨西哥", "AU": "澳大利亚", "NZ": "新西兰",
    "GB": "英国", "FR": "法国", "DE": "德国", "SE": "瑞典", "FI": "芬兰", "NO": "挪威",
    "DK": "丹麦", "NL": "荷兰", "BE": "比利时", "CH": "瑞士", "AT": "奥地利",
    "IT": "意大利", "ES": "西班牙", "PT": "葡萄牙", "PL": "波兰", "CZ": "捷克",
    "SK": "斯洛伐克", "HU": "匈牙利", "RO": "罗马尼亚", "BG": "保加利亚",
    "UA": "乌克兰", "BY": "白俄罗斯", "LT": "立陶宛", "LV": "拉脱维亚",
    "EE": "爱沙尼亚", "IE": "爱尔兰", "IS": "冰岛", "TR": "土耳其",
    "IL": "以色列", "IR": "伊朗", "IQ": "伊拉克", "SA": "沙特阿拉伯",
    "EG": "埃及", "ZA": "南非", "KE": "肯尼亚", "TZ": "坦桑尼亚",
    "BR": "巴西", "AR": "阿根廷", "CL": "智利", "PE": "秘鲁", "CO": "哥伦比亚",
    "EC": "厄瓜多尔", "VE": "委内瑞拉", "BO": "玻利维亚", "PY": "巴拉圭", "UY": "乌拉圭",
    "TW": "台湾", "HK": "香港", "MO": "澳门", "SG": "新加坡", "PH": "菲律宾",
    "MY": "马来西亚", "ID": "印度尼西亚", "BN": "文莱", "KH": "柬埔寨",
    "BD": "孟加拉国", "LK": "斯里兰卡",
}


def inat_taxon(latin):
    """按学名精确匹配 iNaturalist 分类单元。"""
    q = urllib.parse.quote(latin)
    d = get_json(f"{INAT}/taxa?q={q}&locale=en&per_page=8", tries=2)
    target = latin.strip().lower()
    for r in d.get("results", []):
        if (r.get("name") or "").strip().lower() == target:
            return r
    return None


def taxon_detail(tid):
    try:
        d = get_json(f"{INAT}/taxa/{tid}?locale=en", tries=2)
        res = d.get("results") or []
        return res[0] if res else None
    except Exception:
        return None


def lic_rank(lic):
    """许可优先级：CC0 > CC BY/SA > CC BY-NC/SA > 其他 CC > ND 类（最低）。"""
    lic = (lic or "").strip().lower()
    if not lic:
        return -1                  # 版权保留，不用
    if lic.startswith("cc0"):
        return 5
    if lic in ("cc-by", "cc-by-sa"):
        return 4
    if lic in ("cc-by-nc", "cc-by-nc-sa"):
        return 3
    if lic.endswith("-nd"):
        return 1
    return 2


def pick_cc_photo(detail):
    """从 iNat 精选图（default_photo + taxon_photos）中挑一张 CC 授权的，
    优先更宽松的许可；版权保留(ARR, license_code 为空)的一律不用。"""
    if not detail:
        return None
    pics = []
    dp = detail.get("default_photo") or {}
    if dp:
        pics.append((lic_rank(dp.get("license_code")), 1, dp))
    for tp in detail.get("taxon_photos") or []:
        p = tp.get("photo") or {}
        if p:
            pics.append((lic_rank(p.get("license_code")), 0, p))
    pics = [x for x in pics if x[0] > 0 and (x[2].get("url") or "")]
    pics.sort(key=lambda x: (-x[0], -x[1]))
    return pics[0][2] if pics else None


def large_url(u):
    return re.sub(r"/(square|thumb|small|medium)\.(jpe?g)$", r"/large.\2", u)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


def save_jpg(data, path, max_w=900, quality=82):
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "P", "LA"):
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(path, "JPEG", quality=quality, optimize=True)


def country_stats(key):
    """返回 (总记录数, [(国家中文, 条数)...])。"""
    d = get_json(f"{BASE}/occurrence/search?speciesKey={key}&hasCoordinate=true"
                 f"&limit=0&facet=country&facetLimit=8", tries=2)
    total = d.get("count") or 0
    counts = []
    for f in (d.get("facets") or []):
        if f.get("field") == "COUNTRY" or f.get("name") == "COUNTRY":
            counts = f.get("counts") or []
            break
    top = []
    for c in counts[:6]:
        nm = c.get("name")
        if not nm:
            continue
        top.append((COUNTRY_CN.get(nm, nm), c.get("count")))
    return total, top


def process(b, credits):
    out = {"id": b["id"], "name": b["name"], "img": "skip", "en": "skip", "dist": "skip"}
    try:
        # 1) iNat 精选图（仅 CC 授权）
        tax = inat_taxon(b["latin"])
        if tax:
            detail = taxon_detail(tax.get("id")) or tax
            dp = pick_cc_photo(detail) or {}
            u = dp.get("url") or ""
            if u:
                lurl = large_url(u)
                try:
                    data = fetch(lurl)
                    save_jpg(data, os.path.join(IMG_DIR, b["image"].split("/")[-1]))
                    out["img"] = "ok"
                    pid = dp.get("id")
                    credits[b["id"]] = {
                        "name": b["name"],
                        "latin": b["latin"],
                        "photographer": (dp.get("attribution") or "iNaturalist 用户").strip(),
                        "license": dp.get("license_code") or "",
                        "page": (f"https://www.inaturalist.org/photos/{pid}" if pid else ""),
                        "direct": lurl,
                        "status": "inat-default",
                    }
                except Exception as e:
                    out["img"] = "fail:" + str(e)[:60]
            # 英文名
            en = (tax.get("preferred_common_name") or "").strip()
            if en and not b.get("english"):
                b["english"] = en
                out["en"] = "set"
        # 2) GBIF 国家分布
        key = gbif_match(b["latin"]).get("key")
        if key:
            total, top = country_stats(key)
            if top:
                txt = ("依据 GBIF 公开观测记录（1980 年至今，共 %d 条），记录主要来自：%s。"
                       "具体分布范围以权威名录与图鉴为准。"
                       % (total, "、".join(f"{n}（{c} 条）" for n, c in top)))
                sec = next((s for s in b.get("sections", []) if s.get("key") == "distribution"), None)
                if sec:
                    sec["text"] = txt
                    out["dist"] = "ok"
    except Exception as e:
        out["err"] = str(e)[:120]
    return out


def main():
    birds = json.load(open(BIRDS_PATH, encoding="utf-8"))
    credits = {}
    if os.path.exists(CREDITS_PATH):
        try:
            credits = json.load(open(CREDITS_PATH, encoding="utf-8"))
        except Exception:
            credits = {}
    targets = birds[6:]  # 只处理自动导入的 388 种；原有 6 种保持人工档案
    print(f"待改进 {len(targets)} 种")

    done = 0
    results = []
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = [ex.submit(process, b, credits) for b in targets]
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 25 == 0:
                with open(BIRDS_PATH, "w", encoding="utf-8") as f:
                    json.dump(birds, f, ensure_ascii=False, indent=1)
            print(f"[{done}/{len(targets)}] {r['name']} img={r['img']} en={r['en']} dist={r['dist']}")

    with open(BIRDS_PATH, "w", encoding="utf-8") as f:
        json.dump(birds, f, ensure_ascii=False, indent=1)
    with open(CREDITS_PATH, "w", encoding="utf-8") as f:
        json.dump(credits, f, ensure_ascii=False, indent=1)

    from collections import Counter
    img = Counter(r["img"].split(":")[0] for r in results)
    en = Counter(r["en"] for r in results)
    dist = Counter(r["dist"] for r in results)
    print("\n=== 完成 ===")
    print("图片:", dict(img), "| 英文名:", dict(en), "| 分布:", dict(dist))
    print("CREDITS 条数:", len(credits))


if __name__ == "__main__":
    main()
