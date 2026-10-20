# -*- coding: utf-8 -*-
"""从《国家重点保护动物名录-鸟纲-图片链接.xlsx》批量导入图鉴的全部鸟。

对每种鸟自动完成：
  1. GBIF /species/match 权威核验学名（记录 matchType/status，失败或模糊的进报告）；
  2. 提取分类阶元（纲→目→科→属，常见目给出中文名，其余回落拉丁文）；
  3. 检索并下载一张 CC 授权写真（iNaturalist 开放数据），按学名命名 <学名>.jpg；
     表格里的"图片链接"是 Google 搜索页而非图片文件（且 Google 在本网络被屏蔽），
     故改用 GBIF/iNaturalist 授权图片管线。
  4. 合并进 data/birds.json（保留现有鸟类），并写 data/import_report.json 报告。

用法：python import_birds_from_xlsx.py
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import openpyxl
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(ROOT, "国家重点保护动物名录-鸟纲-图片链接.xlsx")
OUT_BIRDS = os.path.join(ROOT, "data", "birds.json")
REPORT = os.path.join(ROOT, "data", "import_report.json")
IMG_DIR = os.path.join(ROOT, "public", "static", "img", "birds")

BASE = "https://api.gbif.org/v1"
UA = "wanbird-import/0.4"
N_WORKERS = 6

# 常见目中文名（覆盖名录绝大多数；缺的回落拉丁文）
ORDER_CN = {
    "Galliformes": "鸡形目", "Anseriformes": "雁形目", "Podicipediformes": "鸊鷉目",
    "Columbiformes": "鸽形目", "Pterocliformes": "沙鸡目", "Caprimulgiformes": "夜鹰目",
    "Apodiformes": "雨燕目", "Cuculiformes": "鹃形目", "Gruiformes": "鹤形目",
    "Otidiformes": "鸨形目", "Charadriiformes": "鸻形目", "Phaethontiformes": "鹲形目",
    "Gaviiformes": "潜鸟目", "Procellariiformes": "鹱形目", "Sphenisciformes": "企鹅目",
    "Ciconiiformes": "鹳形目", "Suliformes": "鲣鸟目", "Pelecaniformes": "鹈形目",
    "Accipitriformes": "鹰形目", "Strigiformes": "鸮形目", "Bucerotiformes": "犀鸟目",
    "Coraciiformes": "佛法僧目", "Piciformes": "啄木鸟目", "Falconiformes": "隼形目",
    "Psittaciformes": "鹦形目",
}


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def gbif_match(latin):
    m = get_json(BASE + "/species/match?name=" + urllib.parse.quote(latin) + "&verbose=true")
    return {
        "found": m.get("matchType") != "NONE",
        "matchType": m.get("matchType"),
        "status": m.get("status"),
        "matchedName": m.get("matchedName") or m.get("canonicalName") or "",
        "key": m.get("usageKey"),
    }


def gbif_taxonomy(key):
    if not key:
        return []
    s = get_json(BASE + "/species/" + str(key))
    out = [{"rank": "纲", "cn": "鸟纲", "latin": "Aves"}]
    order_lat = s.get("order")
    if order_lat:
        out.append({"rank": "目", "cn": ORDER_CN.get(order_lat, order_lat), "latin": order_lat})
    for rank, key_ in (("科", "family"), ("属", "genus")):
        latin = s.get(key_)
        if latin:
            out.append({"rank": rank, "cn": latin, "latin": latin})
    return out


def license_score(lic):
    s = (lic or "").lower()
    if "publicdomain" in s or "cc0" in s or "mark/1.0" in s:
        return 3
    if re.search(r"creativecommons\.org/licenses/by[^n]", s):
        return 2
    if re.search(r"creativecommons\.org/licenses/by-nc", s):
        return 1
    return 0


def find_photo(key):
    """返回 (score, media) 或 None。优先 iNaturalist 开放数据 + 宽松许可。"""
    url = f"{BASE}/occurrence/search?speciesKey={key}&mediaType=StillImage&limit=50"
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
            if "inaturalist-open-data.s3.amazonaws.com" in urllib.parse.urlparse(ident).netloc:
                score += 1
            if best is None or score > best[0]:
                best = (score, m)
    return best


def size_url(ident):
    if "inaturalist-open-data.s3.amazonaws.com" in ident:
        return re.sub(r"/(original|large|medium|small|square)\.jpg$", "/large.jpg", ident)
    return ident


def download_save(ident, out_path, max_w=800, quality=80):
    req = urllib.request.Request(ident, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read()
    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "P", "LA"):
        im = im.convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=quality, optimize=True)


def slugify(latin):
    s = re.sub(r"[^a-z0-9]+", "-", latin.lower()).strip("-")
    return s or "bird"


def main():
    os.makedirs(IMG_DIR, exist_ok=True)
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb["鸟类图片清单"]
    rows = list(ws.iter_rows(values_only=True))[1:]

    existing = []
    if os.path.exists(OUT_BIRDS):
        with open(OUT_BIRDS, encoding="utf-8") as f:
            existing = json.load(f)
    existing_cn = {b.get("name") for b in existing}
    used_ids = {b.get("id") for b in existing}

    # ---- 解析并去重（跳过已有鸟类：保留原有丰富档案） ----
    todos = []
    for r in rows:
        raw, checked, cn, status_col, note = r[1], r[2], r[3], r[6], r[7]
        latin = ((checked or "").strip()) or ((raw or "").strip())
        cn = str(cn or "").strip()
        if not latin or not cn:
            continue
        if cn in existing_cn:
            continue
        sid = slugify(latin)
        n = 1
        while sid in used_ids:
            sid = f"{slugify(latin)}-{n}"
            n += 1
        used_ids.add(sid)
        todos.append({
            "row": r[0], "id": sid, "latin": latin, "cn": cn,
            "cn_uncertain": "尚未可靠核实" in str(status_col or ""),
            "note": str(note or "").strip(),
        })
    print(f"待导入 {len(todos)} 种（现有 {len(existing)} 种）")
    if not todos:
        print("没有新增种类，结束。")
        return

    results = {}

    # ---- 阶段 1：GBIF 学名匹配 + 分类阶元 ----
    def do_match(t):
        try:
            g = gbif_match(t["latin"])
            tax = gbif_taxonomy(g.get("key")) if g.get("key") else []
            return t, g, tax
        except Exception as e:
            return t, {"error": str(e)}, []

    done = 0
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = [ex.submit(do_match, t) for t in todos]
        for fut in as_completed(futs):
            t, g, tax = fut.result()
            results[t["id"]] = {
                "row": t["row"], "cn": t["cn"], "latin": t["latin"],
                "id": t["id"], "cn_uncertain": t["cn_uncertain"], "note": t["note"],
                "match": g, "taxonomy": tax, "photo_status": "pending",
            }
            done += 1
            print(f"[匹配 {done}/{len(todos)}] {t['cn']} -> "
                  f"{g.get('matchedName') or g.get('error', '?')} ({g.get('matchType')}/{g.get('status')})")

    # ---- 阶段 2：图片下载 ----
    def do_photo(res):
        if res["match"].get("error"):
            return "match-failed"
        key = res["match"].get("key")
        if not key:
            return "no-key"
        out_path = os.path.join(IMG_DIR, res["latin"] + ".jpg")
        if os.path.exists(out_path):
            return "existing"
        try:
            found = find_photo(key)
            if not found:
                return "none-found"
            src = size_url(found[1]["identifier"])
            download_save(src, out_path)
            return "ok"
        except Exception as e:
            return "fail:" + str(e)[:120]

    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = {ex.submit(do_photo, res): res for res in results.values()}
        for fut in as_completed(futs):
            futs[fut]["photo_status"] = fut.result()

    # ---- 汇总生成 birds.json ----
    new_birds = []
    for res in results.values():
        order_cn = next((t["cn"] for t in res["taxonomy"] if t["rank"] == "目"), "")
        new_birds.append({
            "id": res["id"],
            "name": res["cn"],
            "latin": res["latin"],
            "english": "",
            "aliases": [],
            "iucn": "",
            "protection": "",
            "order": order_cn,
            "image": "/static/img/birds/" + res["latin"] + ".jpg",
            "summary": f"{res['cn']}（学名：{res['latin']}）属国家重点保护鸟类，详细习性档案整理中。",
            "taxonomy": res["taxonomy"],
            "sections": [],
            "anhui": "",
        })

    merged = existing + new_birds
    with open(OUT_BIRDS, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # ---- 报告 ----
    photo_c = Counter((res.get("photo_status") or "?").split(":")[0] for res in results.values())
    attention = [res for res in results.values()
                 if res["match"].get("error")
                 or res["match"].get("matchType") in ("NONE", "FUZZY", "HIGHERRANK")]
    report = {
        "total_rows": len(rows),
        "imported": len(new_birds),
        "existing_kept": len(existing),
        "skipped_duplicates": len(rows) - len(todos),
        "photo_status": dict(photo_c),
        "match_attention": [
            {"row": r["row"], "cn": r["cn"], "latin": r["latin"],
             "matchType": r["match"].get("matchType"), "status": r["match"].get("status"),
             "note": r["note"]} for r in attention
        ],
        "cn_uncertain": [{"row": r["row"], "cn": r["cn"], "latin": r["latin"]}
                         for r in results.values() if r["cn_uncertain"]],
        "note": "图片列是 Google 搜索页而非图片文件，且 Google 被本网络屏蔽；"
                "已改用 GBIF/iNaturalist 开放数据授权写真（按学名命名）。",
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("\n=== 完成 ===")
    print(f"新增 {len(new_birds)} 种，图鉴共 {len(merged)} 种")
    print("图片状态：", dict(photo_c))
    print(f"需人工复核 {len(attention) + len(report['cn_uncertain'])} 条，详见 {REPORT}")


if __name__ == "__main__":
    main()
