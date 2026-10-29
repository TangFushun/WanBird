/* Anhui-only linked map. All geometry and statistics are local; no map SDK or tile service. */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var M = window.TracesModel;
  var NS = 'http://www.w3.org/2000/svg';
  var data, boundary, projection, state = { bird: '', city: '', mode: 'grid', cell: null, protection: '', from: 0, to: 0, month: 0, expanded: false };
  var cityNodes = {}, gridNodes = {}, borderNodes = {}, labelNodes = {};
  var view = { zoom: 1, x: 0, y: 0 }, activeRequest = null, loadVersion = 0;
  var current, province, detail, drag = null, suppressClick = false;
  var svg = $('trMap'), wrap = $('trMapWrap');
  var tip = document.createElement('div');
  tip.className = 'tr-tooltip'; tip.hidden = true; wrap.appendChild(tip);

  function node(tag, attrs, text) {
    var el = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { el.setAttribute(key, attrs[key]); });
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function textEl(tag, text, cls) {
    var el = document.createElement(tag); el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function polys(geometry) {
    return geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  }
  function km(lon, lat) {
    return [(lon - data.method.origin[0]) * 111.32 * Math.cos(data.method.reference_latitude * Math.PI / 180),
      (lat - data.method.origin[1]) * 111.32];
  }
  function mapPoint(xy) {
    var p = km(xy[0], xy[1]); return projection.xy(p[0], p[1]);
  }
  function path(geometry) {
    return polys(geometry).map(function (poly) {
      return poly.map(function (ring) {
        return ring.map(function (p, i) {
          var xy = mapPoint(p); return (i ? 'L' : 'M') + xy[0].toFixed(2) + ',' + xy[1].toFixed(2);
        }).join('') + 'Z';
      }).join('');
    }).join('');
  }
  function cityName(id) { return data.cities.find(function (c) { return c.id === id; }).name; }
  function birdName(id) { return data.species.find(function (b) { return b.id === id; }).name; }
  function filters(overrides) {
    return Object.assign({ from: state.from, to: state.to, month: state.month,
      birds: state.protection ? data.species.filter(function (b) { return b.protection === state.protection; }).map(function (b) { return b.id; }) : null }, overrides || {});
  }
  function selectedCells() { return state.cell ? data.cells.filter(function (c) { return c.id === state.cell; }) : data.cells; }
  function scopeName() { return state.cell ? '网格 ' + state.cell : state.city ? cityName(state.city) : '安徽全省'; }
  function format(n) { return n.toLocaleString('zh-CN'); }
  function licenseLabel(value) {
    var text=String(value||'').toLowerCase(),version=text.match(/(\d+)[._](\d+)/),suffix=version?' '+version[1]+'.'+version[2]:'';
    if(text.indexOf('by-nc')>=0||text.indexOf('by_nc')>=0)return'CC BY-NC'+suffix;
    if(text.indexOf('by/')>=0||text.indexOf('by_')>=0)return'CC BY'+suffix;
    if(text.indexOf('zero')>=0||text.indexOf('cc0')>=0)return'CC0'+suffix;
    return'许可见原数据集';
  }
  function setYears(from, to) {
    state.from = Math.min(from, to); state.to = Math.max(from, to); render();
  }
  function keyboardClick(el, action) {
    el.addEventListener('click', function () { if (!suppressClick) action(); });
    el.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
    });
  }
  function showTip(el, getLines) {
    function show(event) {
      if (drag) return;
      var lines = getLines();
      tip.replaceChildren(textEl('div', lines[0]), textEl('small', lines[1])); tip.hidden = false;
      var box = wrap.getBoundingClientRect(), bounds = el.getBoundingClientRect();
      var x = event.clientX === undefined ? bounds.x + bounds.width / 2 : event.clientX;
      var y = event.clientY === undefined ? bounds.y + bounds.height / 2 : event.clientY;
      tip.style.left = Math.max(8, Math.min(box.width - tip.offsetWidth - 8, x - box.left + 12)) + 'px';
      tip.style.top = Math.max(8, Math.min(box.height - tip.offsetHeight - 8, y - box.top + 12)) + 'px';
    }
    el.addEventListener('pointermove', show);
    el.addEventListener('focus', show);
    el.addEventListener('pointerleave', function () { tip.hidden = true; });
    el.addEventListener('blur', function () { tip.hidden = true; });
  }
  function buildMap() {
    var points = [];
    boundary.features.forEach(function (feature) {
      polys(feature.geometry).forEach(function (poly) {
        poly.forEach(function (ring) { ring.forEach(function (p) { points.push(km(p[0], p[1])); }); });
      });
    });
    var xs = points.map(function (p) { return p[0]; }), ys = points.map(function (p) { return p[1]; });
    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    var ymin = Math.min.apply(null, ys), ymax = Math.max.apply(null, ys);
    var scale = Math.min(495 / (xmax - xmin), 614 / (ymax - ymin));
    projection = { scale: scale, xy: function (x, y) { return [320 + (x - (xmin + xmax) / 2) * scale, 347 - (y - (ymin + ymax) / 2) * scale]; } };
    ['trCityShapes', 'trCityBorders', 'trCityLabels', 'trGridShapes', 'trScale'].forEach(function (id) { $(id).replaceChildren(); });
    cityNodes = {}; gridNodes = {}; borderNodes = {}; labelNodes = {};
    $('trClipShape').setAttribute('d', boundary.features.map(function (f) { return path(f.geometry); }).join(''));
    boundary.features.forEach(function (feature) {
      var id = String(feature.properties.adcode), shape = path(feature.geometry);
      var p = node('path', { d: shape, 'class': 'tr-city-shape', 'fill-rule': 'evenodd', tabindex: 0, role: 'button', 'data-city': id });
      keyboardClick(p, function () { chooseCity(state.city === id ? '' : id); });
      showTip(p, function () { return [cityName(id) + ' · ' + format(province.byCity[id] || 0) + ' 条记录', '点击后，鸟种构成和时间图同步更新']; });
      cityNodes[id] = p; $('trCityShapes').appendChild(p);
      var border = node('path', { d: shape, 'class': 'tr-city-border', 'fill-rule': 'evenodd' });
      borderNodes[id] = border; $('trCityBorders').appendChild(border);
      var city = data.cities.find(function (c) { return c.id === id; });
      var xy = mapPoint(city.center);
      var label = node('text', { x: xy[0], y: xy[1], 'class': 'tr-city-label' }, city.name.replace(/市$/, ''));
      labelNodes[id] = label; $('trCityLabels').appendChild(label);
    });
    data.cells.forEach(function (cell) {
      var size = data.method.grid_km, p = projection.xy(cell.col * size, (cell.row + 1) * size);
      var rect = node('rect', { x: p[0], y: p[1], width: size * scale, height: size * scale, 'class': 'tr-grid',
        tabindex: 0, role: 'button', 'data-cell': cell.id });
      keyboardClick(rect, function () { state.cell = state.cell === cell.id ? null : cell.id; render(); });
      showTip(rect, function () { return ['网格 ' + cell.id + ' · ' + format(current.cells[cell.id] || 0) + ' 条记录', '点击后，鸟种构成和时间图同步更新']; });
      gridNodes[cell.id] = rect; $('trGridShapes').appendChild(rect);
    });
    $('trScale').appendChild(node('path', { d: 'M32,648v5h' + (50 * scale).toFixed(2) + 'v-5' }));
    $('trScale').appendChild(node('text', { x: 32, y: 674 }, '约50公里 · 全省视图'));
    applyView();
  }
  function renderSelection() {
    var box = $('trSelection'); box.replaceChildren(textEl('span', '⌖', 'tr-selection-mark'));
    var body = document.createElement('div'); box.appendChild(body);
    body.appendChild(textEl('h3', scopeName() + ' · ' + format(detail.total) + ' 条记录 · ' + detail.speciesCount + ' 种鸟'));
    if(!state.cell)body.appendChild(textEl('p','点击有颜色的网格，右侧图表和下方年份曲线会同步切换到该网格。'));
    if(state.cell&&detail.total){
      var composition=textEl('div','','tr-mini-composition');composition.setAttribute('role','group');composition.setAttribute('aria-label','选中网格鸟种构成概览');
      var ranked=Object.keys(detail.byBird).sort(function(a,b){return detail.byBird[b]-detail.byBird[a];}).slice(0,4);
      var peak=detail.byBird[ranked[0]];
      ranked.forEach(function(id){var row=textEl('div','','tr-mini-row'),track=textEl('span','','tr-mini-track'),fill=document.createElement('i');fill.style.width=detail.byBird[id]/peak*100+'%';track.appendChild(fill);row.append(textEl('span',birdName(id)),track,textEl('b',format(detail.byBird[id])));composition.appendChild(row);});
      body.appendChild(composition);
      var more=textEl('a','查看全部鸟种与月份图 ↓');more.href='#trCompositionTitle';more.className='tr-mini-more';body.appendChild(more);
    }else if(state.cell){body.appendChild(textEl('p','此网格在当前条件下没有记录；选区已保留，可调整时间或鸟种继续比较。'));}
    if(state.cell){
      var cell=data.cells.find(function(c){return c.id===state.cell;});
      var examples=(cell.examples||[]).filter(function(e){return(!state.bird||e.bird===state.bird)&&(!state.city||e.city===state.city)&&e.year>=state.from&&e.year<=state.to&&(!state.month||e.month===state.month);}).slice(0,3);
      if(examples.length){var refs=document.createElement('p');refs.appendChild(document.createTextNode('核对部分原始记录：'));examples.forEach(function(e){var a=textEl('a',birdName(e.bird)+' '+e.year+' ↗');a.href='https://www.gbif.org/occurrence/'+encodeURIComponent(e.id);a.target='_blank';a.rel='noopener noreferrer';a.style.marginRight='12px';refs.appendChild(a);});body.appendChild(refs);}
    }
    $('trClearCell').hidden = !state.cell;
  }
  function renderComposition() {
    var focusBird=document.activeElement&&document.activeElement.getAttribute('data-bird');
    var rows = Object.keys(detail.byBird).map(function (id) { return { id: id, n: detail.byBird[id] }; }).sort(function (a,b) { return b.n-a.n || a.id.localeCompare(b.id); });
    var shown = state.expanded ? rows : rows.slice(0,8), maximum = rows.length ? rows[0].n : 1;
    var chart = $('trComposition'); chart.replaceChildren();
    $('trDetailScope').textContent = scopeName() + ' · ' + detail.speciesCount + ' 种 · ' + format(detail.total) + ' 条'+(rows.length>8&&!state.expanded?' · 前8种':'');
    if (!rows.length) chart.appendChild(textEl('p', '此选区在当前条件下没有记录。可以调整年份、月份或鸟种筛选。', 'tr-chart-empty'));
    var palette = ['#92b890','#c6bb76','#80b8b0','#bd9e7c','#8facc2','#b4a6c8','#c6b09a','#a4b78b'];
    shown.forEach(function (row,index) {
      var bird = data.species.find(function (b) { return b.id === row.id; });
      var button = document.createElement('button'); button.type = 'button'; button.className = 'tr-comp-bar';
      button.dataset.bird=bird.id;
      var percentage = (row.n / detail.total * 100).toFixed(1);
      button.setAttribute('aria-label', bird.name + '，' + row.n + '条记录，占' + percentage + '%，点击筛选鸟种');
      button.setAttribute('aria-pressed', String(state.bird === bird.id));
      var image = document.createElement('img'); image.src = bird.image; image.alt = ''; image.loading = 'lazy';
      image.onerror = function () { image.onerror = null; image.src = '/static/img/placeholder.svg'; };
      var body = document.createElement('span'), track = textEl('span', '', 'tr-comp-track'), fill = document.createElement('i');
      fill.style.width = row.n/maximum*100+'%'; fill.style.setProperty('--bird-color', palette[data.species.findIndex(function(b){return b.id===bird.id;})%palette.length]); track.appendChild(fill);
      body.append(textEl('span', bird.name, 'tr-comp-name'),track);
      var value = textEl('span', format(row.n), 'tr-comp-value'); value.appendChild(textEl('small',percentage+'%'));
      button.append(image,body,value);
      button.addEventListener('click', function () { state.bird = state.bird === bird.id ? '' : bird.id; render(); });
      chart.appendChild(button);
    });
    $('trMoreBirds').hidden = rows.length <= 8;
    $('trMoreBirds').textContent = state.expanded ? '收起鸟种列表 ↑' : '展开全部 ' + rows.length + ' 种 ↓';
    if(focusBird){var refocus=chart.querySelector('[data-bird="'+focusBird+'"]');if(refocus)refocus.focus({preventScroll:true});}
  }
  function renderMonthly() {
    var focusMonth=document.activeElement&&document.activeElement.getAttribute('data-month');
    var seasonal = M.tally(selectedCells(),state.bird,state.city,filters({month:0}));
    var chart = $('trMonthChart'); chart.replaceChildren();
    var maximum = Math.max.apply(null,[1].concat(seasonal.byMonth.slice(1)));
    Array.from(new Set([0,Math.round(maximum/2),maximum])).forEach(function (tick) {
      var y = 140-tick/maximum*110;
      chart.appendChild(node('path',{d:'M27 '+y+'H290','class':'tr-axis-grid'}));
      chart.appendChild(node('text',{x:23,y:y+3,'text-anchor':'end','class':'tr-axis-text'},format(tick)));
    });
    for (var month=1;month<=12;month++) {
      (function (m) {
        var n=seasonal.byMonth[m], x=31+(m-1)*21.3, h=n/maximum*110;
        var bar=node('rect',{x:x,y:140-Math.max(2,h),width:14,height:Math.max(2,h),rx:1,tabindex:0,role:'button',
          'class':'tr-month-bar'+(state.month===m?' tr-selected':state.month?' tr-unselected':''),'data-month':m,
          'aria-pressed':String(state.month===m),'aria-label':m+'月，'+n+'条记录，点击'+(state.month===m?'取消月份筛选':'筛选月份')});
        bar.appendChild(node('title',{},m+'月 · '+format(n)+'条记录'));
        keyboardClick(bar,function(){state.month=state.month===m?0:m;render();});
        chart.appendChild(bar); chart.appendChild(node('text',{x:x+7,y:158,'class':'tr-month-label'},m));
      })(month);
    }
    $('trMonthScope').textContent=scopeName()+' · '+state.from+'–'+state.to+'年 · 点击月份筛选';
    $('trMonthCoverage').textContent='按观测月份汇总：'+format(seasonal.knownMonth)+'条有月份记录'+(seasonal.total-seasonal.knownMonth?'，另有'+format(seasonal.total-seasonal.knownMonth)+'条月份未知':'')+'。同一位置可在不同月份重复被记录。';
    if(focusMonth)chart.querySelector('[data-month="'+focusMonth+'"]').focus({preventScroll:true});
  }
  function renderAnnual() {
    var focusYear=document.activeElement&&document.activeElement.getAttribute('data-year');
    var annual=M.tally(selectedCells(),state.bird,state.city,filters({from:0,to:0}));
    var chart=$('trYearChart'); chart.replaceChildren();
    var min=data.coverage.year_min,max=data.coverage.year_max,peak=Math.max.apply(null,[1].concat(Object.values(annual.byYear)));
    function x(year){return 40+(year-min)/Math.max(1,max-min)*540;}
    function y(n){return 125-n/peak*102;}
    chart.appendChild(node('rect',{x:x(state.from)-3,y:16,width:Math.max(6,x(state.to)-x(state.from)+6),height:111,'class':'tr-year-window'}));
    Array.from(new Set([0,Math.round(peak/2),peak])).forEach(function(tick){chart.appendChild(node('path',{d:'M40 '+y(tick)+'H584','class':'tr-axis-grid'}));chart.appendChild(node('text',{x:33,y:y(tick)+3,'text-anchor':'end','class':'tr-axis-text'},format(tick)));});
    var points=[];
    for(var yr=min;yr<=max;yr++)points.push([x(yr),y(annual.byYear[yr]||0)]);
    var line=points.map(function(p,i){return(i?'L':'M')+p[0].toFixed(2)+' '+p[1].toFixed(2);}).join('');
    chart.appendChild(node('path',{d:line+'L'+x(max)+' 125L'+x(min)+' 125Z','class':'tr-year-area'}));
    chart.appendChild(node('path',{d:line,'class':'tr-year-line'}));
    var ticks=new Set([min,Math.round(min+(max-min)*.25),Math.round(min+(max-min)*.5),Math.round(min+(max-min)*.75),max]);
    ticks.forEach(function(year){chart.appendChild(node('text',{x:x(year),y:147,'text-anchor':'middle','class':'tr-axis-text'},year));});
    for(var year=min;year<=max;year++){
      (function(yr){
        var n=annual.byYear[yr]||0;
        if(n)chart.appendChild(node('circle',{cx:x(yr),cy:y(n),r:2.4,fill:'#c7cd99'}));
        var hit=node('circle',{cx:x(yr),cy:y(n),r:6,tabindex:0,role:'button','class':'tr-year-hit','data-year':yr,'aria-label':yr+'年，'+n+'条记录，点击筛选年份'});
        hit.appendChild(node('title',{},yr+'年 · '+format(n)+'条记录'));
        keyboardClick(hit,function(){if(state.from===yr&&state.to===yr)setYears(min,max);else setYears(yr,yr);});
        chart.appendChild(hit);
      })(year);
    }
    $('trAnnualScope').textContent=scopeName()+(state.month?' · '+state.month+'月':' · 全部月份')+' · 点击年份可筛选';
    document.querySelector('.tr-annual p').textContent='折线表示公开记录量的变化，受观测活动和平台收录影响，不表示种群增长或下降。'+(data.coverage.year_max===Number(new Intl.DateTimeFormat('en',{year:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(data.source.retrieved_on)))?'获取当年的记录可能尚未覆盖全年。':'');
    if(focusYear)chart.querySelector('[data-year="'+focusYear+'"]').focus({preventScroll:true});
  }
  function renderChart() {
    var focus = document.activeElement && document.activeElement.closest('.tr-bar');
    var focusId = focus && focus.dataset.city;
    var chart = $('trCityChart'), fragment = document.createDocumentFragment();
    var maximum = Math.max.apply(null, [1].concat(Object.values(province.byCity)));
    data.cities.slice().sort(function (a, b) { return (province.byCity[b.id] || 0) - (province.byCity[a.id] || 0) || Number(a.id) - Number(b.id); }).forEach(function (city) {
      var n = province.byCity[city.id] || 0, button = document.createElement('button');
      button.type = 'button'; button.className = 'tr-bar' + (n ? '' : ' tr-zero'); button.dataset.city = city.id;
      button.setAttribute('aria-pressed', String(state.city === city.id));
      button.setAttribute('aria-label', city.name + '，' + n + '条观测记录，点击' + (state.city === city.id ? '取消区域筛选' : '筛选'));
      var track = textEl('span', '', 'tr-bar-track'), fill = textEl('span', '', 'tr-bar-fill');
      fill.style.width = (n / maximum * 100) + '%'; track.appendChild(fill);
      button.append(textEl('span', city.name.replace(/市$/, '')), track, textEl('b', format(n)));
      button.addEventListener('click', function () { chooseCity(state.city === city.id ? '' : city.id); });
      fragment.appendChild(button);
    });
    chart.replaceChildren(fragment);
    if (focusId) chart.querySelector('[data-city="' + focusId + '"]').focus({ preventScroll: true });
    $('trChartNote').textContent = (state.bird ? birdName(state.bird) : '当前保护级别鸟种') + ' · 同期全省比较 · 点击筛选';
  }
  function renderBirds() {
    var list = $('trBirdList'); list.replaceChildren();
    data.species.filter(function (b) { return detail.byBird[b.id] > 0; }).forEach(function (bird) {
      var row = textEl('div', '', 'tr-bird-row'), image = document.createElement('img');
      image.src = bird.image; image.alt = bird.name; image.loading = 'lazy'; image.width = 44; image.height = 44;
      var body = document.createElement('div'), link = textEl('a', bird.name + ' ↗');
      link.href = bird.profile_url;
      body.append(link, textEl('small', bird.protection));
      var count = detail.byBird[bird.id] || 0;
      var value = textEl('span', format(count)); value.setAttribute('aria-label', count + '条观测记录');
      row.append(image, body, value); list.appendChild(row);
    });
  }
  function render() {
    if (!data) return;
    current = M.tally(data.cells, state.bird, state.city, filters());
    province = M.tally(data.cells, state.bird, '', filters());
    detail = M.tally(selectedCells(),state.bird,state.city,filters());
    $('trCount').textContent = format(detail.total);
    $('trSpeciesCount').textContent = detail.speciesCount;
    $('trGridCount').textContent = detail.gridCount;
    $('trScope').textContent = scopeName();
    $('trCohort').textContent = data.species.length;
    $('trSpecies').value = state.bird; $('trCity').value = state.city;
    $('trProtection').value = state.protection;
    $('trYearFrom').value=state.from; $('trYearTo').value=state.to;
    $('trFromLabel').textContent=state.from; $('trToLabel').textContent=state.to;
    $('trYearRange').textContent=state.from===state.to?state.from+'年':state.from+'–'+state.to;
    $('trMonthLabel').textContent=state.month?state.month+'月':'全部月份';
    $('trGridMode').setAttribute('aria-pressed', String(state.mode === 'grid'));
    $('trCityMode').setAttribute('aria-pressed', String(state.mode === 'city'));
    $('trGridShapes').style.display = state.mode === 'grid' ? '' : 'none';
    $('trMapSvgTitle').textContent = '安徽省公开观测记录' + (state.mode === 'grid' ? '网格图' : '地市统计图');
    $('trClipShape').setAttribute('d', boundary.features.filter(function (f) {
      return !state.city || String(f.properties.adcode) === state.city;
    }).map(function (f) { return path(f.geometry); }).join(''));
    Object.keys(cityNodes).forEach(function (id) {
      var included = !state.city || state.city === id;
      cityNodes[id].setAttribute('fill', state.mode === 'city' ? M.color(included ? province.byCity[id] || 0 : 0) : '#173c35');
      cityNodes[id].setAttribute('aria-pressed', String(state.city === id));
      cityNodes[id].setAttribute('aria-label', cityName(id) + '，当前条件全省比较中有' + (province.byCity[id] || 0) + '条记录，点击筛选');
      borderNodes[id].classList.toggle('tr-selected', state.city === id);
      labelNodes[id].classList.toggle('tr-muted', !included);
    });
    Object.keys(gridNodes).forEach(function (id) {
      var n = current.cells[id] || 0, rect = gridNodes[id];
      rect.style.display = n || state.cell===id ? '' : 'none';
      rect.setAttribute('fill', M.color(n));
      rect.setAttribute('aria-label', '网格' + id + '，' + n + '条观测记录，点击联动图表');
      rect.setAttribute('aria-pressed', String(state.cell === id));
      rect.classList.toggle('tr-selected', state.cell === id);
    });
    $('trMapEmpty').hidden = current.total > 0;
    renderChart(); renderBirds(); renderSelection(); renderComposition(); renderMonthly(); renderAnnual();
    var params = new URLSearchParams();
    if (state.bird) params.set('bird', state.bird);
    if (state.city) params.set('city', state.city);
    if(state.protection)params.set('protection',state.protection==='国家一级保护动物'?'1':'2');
    if(state.from!==data.coverage.year_min)params.set('from',state.from);
    if(state.to!==data.coverage.year_max)params.set('to',state.to);
    if(state.month)params.set('month',state.month);
    var query = params.toString();
    window.history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
  }
  function applyView() {
    view.x = Math.max(-(view.zoom - 1) * 320, Math.min((view.zoom - 1) * 320, view.x));
    view.y = Math.max(-(view.zoom - 1) * 350, Math.min((view.zoom - 1) * 350, view.y));
    $('trMapScene').setAttribute('transform', 'translate(' + (320 + view.x) + ' ' + (350 + view.y) + ') scale(' + view.zoom + ') translate(-320 -350)');
    svg.classList.toggle('tr-zoomed', view.zoom > 1);
    $('trZoomIn').disabled = view.zoom >= 3;
    $('trZoomOut').disabled = view.zoom <= 1;
    $('trScale').style.display = view.zoom === 1 ? '' : 'none';
    tip.hidden = true;
  }
  function zoom(factor) {
    var next = Math.max(1, Math.min(3, view.zoom * factor));
    view.x *= next / view.zoom; view.y *= next / view.zoom;
    view.zoom = next; applyView();
  }
  function fitProvince() { view = { zoom: 1, x: 0, y: 0 }; applyView(); }
  function chooseCity(id) {
    state.city = id; state.cell = null;
    render();
    if (!id) { fitProvince(); return; }
    var box = data.cities.find(function (c) { return c.id === id; }).bbox;
    var a = mapPoint([box[0], box[1]]), b = mapPoint([box[2], box[3]]);
    var z = Math.min(3, Math.max(1, Math.min(470 / Math.abs(a[0] - b[0]), 530 / Math.abs(a[1] - b[1]))));
    view = { zoom: z, x: (320 - (a[0] + b[0]) / 2) * z, y: (350 - (a[1] + b[1]) / 2) * z };
    applyView();
  }
  function svgXY(event) {
    var point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }
  svg.addEventListener('pointerdown', function (event) {
    if (!data || view.zoom <= 1 || event.button !== 0) return;
    drag = { id: event.pointerId, point: svgXY(event), x: view.x, y: view.y, moved: false };
  });
  svg.addEventListener('pointermove', function (event) {
    if (!drag || event.pointerId !== drag.id) return;
    var p = svgXY(event), dx = p.x - drag.point.x, dy = p.y - drag.point.y;
    if (!drag.moved && Math.hypot(dx, dy) < 7) return;
    drag.moved = true; svg.setPointerCapture(event.pointerId); svg.classList.add('tr-dragging');
    view.x = drag.x + dx; view.y = drag.y + dy; applyView();
  });
  function endDrag(event) {
    if (!drag || event.pointerId !== drag.id) return;
    suppressClick = drag.moved;
    if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    drag = null; svg.classList.remove('tr-dragging');
    setTimeout(function () { suppressClick = false; }, 0);
  }
  window.addEventListener('pointerup', endDrag); window.addEventListener('pointercancel', endDrag);
  $('trSpecies').addEventListener('change', function () { state.bird = this.value; tip.hidden = true; render(); });
  function populateSpecies() {
    $('trSpecies').replaceChildren(new Option('全部收录鸟种',''));
    data.species.filter(function(b){return !state.protection||b.protection===state.protection;}).slice().sort(function(a,b){return a.name.localeCompare(b.name,'zh-CN');}).forEach(function(b){$('trSpecies').appendChild(new Option(b.name,b.id));});
  }
  $('trProtection').addEventListener('change',function(){state.protection=this.value;if(state.bird&&!data.species.some(function(b){return b.id===state.bird&&(!state.protection||b.protection===state.protection);}))state.bird='';populateSpecies();render();});
  $('trCity').addEventListener('change', function () { chooseCity(this.value); });
  $('trReset').addEventListener('click', function () { state.bird='';state.city='';state.cell=null;state.protection='';state.from=data.coverage.year_min;state.to=data.coverage.year_max;state.month=0;state.expanded=false;populateSpecies();render();fitProvince(); });
  $('trYearFrom').addEventListener('input',function(){state.from=Math.min(Number(this.value),state.to);render();});
  $('trYearTo').addEventListener('input',function(){state.to=Math.max(Number(this.value),state.from);render();});
  $('trClearTime').addEventListener('click',function(){state.from=data.coverage.year_min;state.to=data.coverage.year_max;state.month=0;render();});
  $('trClearCell').addEventListener('click',function(){state.cell=null;render();});
  $('trMoreBirds').addEventListener('click',function(){state.expanded=!state.expanded;render();});
  $('trGridMode').addEventListener('click', function () { state.mode = 'grid'; render(); });
  $('trCityMode').addEventListener('click', function () { state.mode = 'city'; state.cell = null; render(); });
  $('trZoomIn').addEventListener('click', function () { zoom(1.4); });
  $('trZoomOut').addEventListener('click', function () { zoom(1 / 1.4); });
  $('trFit').addEventListener('click', fitProvince);
  $('trExport').addEventListener('click', function () {
    var url = URL.createObjectURL(new Blob([M.csv(data, state.bird, state.city, filters(), state.cell)], { type: 'text/csv;charset=utf-8;' }));
    var link = document.createElement('a'); link.href = url;
    link.download = ('皖羽踪迹-'+scopeName()+'-'+(state.bird?birdName(state.bird):'全部收录鸟种')+'-'+state.from+'-'+state.to+(state.month?'-'+state.month+'月':'')).replace(/[\\/:*?"<>|]/g,'-')+'.csv';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  });
  async function load() {
    if (activeRequest) activeRequest.abort();
    var version = ++loadVersion, controller = new AbortController(); activeRequest = controller;
    $('trLoadState').hidden = false; $('trRetry').hidden = true; $('trControls').disabled = true;
    $('trLoadText').textContent = '正在加载安徽省内的观测记录…';
    var timer = setTimeout(function () { controller.abort(); }, 15000);
    try {
      if (!M) throw new Error('model');
      var result = await Promise.all(['observations.json', 'anhui-cities.geojson'].map(async function (name) {
        var response = await fetch('/static/data/traces/' + name, { signal: controller.signal });
        if (!response.ok) throw new Error('http');
        return response.json();
      }));
      if (version !== loadVersion) return;
      data = result[0]; boundary = result[1];
      if (data.schema_version !== 2 || !data.cells.length || data.cities.length !== 16 || boundary.features.length !== 16) throw new Error('data');
      $('trCity').replaceChildren(new Option('安徽全省', ''));
      data.cities.forEach(function (c) { $('trCity').appendChild(new Option(c.name, c.id)); });
      var params = new URLSearchParams(window.location.search), bird = params.get('bird'), city = params.get('city');
      state.bird = data.species.some(function (b) { return b.id === bird; }) ? bird : '';
      state.city = data.cities.some(function (c) { return c.id === city; }) ? city : '';
      state.protection=params.get('protection')==='1'?'国家一级保护动物':params.get('protection')==='2'?'国家二级保护动物':'';
      if(state.bird&&state.protection&&!data.species.some(function(b){return b.id===state.bird&&b.protection===state.protection;}))state.bird='';
      populateSpecies();
      var minimum=data.coverage.year_min,maximum=data.coverage.year_max;
      state.from=Number(params.get('from'))||minimum;state.to=Number(params.get('to'))||maximum;
      state.from=Math.max(minimum,Math.min(maximum,Math.round(state.from)));state.to=Math.max(state.from,Math.min(maximum,Math.round(state.to)));
      state.month=Number(params.get('month'))||0;if(!Number.isInteger(state.month)||state.month<0||state.month>12)state.month=0;
      ['trYearFrom','trYearTo'].forEach(function(id){$(id).min=minimum;$(id).max=maximum;$(id).step=1;});
      state.cell = null;
      $('trBuildInfo').textContent = '数据获取日期：'+new Date(data.source.retrieved_on).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai'})+'；观测年份：'+minimum+'–'+maximum+'。获取日期与观测日期分别记录。';
      $('trCoverageInfo').textContent='省界裁切后收录 '+format(data.coverage.records)+' 条记录、'+data.coverage.species+' 种鸟，涉及 '+format(data.coverage.distinct_coordinate_pairs)+' 组不同坐标。按记录ID去重，不把重复地点的多次记录合并为一个点。';
      if(data.source.omitted_candidates&&data.source.omitted_candidates.length)$('trCoverageInfo').textContent+='另有 '+data.source.omitted_candidates.length+' 个候选鸟种因本次获取失败未纳入，没有使用不完整分页；具体情况见处理审计。';
      $('trSourceDatasets').replaceChildren();
      (data.source.datasets||[]).forEach(function(source){var p=textEl('p','','tr-source-dataset'),a=textEl('a',source.title+' ↗');a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';p.append(a,textEl('span',' · '+format(source.count)+'条 · '+licenseLabel(source.license)));if(source.doi){var doi=String(source.doi).replace(/^https?:\/\/doi\.org\//,'');if(/^10\.\d+\//.test(doi)){var cite=textEl('a',' DOI ↗');cite.href='https://doi.org/'+doi;cite.target='_blank';cite.rel='noopener noreferrer';p.appendChild(cite);}}$('trSourceDatasets').appendChild(p);});
      $('trExplorer').hidden = false;
      buildMap(); render(); if (state.city) chooseCity(state.city);
      $('trLoadState').hidden = true; $('trControls').disabled = false;
    } catch (error) {
      if (version !== loadVersion) return;
      $('trExplorer').hidden = true;
      $('trLoadText').textContent = '地图资料暂时无法加载，请重试。鸟类图鉴仍可正常阅读。';
      $('trRetry').hidden = false;
    } finally { clearTimeout(timer); }
  }
  $('trRetry').addEventListener('click', load);
  load();
})();
