"""Build the dated Anhui exploration snapshot from a traceable GBIF record archive.

Offline by default. No fabricated observations or dates; no new runtime dependency.
Refresh the DataV boundary explicitly with --refresh-boundary when appropriate.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public/static/data/traces"
BOUNDARY_URL = "https://geo.datav.aliyun.com/areas_v3/bound/340000_full.json"
GRID_KM = 20
KM_PER_DEGREE = 111.32
COS_LAT = math.cos(math.radians(32))


def wgs84_to_gcj02(lon, lat):
    """Match GBIF WGS84 locations to DataV's GCJ-02 boundary before clipping."""
    x, y = lon - 105, lat - 35
    dlat = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*math.sqrt(abs(x))
    dlat += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    dlat += (20*math.sin(y*math.pi) + 40*math.sin(y/3*math.pi))*2/3
    dlat += (160*math.sin(y/12*math.pi) + 320*math.sin(y*math.pi/30))*2/3
    dlon = 300 + x + 2*y + .1*x*x + .1*x*y + .1*math.sqrt(abs(x))
    dlon += (20*math.sin(6*x*math.pi) + 20*math.sin(2*x*math.pi))*2/3
    dlon += (20*math.sin(x*math.pi) + 40*math.sin(x/3*math.pi))*2/3
    dlon += (150*math.sin(x/12*math.pi) + 300*math.sin(x/30*math.pi))*2/3
    rad = lat*math.pi/180
    magic = 1 - .00669342162296594323 * math.sin(rad)**2
    dlat = dlat*180 / ((6378245*(1-.00669342162296594323))/(magic*math.sqrt(magic))*math.pi)
    dlon = dlon*180 / (6378245/math.sqrt(magic)*math.cos(rad)*math.pi)
    return lon + dlon, lat + dlat


def polygons(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError("Unsupported boundary geometry")


def in_ring(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a
        bx, by = b
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) < 1e-10 and min(ax,bx)-1e-10 <= x <= max(ax,bx)+1e-10 and min(ay,by)-1e-10 <= y <= max(ay,by)+1e-10:
            return True
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
    return inside


def contains(point, geometry):
    return any(in_ring(point, p[0]) and not any(in_ring(point, h) for h in p[1:])
               for p in polygons(geometry))


def project(lon, lat):
    # Local equirectangular approximation, reference parallel 32 N, kilometres.
    return (lon-114)*KM_PER_DEGREE*COS_LAT, (lat-29)*KM_PER_DEGREE


def acquire_processed_archive(use_complete_species=False):
    """Clip new, traceable records; publish cells and city codes, never exact GPS."""
    cache = ROOT / "_tools/anhui-gbif"
    manifest = json.loads((cache/"manifest.json").read_text(encoding="utf-8"))
    if manifest["errors"] and not use_complete_species:
        raise ValueError("Finish or explicitly resolve acquisition errors before rebuilding")
    boundary = json.loads((OUT/"anhui-cities.geojson").read_text(encoding="utf-8"))
    features = boundary["features"]
    prepared = []
    for feature in features:
        points = [p for poly in polygons(feature["geometry"]) for ring in poly for p in ring]
        prepared.append((str(feature["properties"]["adcode"]), feature["geometry"],
                         (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))))
    rows, audits, ids, locations = [], [], set(), set()
    for entry in manifest["files"]:
        raw = (cache/entry["file"]).read_bytes()
        source = json.loads(gzip.decompress(raw))
        if not source.get("complete") or len(source["records"]) != source["api_count"]:
            raise ValueError("Incomplete source file: "+entry["file"])
        counts = Counter()
        for record in source["records"]:
            rid = str(record["key"])
            if rid in ids:
                counts["duplicates"] += 1
                continue
            ids.add(rid)
            lon, lat = record.get("decimalLongitude"), record.get("decimalLatitude")
            if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in (lon,lat)):
                counts["invalid_coordinate"] += 1
                continue
            uncertainty = record.get("coordinateUncertaintyInMeters")
            if isinstance(uncertainty, (int,float)) and uncertainty > 20000:
                counts["coarse_coordinate"] += 1
                continue
            transformed = wgs84_to_gcj02(lon, lat)
            city = None
            for cid, geometry, (west,south,east,north) in prepared:
                if west <= transformed[0] <= east and south <= transformed[1] <= north and contains(transformed, geometry):
                    city = cid
                    break
            if city is None:
                counts["outside"] += 1
                continue
            year, month = record.get("year"), record.get("month")
            if not isinstance(year, int) or not 1980 <= year <= 2026:
                counts["invalid_date"] += 1
                continue
            month = month if isinstance(month, int) and 1 <= month <= 12 else 0
            px, py = project(*transformed)
            cell = f"{math.floor(px/GRID_KM)}:{math.floor(py/GRID_KM)}"
            counts["included"] += 1
            locations.add((round(lon,5),round(lat,5)))
            rows.append({"id": rid, "bird": entry["bird_id"], "city": city, "cell": cell,
                         "year": year, "month": month, "date": record.get("eventDate"),
                         "dataset": record.get("datasetKey"), "license": record.get("license")})
        audits.append({"bird_id": entry["bird_id"], "api_count": source["api_count"],
                       "retrieved_on": source["retrieved_on"], "query": source["query"],
                       "input_sha256": hashlib.sha256(raw).hexdigest(), "counts": dict(counts)})
    dataset_metadata=manifest.get("datasets", [])
    if not dataset_metadata:
        for metadata_file in cache.glob('dataset-*.json'):
            info=json.loads(metadata_file.read_text(encoding='utf-8'))
            dataset_metadata.append({k:info.get(k) for k in ('key','title','doi','license')})
    archive = {"schema_version": 2, "retrieved_on": manifest["retrieved_on"], "query": manifest["query"],
               "cohort_note": manifest["selection"], "candidate_species": manifest["matched_taxa"],
               "bbox_records": sum(a["api_count"] for a in audits), "distinct_coordinate_pairs": len(locations),
               "datasets": dataset_metadata, "omitted_candidates": manifest.get("errors", []), "audit": audits, "records": rows}
    target = ROOT / "data/anhui-gbif-records.json.gz"
    if not rows:
        raise ValueError("No validated Anhui records; preserving the previous snapshot")
    # The committed archive is reproducible at grid/city level without disclosing exact GPS.
    with gzip.open(target, "wt", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, separators=(",", ":"))
    return archive


def build_current(refresh_records=False, use_complete_species=False):
    archive_file = ROOT / "data/anhui-gbif-records.json.gz"
    if refresh_records:
        archive = acquire_processed_archive(use_complete_species)
    else:
        with gzip.open(archive_file, "rt", encoding="utf-8") as f:
            archive = json.load(f)
    boundary_file = OUT/"anhui-cities.geojson"
    boundary = json.loads(boundary_file.read_text(encoding="utf-8"))
    birds = {b["id"]: b for b in json.loads((ROOT/"data/birds.json").read_text(encoding="utf-8"))}
    cities = []
    for feature in boundary["features"]:
        props = feature["properties"]
        vertices = [xy for poly in polygons(feature["geometry"]) for ring in poly for xy in ring]
        cities.append({"id": str(props["adcode"]), "name": props["name"], "center": props.get("centroid", props["center"]),
                       "bbox": [min(p[0] for p in vertices), min(p[1] for p in vertices), max(p[0] for p in vertices), max(p[1] for p in vertices)]})
    total, cells, datasets = Counter(), {}, Counter()
    years, known_months = [], 0
    for row in archive["records"]:
        bid, cid, cell_id, year, month = (row[k] for k in ("bird", "city", "cell", "year", "month"))
        col, gridrow = map(int, cell_id.split(":"))
        cell = cells.setdefault(cell_id, {"id": cell_id, "col": col, "row": gridrow, "counts": {}, "_events": Counter(), "examples": []})
        by_city = cell["counts"].setdefault(bid, {})
        by_city[cid] = by_city.get(cid,0)+1
        cell["_events"][(bid,cid,year,month)] += 1
        if len(cell["examples"]) < 8 and not any(e["bird"]==bid for e in cell["examples"]):
            cell["examples"].append({"id": row["id"], "bird": bid, "city": cid, "year": year, "month": month})
        total[bid] += 1
        datasets[row["dataset"]] += 1
        years.append(year)
        known_months += bool(month)
    for cell in cells.values():
        cell["events"] = [[*key,count] for key,count in sorted(cell.pop("_events").items())]
    selected = []
    for bid, count in sorted(total.items(), key=lambda row: (-row[1],row[0])):
        bird = birds[bid]
        filenames = [Path(bird.get("image", "")).name, bid+".jpg", bid+".png", bid+".svg"]
        image = next(("/static/img/birds/"+name for name in filenames if name and (ROOT/"public/static/img/birds"/name).is_file()), "/static/img/placeholder.svg")
        selected.append({"id": bid, "name": bird["name"], "latin": bird["latin"], "protection": bird.get("protection", ""),
                         "image": image, "count": count, "profile_url": "/guide/"+bid})
    dataset_metadata = {d["key"]:d for d in archive.get("datasets", [])}
    source_datasets = []
    for key, count in datasets.most_common():
        info = dataset_metadata.get(key, {})
        source_datasets.append({"key": key, "title": info.get("title", "GBIF 数据集 "+str(key)), "doi": info.get("doi"),
                                "url": "https://www.gbif.org/dataset/"+str(key), "license": info.get("license"), "count": count})
    result = {"schema_version": 2, "built_on": datetime.now(timezone.utc).isoformat(),
              "source": {"name": "GBIF.org 公开人工观测记录", "url": "https://www.gbif.org/occurrence/search", "retrieved_on": archive["retrieved_on"],
                         "event_dates_available": True, "unit": "按 GBIF 记录ID去重的人工观测记录；同址不同日期或记录ID分别计数，不代表个体数",
                         "query": archive["query"], "cohort_note": archive["cohort_note"], "datasets": source_datasets,
                         "omitted_candidates": archive.get("omitted_candidates", [])},
              "coverage": {"records": len(archive["records"]), "species": len(selected), "grid_count": len(cells),
                           "distinct_coordinate_pairs": archive["distinct_coordinate_pairs"], "year_min": min(years), "year_max": max(years),
                           "known_month_records": known_months, "candidate_species": archive["candidate_species"], "bbox_records": archive["bbox_records"]},
              "boundary": {"name": "阿里云 DataV.GeoAtlas · 安徽16市", "url": BOUNDARY_URL, "crs": "GCJ-02",
                           "sha256": hashlib.sha256(boundary_file.read_bytes()).hexdigest()},
              "method": {"grid_km": GRID_KM, "origin": [114,29], "reference_latitude": 32,
                         "projection": "Local equirectangular approximation; GBIF WGS84 → GCJ-02 before containment",
                         "scope_note": "GBIF科学名精确匹配本站国家一、二级保护鸟类后裁切安徽省界；不是完整名录或系统普查。"},
              "archive": {"path": "data/anhui-gbif-records.json.gz", "sha256": hashlib.sha256(archive_file.read_bytes()).hexdigest(), "exact_coordinates_published": False},
              "species": selected, "cities": cities, "cells": sorted(cells.values(), key=lambda c:(c["row"],c["col"])), "audit": archive["audit"]}
    (OUT/"observations.json").write_text(json.dumps(result,ensure_ascii=False,separators=(",", ":")),encoding="utf-8")
    print(json.dumps(result["coverage"],ensure_ascii=False))
    return result


def build(refresh_records=False, use_complete_species=False):
    return build_current(refresh_records, use_complete_species)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-boundary", action="store_true")
    parser.add_argument("--refresh-records", action="store_true", help="Build a sanitized archive from the completed acquisition cache")
    parser.add_argument("--use-complete-species", action="store_true", help="Explicitly omit failed taxa, retain only fully paginated species and disclose omissions")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.refresh_boundary:
        with urlopen(BOUNDARY_URL, timeout=30) as response:
            geometry = json.load(response)
        (OUT/"anhui-cities.geojson").write_text(json.dumps(geometry, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    build(args.refresh_records, args.use_complete_species)
