const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../public/static/js/traces-model.js');

const fixture = {
  species: [{ id: 'a', name: '鸟甲' }, { id: 'b', name: '鸟乙' }, { id: 'c', name: '鸟,丙' }],
  cities: [{ id: '1', name: '一市' }, { id: '2', name: '二市' }, { id: '3', name: '三市' }],
  cells: [
    { id: 'cross-border', counts: { a: { 1: 2, 2: 3 }, b: { 2: 4 } }, events: [['a','1',2020,1,2],['a','2',2021,2,3],['b','2',2021,0,4]] },
    { id: 'second', counts: { a: { 1: 5 }, c: { 3: 1 } }, events: [['a','1',2022,1,5],['c','3',2021,12,1]] },
  ],
};

test('a grid crossing a city border contributes only its selected-city samples', () => {
  assert.equal(M.tally(fixture.cells, '', '2').total, 7);
  assert.equal(M.tally(fixture.cells, 'a', '2').total, 3);
  assert.equal(M.tally(fixture.cells, 'a', '2').gridCount, 1);
  assert.deepEqual(M.tally(fixture.cells, '', '2').byBird, { a: 3, b: 4 });
});

test('reset and zero-result combinations preserve the original data', () => {
  const before = JSON.stringify(fixture);
  assert.equal(M.tally(fixture.cells, 'b', '1').total, 0);
  assert.equal(M.tally(fixture.cells, 'b', '1').speciesCount, 0);
  assert.equal(M.tally(fixture.cells, '', '').total, 15);
  assert.deepEqual(M.tally(fixture.cells, '', '').byCity, { 1: 7, 2: 7, 3: 1 });
  assert.equal(JSON.stringify(fixture), before);
});

test('color thresholds remain fixed when the selected population changes', () => {
  assert.equal(M.color(0), '#173c35');
  assert.equal(M.color(1), '#28605a');
  assert.equal(M.color(2), M.color(9));
  assert.notEqual(M.color(9), M.color(10));
  assert.notEqual(M.color(49), M.color(50));
  assert.notEqual(M.color(199), M.color(200));
});

test('CSV respects both filters, retains zero rows, and escapes punctuation', () => {
  const scoped = M.csv(fixture, 'b', '1');
  assert.equal(scoped.charCodeAt(0), 0xFEFF);
  assert.equal(scoped.split('\r\n').length, 2);
  assert.match(scoped, /"鸟乙","一市","0"/);
  assert.doesNotMatch(scoped, /"二市"/);
  assert.match(M.csv(fixture, 'c', '3'), /"鸟,丙","三市","1"/);
});

test('committed snapshot conserves every sample across grids, species and cities', () => {
  const data = JSON.parse(fs.readFileSync(path.join(__dirname, '../public/static/data/traces/observations.json'), 'utf8'));
  const all = M.tally(data.cells, '', '');
  assert.equal(data.cities.length, 16);
  assert.equal(all.total, data.audit.reduce((sum, row) => sum + (row.counts?.included || 0), 0));
  for (const bird of data.species) {
    const scoped = M.tally(data.cells, bird.id, '');
    assert.equal(scoped.total, bird.count);
    assert.equal(Object.values(scoped.byCity).reduce((a, b) => a + b, 0), bird.count);
  }
  for (const city of data.cities) {
    const scoped = M.tally(data.cells, '', city.id);
    assert.equal(scoped.total, all.byCity[city.id] || 0);
    assert.equal(Object.values(scoped.byBird).reduce((a, b) => a + b, 0), scoped.total);
  }
  assert.equal(all.total,data.coverage.records);
  assert.equal(all.knownMonth,data.coverage.known_month_records);
  assert.ok(Number.isFinite(Date.parse(data.source.retrieved_on)));
  assert.equal(data.source.event_dates_available, true);
});

test('year, month, protection and city filters intersect without losing unknown months',()=>{
  const year=M.tally(fixture.cells,'','',{from:2021,to:2021});
  assert.equal(year.total,8);
  assert.equal(year.knownMonth,4);
  assert.equal(year.total-year.knownMonth,4);
  assert.equal(M.tally(fixture.cells,'','',{from:2021,to:2021,month:2}).total,3);
  assert.equal(M.tally(fixture.cells,'','2',{from:2021,to:2021,month:12}).total,0);
  assert.equal(M.tally(fixture.cells,'','',{birds:['a','b']}).total,14);
});

test('a selected grid drives composition, seasonal and annual series with the same scope',()=>{
  const selected=[fixture.cells[0]];
  const detail=M.tally(selected,'','',{from:2021,to:2021,month:2});
  assert.deepEqual(detail.byBird,{a:3});
  assert.equal(detail.total,3);
  const seasonal=M.tally(selected,'','',{from:2021,to:2021});
  assert.equal(seasonal.byMonth[2],3);
  assert.equal(seasonal.total,7);
  const annual=M.tally(selected,'','',{month:2});
  assert.deepEqual(annual.byYear,{2021:3});
});

test('CSV exports exactly the selected grid and time slice',()=>{
  const output=M.csv(fixture,'a','2',{from:2021,to:2021,month:2},'cross-border');
  assert.match(output,/"鸟甲","二市","3","2021–2021","2"/);
  assert.equal(output.split('\r\n').length,2);
});
