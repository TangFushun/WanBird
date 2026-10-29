"""Run with: python -m unittest discover -s tests -p test_anhui_traces.py"""
from collections import Counter
import hashlib
import gzip
import json
import math
from pathlib import Path
import unittest

from scripts.build_anhui_traces import contains, in_ring, wgs84_to_gcj02, project

ROOT = Path(__file__).resolve().parents[1]


class ProvinceClippingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "public/static/data/traces/observations.json").read_text(encoding="utf-8"))
        cls.boundary = json.loads((ROOT / "public/static/data/traces/anhui-cities.geojson").read_text(encoding="utf-8"))

    def test_holes_and_shared_edges(self):
        shape = {"type": "Polygon", "coordinates": [
            [[0,0],[4,0],[4,4],[0,4],[0,0]],
            [[1,1],[2,1],[2,2],[1,2],[1,1]],
        ]}
        self.assertTrue(contains((3,3), shape))
        self.assertFalse(contains((1.5,1.5), shape))
        self.assertTrue(in_ring((0,2), shape["coordinates"][0]))
        self.assertFalse(contains((5,2), shape))

    def test_beijing_coordinate_conversion_reference(self):
        lon, lat = wgs84_to_gcj02(116.404, 39.915)
        self.assertAlmostEqual(lon, 116.41024449916938, places=8)
        self.assertAlmostEqual(lat, 39.91640428150164, places=8)

    def test_real_province_shape_not_just_a_bounding_box(self):
        def cities_at(wgs):
            p = wgs84_to_gcj02(*wgs)
            return [str(f["properties"]["adcode"]) for f in self.boundary["features"] if contains(p, f["geometry"])]
        self.assertEqual(cities_at((117.2272, 31.8206)), ["340100"])  # Hefei
        self.assertEqual(cities_at((118.7969, 32.0603)), [])  # Nanjing is inside the bounding rectangle, outside Anhui.
        self.assertEqual(cities_at((120.1551, 30.2741)), [])  # Hangzhou

    def test_archive_fingerprints_and_accounting(self):
        for row in self.data["audit"]:
            source_file=ROOT/"_tools/anhui-gbif"/(row["bird_id"]+".json.gz")
            if source_file.exists():
                self.assertEqual(hashlib.sha256(source_file.read_bytes()).hexdigest(),row["input_sha256"])
            self.assertEqual(row["api_count"],sum(row["counts"].values()))
        boundary = (ROOT / "public/static/data/traces/anhui-cities.geojson").read_bytes()
        self.assertEqual(hashlib.sha256(boundary).hexdigest(), self.data["boundary"]["sha256"])
        archive=(ROOT/self.data["archive"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(archive).hexdigest(),self.data["archive"]["sha256"])
        content=json.loads(gzip.decompress(archive))
        records=content["records"]
        self.assertEqual(len(records),self.data["coverage"]["records"])
        self.assertEqual(len({r["id"] for r in records}),len(records))
        self.assertTrue(all('decimalLongitude' not in row and 'decimalLatitude' not in row for row in records))

    def test_independent_shapely_clipping_matches_published_grid_counts(self):
        try:
            from shapely.geometry import Point, shape
        except ImportError:
            self.skipTest("Optional independent geometry cross-check requires shapely")
        features = {str(f["properties"]["adcode"]):shape(f["geometry"]) for f in self.boundary["features"]}
        expected = Counter()
        with gzip.open(ROOT/self.data["archive"]["path"],"rt",encoding="utf-8") as f:
            records=json.load(f)["records"]
        sources={}
        for audit in self.data["audit"]:
            file=ROOT/"_tools/anhui-gbif"/(audit["bird_id"]+".json.gz")
            if not file.exists():
                self.skipTest("Raw GPS is kept only in the ignored acquisition cache")
            with gzip.open(file,"rt",encoding="utf-8") as f:
                sources[audit["bird_id"]]={str(r["key"]):r for r in json.load(f)["records"]}
        for row in records:
            raw=sources[row["bird"]][row["id"]]
            transformed=wgs84_to_gcj02(raw["decimalLongitude"],raw["decimalLatitude"])
            self.assertTrue(features[row["city"]].covers(Point(*transformed)))
            x,y=project(*transformed)
            self.assertEqual(row["cell"],f"{math.floor(x/20)}:{math.floor(y/20)}")
            expected[(row["cell"],row["bird"],row["city"])] += 1
        actual = Counter()
        for cell in self.data["cells"]:
            for bid, cities in cell["counts"].items():
                for cid, n in cities.items():
                    actual[(cell["id"], bid, cid)] = n
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
