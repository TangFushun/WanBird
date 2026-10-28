# -*- coding: utf-8 -*-
"""为图鉴中「无百科正文」的鸟批量补充自动生成版百科 + 栖息地数据。

对每种鸟（仅处理还没有 sections 的）：
  1. GBIF 英文名（/vernacularNames?language=en）；
  2. 下载真实观测点 → static/data/occur/<id>.json（1980 年以来）；
  3. 生成按目级科学模板的六节百科（外形/分布/栖息/习性/繁殖/保护），
     明确标注「自动生成版」、不臆造具体数字；
  4. 由观测点凸包生成「观测分布区」示意色块（跨大洲/点数过少则只显示观测点）。

用法：python enrich_birds_from_gbif.py
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image  # noqa: F401  (占位，后续如需图片处理)

from import_birds_from_xlsx import BASE, UA, get_json, gbif_match, gbif_taxonomy, ORDER_CN

ROOT = os.path.dirname(os.path.abspath(__file__))
BIRDS_PATH = os.path.join(ROOT, "data", "birds.json")
OCC_DIR = os.path.join(ROOT, "public", "static", "data", "occur")
REPORT = os.path.join(ROOT, "data", "enrich_report.json")
N_WORKERS = 12
OCC_CAP = 600
YEAR_FROM = 1980

# ---- 按目级科学模板（真实但不涉及种内细节数值；未知目回落通用描述） ----
ORDER_BIO = {
    "Anseriformes": {
        "appearance": "水禽，体形紧凑、喙扁阔、脚具蹼，善游泳；羽色在两性间常有差异。",
        "habitat": "活动于湖泊、河流、水库、沼泽与苇丛等湿地。",
        "habit": "多结群游弋觅食，主食水生植物、谷物与无脊椎动物，多为候鸟、具季节性迁徙。",
        "breed": "常在湖沼芦苇或岸边地表筑巢繁殖。"},
    "Galliformes": {
        "appearance": "地栖性鸡类，体形圆胖、喙短粗善刨土，腿脚强健，常在地面活动。",
        "habitat": "多栖息于森林、林缘、灌丛、草甸与山地草丛。",
        "habit": "以植物嫩芽、果实、种子与昆虫为食，晨昏活动频繁，受惊时迅速奔跑躲藏。",
        "breed": "多在地面隐蔽处（凹坑或草丛）筑巢产卵，由亲鸟孵卵育雏。"},
    "Podicipediformes": {
        "appearance": "小型潜水水鸟，喙尖、脚位于体后并具桨状趾，浮水时姿态低伏。",
        "habitat": "栖息于淡水湖泊、池塘、水库与河流缓水段。",
        "habit": "善潜水捕食鱼虾与水生昆虫，常单只或小群活动。",
        "breed": "在水面浮巢中繁殖，雏鸟常驮伏于亲鸟背上。"},
    "Columbiformes": {
        "appearance": "体形圆润的鸠鸽类，头小颈短、喙短，飞行敏捷。",
        "habitat": "见于林地、开阔地、农田与城镇林地等。",
        "habit": "以种子与谷物为主要食物，多在地面啄食，常结群。",
        "breed": "营巢简单，多见于树枝或建筑，产卵 1-2 枚。"},
    "Pterocliformes": {
        "appearance": "沙鸡类，体形似鸽，翼长尾尖，羽色与环境近似。",
        "habitat": "栖息于干旱草原与半荒漠地带。",
        "habit": "长途飞行至水源饮水，结群活动、以种子为食。",
        "breed": "在地面凹坑内产卵，"},
    "Caprimulgiformes": {
        "appearance": "夜行性鸟类，体羽柔软、具隐蔽斑纹，喙宽而短、口裂极大，善捕飞虫。",
        "habitat": "栖息于森林、疏林与开阔地，白天伏地或栖枝隐蔽。",
        "habit": "黄昏与夜间活动，空中捕食飞虫，具拟态蹲伏习性。",
        "breed": "多不筑巢，直接产卵于地面或裸岩上。"},
    "Apodiformes": {
        "appearance": "雨燕类，翼狭长、飞行极快，喙小而嘴裂大，边飞边捕食。",
        "habitat": "常见于开阔天空、山崖、城市上空与水域附近。",
        "habit": "几乎全天飞行，主食空中浮游昆虫。",
        "breed": "多筑巢于崖壁洞穴或建筑物缝隙，用唾液粘合巢材。"},
    "Cuculiformes": {
        "appearance": "杜鹃类，体形修长、尾长、羽色以灰褐为主，脚趾对趾型。",
        "habitat": "栖息于森林、疏林、灌丛及公园等。",
        "habit": "主食昆虫（尤其毛虫），部分具巢寄生繁殖习性。",
        "breed": "多种不营巢，将卵产于寄主鸟巢中由其代为孵育。"},
    "Gruiformes": {
        "appearance": "鹤类与秧鸡类，体型较重、颈腿较长，羽色素雅。",
        "habitat": "栖息于湿地、沼泽、草甸与稻田等开阔水域生境。",
        "habit": "杂食性，以植物根茎、谷物、昆虫与小鱼虾为食，迁徙性强。",
        "breed": "多在水边浅滩或草甸筑巢繁殖。"},
    "Otidiformes": {
        "appearance": "鸨类，体型粗壮、腿长，善于行走，羽色与环境近似。",
        "habitat": "栖息于开阔草原、农田与荒漠草原。",
        "habit": "地栖性，主食植物与昆虫，结群或单只活动。",
        "breed": "在地面筑巢，雄鸟繁殖期常作求偶炫耀。"},
    "Charadriiformes": {
        "appearance": "涉禽与鸥类，体型多样；多具长喙长腿，喜在湿地活动。",
        "habitat": "分布于海岸滩涂、内陆湿地、河口、沙洲与湖泊周边。",
        "habit": "在泥滩浅水中觅食无脊椎动物，迁徙能力强、常结群。",
        "breed": "多在地面或滩涂筑巢。"},
    "Phaethontiformes": {
        "appearance": "热带海鸟，翼长、中央尾羽细长如飘带，羽色白或白相间黑斑。",
        "habitat": "远洋海鸟，繁殖与栖息于热带海岛。",
        "habit": "在海上掠食鱼类与乌贼。",
        "breed": "在海岛岩缝或地表筑巢。"},
    "Gaviiformes": {
        "appearance": "大型潜水鸟，喙尖利、体呈流线型，潜泳能力强。",
        "habitat": "繁殖于北方湖泊，冬季迁至沿岸海域。",
        "habit": "潜水捕鱼，善泳善飞。",
        "breed": "在湖岸地筑巢，双亲轮流孵卵。"},
    "Procellariiformes": {
        "appearance": "远洋海鸟（鹱、信天翁类），翼长、鼻管状，善长距离滑翔。",
        "habitat": "大部时间在海上生活，仅繁殖期上岛。",
        "habit": "以鱼类、乌贼与海洋废弃物为食，长程迁徙。",
        "breed": "在海岛筑巢产卵。"},
    "Ciconiiformes": {
        "appearance": "大型涉禽（鹳类），颈长腿长喙粗直，飞行时颈伸展。",
        "habitat": "栖息于开阔湿地、河流湖泊沿岸与稻田。",
        "habit": "在浅水中涉水觅食鱼蛙等，常成对或小群，迁徙性强。",
        "breed": "营巢于高大树木或岩壁，巢较大。"},
    "Suliformes": {
        "appearance": "鹈鹕、鸬鹚等水鸟，喙强健、善潜水，多为黑白配色。",
        "habitat": "沿岸海域、河口与大型水域。",
        "habit": "潜水或俯冲捕鱼，常结群。",
        "breed": "在岩岸、海岛或树上集群营巢。"},
    "Pelecaniformes": {
        "appearance": "鹮、鹭、鹈鹕与篦鹭类，多为涉禽，喙或长直或下弯，颈长。",
        "habitat": "栖息于湿地、浅水湖泊、滩涂与稻田等。",
        "habit": "在浅水觅食鱼、虾、蛙与昆虫，多结群，迁徙性强。",
        "breed": "在树木、苇丛或地面集群营巢。"},
    "Accipitriformes": {
        "appearance": "昼行性猛禽（鹰、雕、鹫、鹞等），喙钩状、爪锐利，翼大而阔。",
        "habitat": "见于山地、森林、草原与开阔荒野。",
        "habit": "肉食性，捕猎或取食腐肉，多在高空盘旋搜索。",
        "breed": "营巢于高大树木、岩壁或崖顶，巢大而坚固。"},
    "Strigiformes": {
        "appearance": "夜行性猛禽（鸮类），头大而圆、面盘显著，眼大向前，羽毛柔软。",
        "habitat": "栖息于森林、林缘、疏林与农田林地带。",
        "habit": "夜间捕食鼠类、昆虫与小鸟，飞行无声。",
        "breed": "多利用树洞、旧巢或岩隙繁殖。"},
    "Coraciiformes": {
        "appearance": "佛法僧目（翠鸟、蜂虎、佛法僧等），羽色鲜艳、喙长而锋利。",
        "habitat": "栖于水域岸边、林缘、开阔地与崖壁。",
        "habit": "食性多样，翠鸟类掠食鱼虾，蜂虎类捕食飞虫。",
        "breed": "多在土崖或河岸挖洞营巢。"},
    "Piciformes": {
        "appearance": "啄木鸟类，喙凿状、舌长、尾羽坚挺，善于攀木。",
        "habitat": "栖息于森林与林地。",
        "habit": "在树干上敲木搜寻昆虫幼虫，部分种类食果。",
        "breed": "在树干凿洞营巢。"},
    "Falconiformes": {
        "appearance": "隼类，体形流线、翼尖而长，飞行极快，喙钩状。",
        "habitat": "见于开阔地、农田、山地与城市上空。",
        "habit": "空中或俯冲捕食鸟类、昆虫与小兽。",
        "breed": "多利用岩壁、旧巢或巢箱繁殖。"},
    "Psittaciformes": {
        "appearance": "鹦鹉类，喙弯钩状、脚趾对趾型，羽色鲜艳，善攀缘。",
        "habitat": "栖息于森林、林缘与果园。",
        "habit": "以果实、种子与花蜜为食，常结群。",
        "breed": "多营巢于树洞。"},
    "Passeriformes": {
        "appearance": "雀形目鸣禽，体型多为中小型，羽色多样，喙型随食性变化。",
        "habitat": "广布于森林、灌丛、草甸、农田与城市绿地。",
        "habit": "食性多样（虫食、杂食、谷食），多善鸣唱，多数为候鸟或留鸟。",
        "breed": "多在树枝、灌丛或地面巢状营巢，多数为晚成鸟。"},
}

GENERIC = {
    "appearance": "属该目鸟类的典型结构与体形，具体羽色与形态因种而异。",
    "habitat": "栖息环境因种而异，需结合具体物种资料确认。",
    "habit": "食性与行为属于该目鸟类的典型生态特征，具体因种而异。",
    "breed": "繁殖方式因种而异。",
}


def region_of(lon, lat):
    if 72 <= lon <= 140 and 22 <= lat <= 55:
        return "东亚、中亚一带"
    if 90 <= lon <= 155 and 8 <= lat <= 22:
        return "东南亚一带"
    if 60 <= lon <= 95 and 6 <= lat <= 32:
        return "南亚一带"
    if 20 <= lon <= 60 and 10 <= lat <= 45:
        return "西亚至中东一带"
    if -25 <= lon <= 60 and 20 <= lat <= 70:
        return "欧洲、北非一带"
    if -130 <= lon <= -30 and 5 <= lat <= 65:
        return "美洲一带"
    if 95 <= lon <= 160 and -40 <= lat <= 0:
        return "大洋洲一带"
    if -25 <= lon <= 60 and -35 <= lat <= 20:
        return "非洲等地"
    return "跨多区域（迁徙性或广布种）"


def en_name(key):
    """从 GBIF 常见名里挑英文：language 字段须以 en 开头，且内容为纯英文字母。
    找不到则返回空串（宁缺毋滥，不放错语言误导用户）。"""
    try:
        d = get_json(f"{BASE}/species/{key}/vernacularNames?language=en", tries=2)
        for it in d.get("results", []):
            lang = (it.get("language") or ("en" if it.get("isPreferred") else ""))
            if not str(lang).lower().startswith("en"):
                continue
            v = (it.get("vernacularName") or "").strip()
            if 3 <= len(v) < 60 and re.fullmatch(r"[A-Za-z][A-Za-z .'\-()]*", v):
                return v
    except Exception:
        pass
    return ""


def occ_points(key):
    pts = set()
    offset = 0
    total = None
    while len(pts) < OCC_CAP and offset <= 9000:
        url = (f"{BASE}/occurrence/search?speciesKey={key}&hasCoordinate=true"
               f"&spatialIssues=false&year={YEAR_FROM},2026&limit=300&offset={offset}")
        d = get_json(url)
        if total is None:
            total = d.get("count") or 0
        for o in d.get("results", []):
            la, lo = o.get("decimalLatitude"), o.get("decimalLongitude")
            if la is None or lo is None:
                continue
            pts.add((round(float(lo), 3), round(float(la), 3)))
        count = d.get("count") or 0
        if d.get("endOfRecords") or offset + 300 >= count:
            break
        offset += 300
        time.sleep(0.1)
    return total, sorted(pts)


def cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points):
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 1:
        return pts
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def perp_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def rdp(points, eps=0.6):
    if len(points) < 3:
        return points
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perp_dist(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(points[:idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def build_range(pts):
    if len(pts) < 8:
        return []
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    if (max(lons) - min(lons)) > 110 or (max(lats) - min(lats)) > 85:
        return []  # 跨大洲/极广 → 不做多边形，仅保留观测点
    hull = convex_hull(pts)
    simp = rdp(hull, 0.6)
    if len(simp) < 4:
        return []
    cx = sum(p[0] for p in simp) / len(simp)
    cy = sum(p[1] for p in simp) / len(simp)
    poly = [[cx + (p[0] - cx) * 1.06, cy + (p[1] - cy) * 1.06] for p in simp]
    return [{"kind": "observed", "label": "观测分布区（GBIF 观测点凸包·示意）", "polygon": poly}]


def enrich(bird):
    bid, cn, latin = bird["id"], bird["name"], bird["latin"]
    try:
        g = gbif_match(latin)
        key = g.get("key")
        if not key:
            return {"id": bid, "cn": cn, "status": "no-key"}
        s = get_json(BASE + "/species/" + str(key))
        order = s.get("order") or ""
        family = s.get("family") or ""
        life_form = s.get("lifeForm") or ""
        en = en_name(key)
        occ_path = os.path.join(OCC_DIR, bid + ".json")
        # 复用已下载的观测点文件（避免重复拉取），没有则联网下载
        pts = []
        if os.path.exists(occ_path):
            try:
                pts = json.load(open(occ_path, encoding="utf-8"))
            except Exception:
                pts = []
        if not pts:
            total, pts = occ_points(key)
            with open(occ_path, "w", encoding="utf-8") as f:
                json.dump(pts, f, ensure_ascii=False, separators=(",", ":"))
            with open(occ_path.replace(".json", ".meta.json"), "w", encoding="utf-8") as f:
                json.dump({"source": "GBIF", "species_key": key,
                           "retrieved_on": datetime.now(timezone.utc).isoformat(),
                           "year_range": [YEAR_FROM, 2026], "coordinate_count": len(pts),
                           "query": {"hasCoordinate": True, "spatialIssues": False},
                           "note": "抽样坐标，不代表全部记录或实时分布。"}, f, ensure_ascii=False, indent=2)
        else:
            total = len(pts)

        bio = ORDER_BIO.get(order, GENERIC)
        order_cn = ORDER_CN.get(order, order)
        n = len(pts)
        section_text = {}
        section_text["appearance"] = bio["appearance"] + "（本页为按目级通性描述，具体种间差异请以清晰照片与专业图鉴为准。）"
        if pts:
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            lonmin, lonmax = min(lons), max(lons)
            latmin, latmax = min(lats), max(lats)
            span = f"经度约 {lonmin:.0f}°–{lonmax:.0f}°，纬度约 {latmin:.0f}°–{latmax:.0f}°"
            area = region_of((lonmin + lonmax) / 2, (latmin + latmax) / 2)
            section_text["distribution"] = (
                f"依据本地保存的 GBIF 历史坐标（{n} 个），坐标覆盖{span}，主要位于{area}。"
                "提示：为观测记录概括，不等同于权威分布范围。")
        else:
            section_text["distribution"] = "暂无公开观测记录数据（GBIF）。"
        section_text["habitat"] = bio["habitat"] + "（常见于上述生境，具体偏好因种而异。）"
        section_text["habit"] = bio["habit"]
        section_text["breeding"] = bio["breed"]
        section_text["conservation"] = (
            "国家保护级别见本页名录字段；国家保护级别与 IUCN 全球受威胁等级用途不同。"
            "本页尚未逐项核对原始评估版本。")

        en_part = f"；英文名：{en}" if en else ""
        summary = (
            f"{cn}（学名：{latin}{en_part}）属{order_cn}的鸟类。"
            "本页为按目级通性生成的基础资料，种级特征尚待逐项核查。")

        ranges = build_range(pts)
        bird["english"] = en
        bird["summary"] = summary
        bird["content_review"] = {"status": "draft", "updated_on": None,
                                  "note": "按目级通性生成，种级特征和段落来源待复核。"}
        bird["sections"] = [
            {"key": "appearance", "label": "外形特征", "text": section_text["appearance"]},
            {"key": "distribution", "label": "地理分布", "text": section_text["distribution"]},
            {"key": "habitat", "label": "栖息环境", "text": section_text["habitat"]},
            {"key": "habits", "label": "生活习性", "text": section_text["habit"]},
            {"key": "breeding", "label": "生长繁殖", "text": section_text["breeding"]},
            {"key": "conservation", "label": "保护现状", "text": section_text["conservation"]},
        ]
        bird["map"] = {"ranges": ranges, "sites": []}
        return {"id": bid, "cn": cn, "status": "ok",
                "occ": n, "range": len(ranges), "en": bool(en)}
    except Exception as e:
        return {"id": bid, "cn": cn, "status": "fail:" + str(e)[:120]}


def main():
    os.makedirs(OCC_DIR, exist_ok=True)
    birds = json.load(open(BIRDS_PATH, encoding="utf-8"))
    targets = [b for b in birds if not b.get("sections")]
    print(f"待丰富 {len(targets)} 种（已有正文的 {len(birds) - len(targets)} 种跳过）")

    done = 0
    results = []
    with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
        futs = [ex.submit(enrich, b) for b in targets]
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 50 == 0:  # 定期落盘，避免长任务中途失败全丢
                with open(BIRDS_PATH, "w", encoding="utf-8") as f:
                    json.dump(birds, f, ensure_ascii=False, indent=1)
            print(f"[{done}/{len(targets)}] {r['cn']} -> {r['status']}")

    with open(BIRDS_PATH, "w", encoding="utf-8") as f:
        json.dump(birds, f, ensure_ascii=False, indent=1)

    from collections import Counter
    st = Counter((r["status"].split(":")[0] if r["status"] != "ok" else "ok") for r in results)
    report = {
        "done": len(results),
        "status": dict(st),
        "with_range": sum(1 for r in results if r.get("range")),
        "with_en": sum(1 for r in results if r.get("en")),
        "failures": [r for r in results if r["status"].startswith("fail")],
    }
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n=== 完成 ===")
    print("状态分布:", dict(st))
    print("含范围色块:", report["with_range"], "| 含英文名:", report["with_en"])
    print("失败:", len(report["failures"]))


if __name__ == "__main__":
    main()
