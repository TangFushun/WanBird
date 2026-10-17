/* 皖境飞鸟观测台 —— 栖息地分布地图
   基于本地化 Leaflet + 高德栅格瓦片；深色化瓦片 + 金色点位，与 HUD 风格统一。
   内容：
   1. 默认视图为一幅完整世界地图：maxBounds 钳制在世界边界（不能无限左右滑动进空白），
      minZoom=2 保证整幅世界可见且无法滑出单幅世界，最大可放大到城市级；
   2. 示意范围（多边形/折线）+ 关键地点（脉冲点）+ 图例 + 动态效果；
   3. 真实观测记录图层（GBIF 数据，可开关）；
   4. 「聚焦本种」按钮（fitToSpecies）可飞到该物种的分布中心。
   数据：data/birds.json 的 map 字段 + static/data/occur/<id>.json。 */
(function () {
  var KIND_STYLE = {
    breed:    { label: '繁殖地',   color: '#ffb25a' },
    winter:   { label: '越冬地',   color: '#4fc3f7' },
    resident: { label: '留鸟区',   color: '#7fe0b0' },
    staging:  { label: '迁徙停歇地', color: '#4dd0e1' },
    historic: { label: '历史分布区', color: '#9aa7a6' }
  };
  var DEFAULT_COLOR = '#e8a838';
  var OCC_COLOR = '#7fd0bd';   // 真实观测点颜色（青绿，区别于金色关键点）

  // 世界边界：限制平移，避免左右无限滑动出空白；纬度略收避免极地伪影
  var WORLD_BOUNDS = [[-85, -180], [85, 180]];

  function kindStyle(kind) {
    return KIND_STYLE[kind] || { label: '', color: DEFAULT_COLOR };
  }

  window.initBirdMap = function (elId, data, opts) {
    var el = document.getElementById(elId);
    if (!el) return;

    var ranges = (data && data.ranges || []).filter(function (r) {
      return r && Array.isArray(r.polygon) && r.polygon.length;
    });
    var sites = (data && data.sites || []).filter(function (s) {
      return s && Array.isArray(s.coord);
    });

    if (!ranges.length && !sites.length) {
      el.innerHTML = '<div class="mempty">该物种暂无栖息地地图数据</div>';
      return;
    }
    if (typeof L === 'undefined') {
      el.innerHTML = '<div class="mempty">地图组件加载失败（Leaflet 未就绪）</div>';
      return;
    }

    var map = L.map(el, { zoomControl: true, attributionControl: true });
    // 完整世界地图：默认视图 = 整幅世界（中心 0°经线，随时可看全六大洲）。
    // maxBounds=世界边界 → 平移钳制（不能无限滑进空白）；minZoom=2 → 世界宽于视口，无法滑出单幅世界。
    map.setView([18, 0], 2);
    map.setMaxBounds(WORLD_BOUNDS);
    map.setMinZoom(2);
    map.setMaxZoom(18);
    map.options.maxBoundsViscosity = 0.8;

    // 高德栅格瓦片（本机实测可访问；勿换 OSM —— 网络层被屏蔽）
    L.tileLayer(
      'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}',
      { subdomains: ['1', '2', '3', '4'], maxZoom: 18, attribution: '© 高德地图' }
    ).addTo(map);

    var allPts = [];   // 范围 + 关键点：供「聚焦本种」使用

    // ---------- 范围：多边形（流动虚线 + 光晕 + 渐入）；停歇地 → 发光折线 ----------
    ranges.forEach(function (r) {
      var st = kindStyle(r.kind);
      var pts = r.polygon.map(function (p) { return [p[1], p[0]]; });
      pts.forEach(function (p) { allPts.push(p); });

      var layer;
      if (r.kind === 'staging') {
        layer = L.polyline(pts, {
          color: st.color, weight: 5, opacity: .9, className: 'staging-line'
        }).addTo(map).bindTooltip(r.label || st.label || r.kind, { sticky: true });
        layer.on('mouseover', function () { layer.setStyle({ weight: 7, opacity: 1 }); });
        layer.on('mouseout', function () { layer.setStyle({ weight: 5, opacity: .9 }); });
      } else {
        var cls = 'bird-range' + (r.kind === 'historic' ? ' solid' : '');
        layer = L.polygon(pts, {
          color: st.color, weight: 2, opacity: .95,
          fillColor: st.color, fillOpacity: .28, className: cls
        }).addTo(map).bindTooltip(r.label || st.label || r.kind, { sticky: true });
        layer.on('mouseover', function () { layer.setStyle({ weight: 3, fillOpacity: .45 }); });
        layer.on('mouseout', function () { layer.setStyle({ weight: 2, fillOpacity: .28 }); });
      }
      var g = layer.getElement && layer.getElement();
      if (g) g.style.color = st.color;
    });

    // ---------- 关键地点：金色脉冲点（呼吸光圈） ----------
    sites.forEach(function (s, i) {
      var ll = [s.coord[1], s.coord[0]];
      allPts.push(ll);
      L.marker(ll, {
        icon: L.divIcon({
          className: 'site-pin-wrap',
          html: '<i class="site-pin"></i>'
              + '<i class="site-ring" style="animation-delay:' + (i % 4) * .45 + 's"></i>',
          iconSize: [26, 26],
          iconAnchor: [13, 13],
          popupAnchor: [0, -8]
        })
      }).addTo(map).bindPopup('<b>' + s.name + '</b>' + (s.note ? '<br>' + s.note : ''));
    });

    // ---------- 图例 ----------
    var used = {};
    ranges.forEach(function (r) { used[r.kind] = r.label || kindStyle(r.kind).label; });
    var legend = document.createElement('div');
    legend.className = 'mlegend';
    Object.keys(used).forEach(function (k) {
      var row = document.createElement('div');
      row.className = 'mlegend-row';
      var dot = document.createElement('i');
      dot.style.background = kindStyle(k).color;
      row.appendChild(dot);
      row.appendChild(document.createTextNode(used[k]));
      legend.appendChild(row);
    });
    var occRow = document.createElement('div');
    occRow.className = 'mlegend-row';
    var occDot = document.createElement('i');
    occDot.style.background = OCC_COLOR;
    occDot.style.borderRadius = '50%';
    occRow.appendChild(occDot);
    occRow.appendChild(document.createTextNode('真实观测记录(GBIF)'));
    legend.appendChild(occRow);
    el.appendChild(legend);

    // ---------- 真实观测点图层（GBIF，异步加载，失败静默） ----------
    var occLayer = L.layerGroup();
    if (opts && opts.occurUrl) {
      fetch(opts.occurUrl).then(function (r) { return r.ok ? r.json() : []; }).then(function (list) {
        if (!Array.isArray(list) || !list.length) return;
        list.forEach(function (p) {
          if (!Array.isArray(p) || p.length < 2) return;
          occLayer.addLayer(L.circleMarker([p[1], p[0]], {
            radius: 2.3, weight: 1, color: 'rgba(214,242,234,.8)',
            fillColor: OCC_COLOR, fillOpacity: .5, interactive: false
          }));
        });
        if (occLayer.getLayers().length) occLayer.addTo(map);
      }).catch(function () { /* 观测点不可用则忽略 */ });
    }

    map.invalidateSize();

    // ---------- 供页面开关/按钮控制 ----------
    window.__birdMaps = window.__birdMaps || {};
    window.__birdMaps[elId] = {
      map: map,
      setOccurVisible: function (show) {
        if (show) { if (occLayer.getLayers().length && !map.hasLayer(occLayer)) occLayer.addTo(map); }
        else if (map.hasLayer(occLayer)) map.removeLayer(occLayer);
      },
      // 聚焦本种：以该物种「范围+关键点」的几何中心缩放（z7），
      // 不用 fitBounds —— 在世界 maxBounds 下高缩放时中心锁消失，亚洲任意区域都可居中。
      fitToSpecies: function () {
        if (!allPts.length) return;
        var lat = 0, lng = 0, n = 0;
        allPts.forEach(function (p) {
          if (!Array.isArray(p) || p.length < 2) return;
          lat += p[0]; lng += p[1]; n++;
        });
        if (!n) return;
        map.setView([lat / n, lng / n], 7);
      }
    };

    // ---------- 瓦片加载失败提示 ----------
    var failed = false;
    map.on('tileerror', function () {
      if (failed) return;
      failed = true;
      var w = document.createElement('div');
      w.className = 'mempty maperr';
      w.textContent = '地图瓦片加载失败：请联网后刷新查看栖息地地图。';
      el.appendChild(w);
    });
  };

  window.BIRD_KIND_STYLE = KIND_STYLE;
})();
