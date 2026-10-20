/* 皖境飞鸟观测台 —— 公共前端工具 */

// 鸟类图片兜底链：用户照片(jpg/png) → 内置剪影 svg → 占位图
// 文件名优先取 bird.image 里指定的（支持按学名命名，如 "Ciconia boyciana.jpg"），
// 否则回落到 bird.id 的命名。
function birdImg(bird, cls){
  var img = document.createElement('img');
  if (cls) img.className = cls;
  img.loading = 'lazy';
  img.alt = bird && bird.name ? bird.name : '';
  var id = bird ? bird.id : '';
  var name = id;
  if (bird && bird.image) {
    var fn = String(bird.image).split('/').pop().replace(/\.(jpe?g|png)$/i, '');
    if (fn) name = fn;
  }
  var enc = encodeURIComponent(name);
  // 优先放的照片（jpg 或 png），失败再回落剪影/占位
  img.dataset.steps = JSON.stringify([
    '/static/img/birds/' + enc + '.jpg',
    '/static/img/birds/' + enc + '.png',
    '/static/img/birds/' + encodeURIComponent(id) + '.svg',
    '/static/img/placeholder.svg'
  ]);
  var tries = 0;
  img.addEventListener('error', function(){
    tries++;
    var steps = JSON.parse(img.dataset.steps || '[]');
    if (tries < steps.length && steps[tries]) {
      img.src = steps[tries];
    }
  });
  img.src = '/static/img/birds/' + enc + '.jpg';
  return img;
}

// 封面/普通图片：失败回落到占位图
function coverImg(src, alt, cls){
  var img = document.createElement('img');
  if (cls) img.className = cls;
  img.loading = 'lazy';
  img.alt = alt || '';
  img.onerror = function(){ img.onerror = null; img.src = '/static/img/placeholder.svg'; };
  img.src = src || '/static/img/placeholder.svg';
  return img;
}

// 国际化常数：IUCN 代码 → 中文
var IUCN_CN = {
  EX: '已灭绝', EW: '野外灭绝', CR: '极危', EN: '濒危',
  VU: '易危', NT: '近危', LC: '无危', DD: '数据缺乏', NE: '未评估'
};
