"""Acquire public GBIF records for protected birds in the Anhui bounding box.

An explicit network maintenance command, never executed by Flask. Raw coordinates
stay in the ignored local cache; the build command publishes only 20-km aggregates.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "_tools/anhui-gbif"
BASE = "https://api.gbif.org/v1"
PAGE_SIZE = 100
QUERY = {"taxonKey": 212, "country": "CN", "hasCoordinate": "true",
         "hasGeospatialIssue": "false", "decimalLatitude": "29.3,34.8",
         "decimalLongitude": "114.8,119.7", "year": "1980,2026",
         "occurrenceStatus": "PRESENT", "basisOfRecord": "HUMAN_OBSERVATION"}


def get_json(path, params=None):
    for attempt in range(3):
        try:
            url = BASE+path + ("?"+urlencode(params,doseq=True) if params else "")
            req = Request(url, headers={"User-Agent": "WanBird-educational-atlas/2.0", "Accept-Encoding": "gzip"})
            with urlopen(req,timeout=25) as response:
                body=response.read()
                if response.headers.get("Content-Encoding")=="gzip":
                    body=gzip.decompress(body)
                return json.loads(body)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            if isinstance(error, HTTPError) and error.code < 500 and error.code != 429:
                raise
            if attempt == 2:
                raise
            print("retry", path, attempt+1, type(error).__name__, flush=True)
            time.sleep(min(2**attempt, 8))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def discover():
    path = CACHE/"facets.json"
    if path.exists():
        return read_json(path)
    # GBIF returns accepted names with authors. Match the first two words to the
    # site's binomials, not translated or approximate names.
    d = get_json("/occurrence/search", {**QUERY, "limit": 0, "facet": "scientificName", "facetLimit": 1000})
    write_json(path, {"retrieved_on": datetime.now(timezone.utc).isoformat(), "query": QUERY, **d})
    return read_json(path)


def fetch_bird(bird, scientific_name):
    path = CACHE/(bird["id"]+".json.gz")
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            existing = json.load(f)
        if existing.get("complete") and len(existing.get("records", [])) == existing.get("api_count") and existing.get("species_key") == (existing.get("taxon_match", {}).get("acceptedUsageKey") or existing.get("taxon_match", {}).get("usageKey")):
            return existing
    match_path = CACHE / (bird["id"]+".match.json")
    if match_path.exists():
        match = read_json(match_path)
    else:
        match = get_json("/species/match", {"name": bird["latin"], "rank": "SPECIES", "strict": "true"})
        write_json(match_path, match)
    if match.get("rank") != "SPECIES" or match.get("matchType") != "EXACT":
        raise RuntimeError("Species-level exact taxonomic match required")
    species_key = match.get("acceptedUsageKey") or match["usageKey"]
    records, seen, offset, query_count = [], set(), 0, None
    queries = []
    while True:
        params = {**QUERY, "taxonKey": species_key, "limit": PAGE_SIZE, "offset": offset}
        page_folder=CACHE/"pages"
        page_folder.mkdir(exist_ok=True)
        fingerprint=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:20]
        page_path=page_folder/(bird["id"]+"-"+fingerprint+".json.gz")
        if page_path.exists():
            with gzip.open(page_path,"rt",encoding="utf-8") as f:
                d=json.load(f)
        else:
            d = get_json("/occurrence/search", params)
            with gzip.open(page_path,"wt",encoding="utf-8") as f:
                json.dump(d,f,ensure_ascii=False,separators=(',',':'))
        queries.append({"offset": offset, "returned": len(d.get("results", [])), "count": d.get("count")})
        if query_count is None:
            query_count = d["count"]
            print("query", bird["name"], query_count, flush=True)
            if query_count > 20000:
                raise RuntimeError("Unexpectedly broad species query")
        for row in d.get("results", []):
            record_id = str(row["key"])
            if record_id in seen:
                continue
            seen.add(record_id)
            records.append({k: row.get(k) for k in (
                "key", "speciesKey", "species", "scientificName", "decimalLongitude", "decimalLatitude",
                "year", "month", "day", "eventDate", "datasetKey", "license", "basisOfRecord",
                "occurrenceID", "coordinateUncertaintyInMeters", "issues", "recordedBy", "references")})
        if d.get("count") != query_count:
            raise RuntimeError("GBIF result count changed during pagination; retry this species")
        if d.get("endOfRecords") or offset+PAGE_SIZE >= d["count"]:
            break
        offset += PAGE_SIZE
        if offset+PAGE_SIZE > 100000:
            raise RuntimeError("GBIF search limit exceeded; use an authenticated bulk download")
        time.sleep(.2)
    if len(records) != query_count:
        raise RuntimeError("Incomplete or duplicate pages; refusing to mark this download complete")
    result = {"bird_id": bird["id"], "scientific_name_query": scientific_name, "species_key": species_key, "taxon_match": match,
              "retrieved_on": datetime.now(timezone.utc).isoformat(), "query": {**QUERY, "taxonKey": species_key},
              "api_count": query_count, "pages": queries, "complete": True, "records": records}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    return result


def main(probe=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    inventory = discover()
    facets = inventory.get("facets", [])
    if not facets:
        raise RuntimeError("GBIF scientificName facet was unavailable")
    counts = facets[0].get("counts", [])
    print(json.dumps({"bbox_human_observations": inventory["count"], "facet_values": len(counts),
                      "examples": counts[:3]}, ensure_ascii=False), flush=True)
    local = read_json(ROOT/"data/birds.json")
    local = {b["latin"]: b for b in local if b.get("protection") in ("国家一级保护动物", "国家二级保护动物")}
    grouped = {}
    for row in counts:
        binomial = " ".join(row["name"].split()[:2])
        if binomial in local:
            bird = local[binomial]
            group = grouped.setdefault(bird["id"], [bird, [], 0])
            group[1].append(row["name"])
            group[2] += row["count"]
    matched = sorted(grouped.values(), key=lambda row: -row[2])
    write_json(CACHE/"candidates.json", [{"id": b["id"], "name": b["name"], "scientific_name": n, "bbox_count": c} for b,n,c in matched])
    print(json.dumps({"matched_protected_taxa": len(matched), "bbox_records": sum(c for b,n,c in matched),
                      "candidates": [{"name": b["name"], "count": c} for b,n,c in matched[:15]]}, ensure_ascii=False), flush=True)
    if probe:
        return
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_bird, bird, name): bird for bird,name,count in matched}
        for future in as_completed(jobs):
            bird = jobs[future]
            try:
                result = future.result()
                results.append({"bird_id": bird["id"], "records": len(result["records"]), "api_count": result["api_count"],
                                "retrieved_on": result["retrieved_on"], "file": bird["id"]+".json.gz"})
                print(bird["name"], len(result["records"]), flush=True)
            except Exception as error:
                errors.append({"bird_id": bird["id"], "error": str(error)})
                print("FAILED", bird["id"], type(error).__name__, flush=True)
    manifest = {"retrieved_on": datetime.now(timezone.utc).isoformat(), "query": QUERY,
                "bbox_count_all_birds": inventory["count"], "matched_taxa": len(matched),
                "selection": "GBIF accepted scientific-name facet exactly matched to the site's national I/II protected bird binomials; not a complete Anhui checklist",
                "files": sorted(results, key=lambda r: r["bird_id"]), "errors": errors}
    write_json(CACHE/"manifest.json", manifest)
    print(json.dumps({"complete_species": len(results), "records": sum(r["records"] for r in results), "errors": len(errors)}, ensure_ascii=False), flush=True)
    if errors:
        raise SystemExit(1)


def metadata():
    manifest_path = CACHE/"manifest.json"
    manifest = read_json(manifest_path)
    keys = set()
    for row in manifest["files"]:
        with gzip.open(CACHE/row["file"], "rt", encoding="utf-8") as f:
            records = json.load(f)["records"]
        keys.update(r["datasetKey"] for r in records if r.get("datasetKey"))
    datasets = []
    for key in sorted(keys):
        target = CACHE/("dataset-"+key+".json")
        if target.exists():
            info = read_json(target)
        else:
            info = get_json("/dataset/"+key)
            write_json(target, info)
        datasets.append({k: info.get(k) for k in ("key", "title", "doi", "license", "publishingOrganizationKey")})
        print("dataset", info.get("title"), flush=True)
    manifest["datasets"] = datasets
    write_json(manifest_path, manifest)


def finalize_cache():
    """Publish an honest inventory of fully downloaded taxa after network failures."""
    manifest_path=CACHE/'manifest.json'
    previous=read_json(manifest_path) if manifest_path.exists() else {}
    old_errors={r['bird_id']:r['error'] for r in previous.get('errors',[])}
    candidates=read_json(CACHE/'candidates.json')
    complete,errors=[],[]
    for candidate in candidates:
        bid=candidate['id']
        try:
            with gzip.open(CACHE/(bid+'.json.gz'),'rt',encoding='utf-8') as f:
                row=json.load(f)
            key=row.get('taxon_match',{}).get('acceptedUsageKey') or row.get('taxon_match',{}).get('usageKey')
            if not row.get('complete') or len(row['records'])!=row['api_count'] or row.get('species_key')!=key:
                raise ValueError('Incomplete record pages')
            complete.append({'bird_id':bid,'records':len(row['records']),'api_count':row['api_count'],'retrieved_on':row['retrieved_on'],'file':bid+'.json.gz'})
        except (OSError,EOFError,ValueError,KeyError):
            errors.append({'bird_id':bid,'error':old_errors.get(bid,'Network acquisition did not complete; partial pages excluded')})
    manifest={**previous,'retrieved_on':max(r['retrieved_on'] for r in complete),'query':QUERY,
              'matched_taxa':len(candidates),'files':sorted(complete,key=lambda r:r['bird_id']),'errors':errors}
    write_json(manifest_path,manifest)
    print(json.dumps({'complete_species':len(complete),'records':sum(r['records'] for r in complete),'omitted_candidates':[r['bird_id'] for r in errors]}),flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--finalize-cache", action="store_true", help="Inventory only fully downloaded taxa; disclose incomplete candidates")
    args=parser.parse_args()
    if args.finalize_cache:
        finalize_cache()
    elif args.metadata_only:
        metadata()
    else:
        main(args.probe)
