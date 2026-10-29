import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fetch_anhui_observations as fetcher


class PaginationTests(unittest.TestCase):
    def test_species_key_remains_constant_across_pages_and_record_ids(self):
        calls=[]
        def api(path, params):
            if path=='/species/match':
                return {'rank':'SPECIES','matchType':'EXACT','usageKey':123}
            calls.append(dict(params))
            offset=params['offset']
            rows=[{'key':987654+offset+i} for i in range(min(params['limit'],301-offset))]
            return {'count':301,'endOfRecords':offset+params['limit']>=301,'results':rows}
        with tempfile.TemporaryDirectory() as temp, patch.object(fetcher,'CACHE',Path(temp)), patch.object(fetcher,'get_json',side_effect=api),patch.object(fetcher.time,'sleep'):
            result=fetcher.fetch_bird({'id':'test','name':'测试鸟','latin':'Testus birdus'},['Testus birdus'])
            self.assertEqual([c['taxonKey'] for c in calls],[123,123,123,123])
            self.assertEqual(len(result['records']),301)
            self.assertTrue(result['complete'])

    def test_truncated_or_changed_pagination_is_not_published_as_complete(self):
        def api(path,params):
            if path=='/species/match':
                return {'rank':'SPECIES','matchType':'EXACT','usageKey':123}
            if params['offset']==0:
                return {'count':301,'endOfRecords':False,'results':[{'key':i} for i in range(params['limit'])]}
            return {'count':0,'endOfRecords':True,'results':[]}
        with tempfile.TemporaryDirectory() as temp,patch.object(fetcher,'CACHE',Path(temp)),patch.object(fetcher,'get_json',side_effect=api),patch.object(fetcher.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'count changed'):
                fetcher.fetch_bird({'id':'test','name':'测试鸟','latin':'Testus birdus'},['Testus birdus'])
            self.assertFalse((Path(temp)/'test.json.gz').exists())


if __name__=='__main__':
    unittest.main()
