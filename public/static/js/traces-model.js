/* Shared, DOM-free aggregation for the Anhui atlas and its regression checks. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TracesModel = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function tally(cells, birdId, cityId, filters) {
    filters = filters || {};
    var result = { total: 0, byBird: {}, byCity: {}, byYear: {}, byMonth: Array(13).fill(0), cells: {}, gridCount: 0, speciesCount: 0, knownMonth: 0 };
    cells.forEach(function (cell) {
      var n = 0;
      function add(bid, cid, year, month, count) {
        if (birdId && bid !== birdId) return;
        if (cityId && cid !== cityId) return;
        if (filters.birds && filters.birds.indexOf(bid) === -1) return;
        if (filters.from && year < filters.from || filters.to && year > filters.to) return;
        if (filters.month && month !== filters.month) return;
        if (!Number.isSafeInteger(count) || count <= 0) return;
        n += count;
        result.byBird[bid] = (result.byBird[bid] || 0) + count;
        result.byCity[cid] = (result.byCity[cid] || 0) + count;
        if (year) result.byYear[year] = (result.byYear[year] || 0) + count;
        if (month >= 1 && month <= 12) { result.byMonth[month] += count; result.knownMonth += count; }
      }
      if (Array.isArray(cell.events)) {
        cell.events.forEach(function (event) { add.apply(null, event); });
      } else {
        Object.keys(cell.counts).forEach(function (bid) {
          Object.keys(cell.counts[bid]).forEach(function (cid) { add(bid, cid, 0, 0, cell.counts[bid][cid]); });
        });
      }
      result.cells[cell.id] = n;
      result.total += n;
      if (n) result.gridCount++;
    });
    result.speciesCount = Object.keys(result.byBird).length;
    return result;
  }
  function color(count) {
    if (count >= 200) return '#f6c868';
    if (count >= 50) return '#b1ad65';
    if (count >= 10) return '#508b71';
    if (count >= 2) return '#34766a';
    if (count >= 1) return '#28605a';
    return '#173c35';
  }
  function csv(data, birdId, cityId, filters, cellId) {
    filters = filters || {};
    function quote(s) { return '"' + String(s).replace(/"/g, '""') + '"'; }
    var rows = [['鸟种', '地市', '观测记录数', '年份范围', '月份', '统计口径']];
    data.species.filter(function (b) { return (!birdId || b.id === birdId) && (!filters.birds || filters.birds.indexOf(b.id) !== -1); }).forEach(function (bird) {
      var counts = tally(data.cells.filter(function (c) { return !cellId || c.id === cellId; }), bird.id, cityId, filters);
      data.cities.filter(function (c) { return !cityId || c.id === cityId; }).forEach(function (city) {
        rows.push([bird.name, city.name, counts.byCity[city.id] || 0, filters.from ? filters.from+'–'+filters.to : '全部年份', filters.month || '全部月份', 'GBIF记录ID去重；同址不同记录分别计数，不代表个体数量']);
      });
    });
    return '\uFEFF' + rows.map(function (row) { return row.map(quote).join(','); }).join('\r\n');
  }
  return { tally: tally, color: color, csv: csv };
});
