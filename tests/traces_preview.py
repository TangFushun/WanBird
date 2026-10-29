"""Isolated browser QA: synthetic dates/counts, never imported by production Flask.

Run: python tests/traces_preview.py, then http://127.0.0.1:5081/traces
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app, BIRDS
from flask import request, jsonify

NOW=datetime.now(timezone.utc).isoformat()
IDS=['oriental-stork','scaly-sided-merganser','hooded-crane']
birds={b['id']:b for b in BIRDS}
boundary=json.loads((Path(app.static_folder)/'data/traces/anhui-cities.geojson').read_text(encoding='utf-8'))
cities=[]
for f in boundary['features']:
 p=f['properties']
 coords=[point for poly in (f['geometry']['coordinates'] if f['geometry']['type']=='MultiPolygon' else [f['geometry']['coordinates']]) for ring in poly for point in ring]
 cities.append({'id':str(p['adcode']),'name':p['name'],'center':p['centroid'],'bbox':[min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]})
events=[['oriental-stork','340100',2020,1,2],['scaly-sided-merganser','340100',2021,2,3],['hooded-crane','340100',2021,0,4]]
other=[['oriental-stork','341700',2022,1,5],['hooded-crane','341700',2021,12,1]]
def cell(id,events):
 counts={}
 for bid,cid,y,m,n in events:
  counts.setdefault(bid,{})[cid]=counts.setdefault(bid,{}).get(cid,0)+n
 col,row=map(int,id.split(':'))
 return {'id':id,'col':col,'row':row,'counts':counts,'events':events,'examples':[]}
fixture={'schema_version':2,'built_on':NOW,'source':{'retrieved_on':NOW,'datasets':[]},
 'coverage':{'year_min':2020,'year_max':2022,'records':15,'species':3,'distinct_coordinate_pairs':2},
 'method':{'origin':[114,29],'reference_latitude':32,'grid_km':20},'cities':cities,
 'species':[{'id':bid,'name':birds[bid]['name'],'latin':birds[bid]['latin'],'protection':birds[bid]['protection'],'image':'/static/img/birds/'+bid+'.png','count':n,'profile_url':'/guide/'+bid} for bid,n in zip(IDS,[7,3,5])],
 'cells':[cell('15:15',events),cell('16:7',other)]}
@app.before_request
def qa_data():
 if request.path=='/static/data/traces/observations.json':
  return jsonify(fixture)
@app.after_request
def mark_synthetic(response):
 if request.path=='/traces':
  text=response.get_data(as_text=True)
  response.set_data(text.replace('皖羽踪迹<span>','可视化交互测试 · 模拟数据<span>'))
 return response
if __name__=='__main__':
 app.run(host='127.0.0.1',port=5081,debug=False,use_reloader=False)
