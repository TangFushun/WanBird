# -*- coding: utf-8 -*-
"""从 GBIF 下载六种鸟的真实观测坐标，去重后存入 static/data/occur/<id>.json。
数据：GBIF.org 聚合记录；许可须以原始数据集为准，坐标点不代表实时分布。"""
from datetime import datetime, timezone
import json
import os
import time
import urllib.parse
import urllib.request

BASE = "https://api.gbif.org/v1"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "static", "data", "occur")

SPECIES = [
    ("oriental-stork", "Ciconia boyciana"),
    ("crested-ibis", "Nipponia nippon"),
    ("spoon-billed-sandpiper", "Calidris pygmaea"),
    ("scaly-sided-merganser", "Mergus squamatus"),
    ("hooded-crane", "Grus monacha"),
    ("elliots-pheasant", "Syrmaticus ellioti"),
]

CAP = 1500          # 每物种最多保留的观测点数（渲染足够，文件小）
YEAR_FROM = 1980    # 只取较新记录，避免旧重复


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wanbird-gbif/0.2"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def match_key(name):
    m = get_json(BASE + "/species/match?name=" + urllib.parse.quote(name) + "&verbose=true")
    return m.get("usageKey")


def fetch_occurrences(key, cap):
    pts = set()
    offset = 0
    while len(pts) < cap and offset <= 9000:
        url = (f"{BASE}/occurrence/search?speciesKey={key}&hasCoordinate=true"
               f"&spatialIssues=false&year={YEAR_FROM},2026&limit=300&offset={offset}")
        d = get_json(url)
        for o in d.get("results", []):
            lat, lon = o.get("decimalLatitude"), o.get("decimalLongitude")
            if lat is None or lon is None:
                continue
            # 保留 ~0.1km 级精度，去掉完全重复的坐标
            pts.add((round(float(lon), 3), round(float(lat), 3)))
        count = d.get("count") or 0
        if d.get("endOfRecords") or offset + 300 >= count:
            break
        offset += 300
        time.sleep(0.15)
    return sorted(pts)


os.makedirs(OUT_DIR, exist_ok=True)
for bid, sp in SPECIES:
    try:
        key = match_key(sp)
        pts = fetch_occurrences(key, CAP)
        path = os.path.join(OUT_DIR, bid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pts, f, ensure_ascii=False, separators=(",", ":"))
        with open(path.replace(".json", ".meta.json"), "w", encoding="utf-8") as f:
            json.dump({"source": "GBIF", "species_key": key,
                       "retrieved_on": datetime.now(timezone.utc).isoformat(),
                       "year_range": [YEAR_FROM, 2026], "coordinate_count": len(pts),
                       "query": {"hasCoordinate": True, "spatialIssues": False},
                       "note": "抽样、去重和简化后的坐标；不代表记录总数或完整分布。"}, f, ensure_ascii=False, indent=2)
        print("%-24s key=%-10s points=%d -> %s" % (bid, key, len(pts), os.path.relpath(path)))
    except Exception as e:
        print("%-24s ERROR %s" % (bid, e))
