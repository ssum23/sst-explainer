/*
 * geo.js — 지도 좌표계
 * 충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §5 「지도 배경」
 *
 * 이 파일이 존재하는 이유
 *   PRD §5 가 "이미지의 네 모서리 위경도(bounding box)를 §16 에 못 박고
 *   변환식을 고정한다"고 했다. 개념도와, 3주차에 얹을 실제 배경지도가
 *   같은 bbox·같은 변환식을 쓰면 교체할 때 점을 다시 찍지 않아도 된다.
 *
 *   그러므로 bbox 를 바꾸는 일은 여기 한 곳만 고치는 일이어야 한다.
 *   화면에 좌표를 직접 적어 넣지 않는다.
 *
 * 빌드 도구를 쓰지 않으므로 ES module 이 아니라 일반 스크립트다.
 * (file:// 로 열었을 때 module 은 CORS 로 막힌다. 오프라인에서 떠야 한다.)
 */
(function (global) {
  'use strict';

  /* ------------------------------------------------------------------
     1. bounding box — 확정값 (2026-07-31, PRD §5·§16 반영 대기)

     충남 서해안 전체가 보이도록 넓혔다. 천수만만 담으면 축척이 너무 커서
     여기가 어디쯤인지 알 수 없다 — 태안반도와 가로림만이 함께 보여야
     천수만이 어디인지 읽힌다. 지곡도 이 범위 안에 들어온다.

     ── 1주차 배경지도 캡처 지침 ──────────────────────────────────
     이 네 값이 곧 캡처 범위다. 이미지의 네 모서리가 정확히 이 위경도여야 한다.

       북 36.95   남 36.15   서 125.95   동 126.90

     지켜야 할 것 셋.
       1) 가로:세로 = 0.956 : 1 (85.0 × 88.9 km). 이 비율로 잘라야 한다.
          비율이 어긋나면 아래 toPixel() 이 어긋나 점이 육지에 찍힌다.
       2) 여백 없이 자른다. 이미지 가장자리가 곧 bbox 경계다.
       3) 출처가 깨끗한 것만 쓴다 — 브이월드 · OpenStreetMap ·
          국립해양조사원 / 국토지리정보원. 카카오·네이버·구글 화면 캡처는
          재배포 금지다. 화면에 출처를 표기한다 (PRD §5·§11).

     교체할 때 고칠 곳은 index.html 의 <path class="app-land"> 두 개뿐이다.
     bbox 와 변환식이 그대로이므로 점의 좌표는 다시 찍지 않는다.
     ──────────────────────────────────────────────────────────── */
  var BBOX = {
    north: 36.95,
    south: 36.15,
    west:  125.95,
    east:  126.90
  };

  /* ------------------------------------------------------------------
     2. 그리기 면적
     높이는 bbox 의 실거리 비율에서 나온 값이다. 임의로 정한 값이 아니다.
       가로 84.96 km · 세로 88.91 km · 가로:세로 = 0.956 : 1 (거의 정사각형)
       350 × (88.91/84.96) = 366.3 → 366 을 쓴다.
     366 을 쓰면 가로 4.120 px/km, 세로 4.117 px/km 로 0.07% 어긋난다.
     20km 축척 막대에서 0.06px 차이라 화면에서 보이지 않는 수준이다.

     viewBox 폭을 350 으로 잡은 이유. 화면에서 실제로 그려지는 폭이 350px 다
     (컨테이너 414 − 본문 패딩 20×2 − figure 패딩 12×2). 둘을 같게 두면
     배율이 1.0 이 되어 SVG 안의 글자 크기가 곧 화면 px 이 된다.
     ------------------------------------------------------------------ */
  var VIEWBOX = { width: 350, height: 366 };

  /* 참고용 실거리. spanKm(BBOX) 로도 같은 값이 나온다 —
     이 상수는 문서용이고, 계산은 spanKm() 이 한다. */
  var SPAN_KM = { horizontal: 84.96, vertical: 88.91 };

  /* ------------------------------------------------------------------
     3. 위경도 → 픽셀

     단순 선형 변환이다. 투영을 쓰지 않는다 —
     이 범위(남북 89km)에서 메르카토르와의 차이는 1px 미만이고,
     투영을 넣으면 배경지도 교체 때 맞춰야 할 것이 하나 늘어난다.

     x 는 서→동, y 는 북→남(SVG 좌표계와 같은 방향)이다.

     bbox 와 폭을 인자로 받는다. 넘기지 않으면 위 확정값을 쓴다.
     확대·축소나 지역 확장을 하게 되면 함수는 그대로 두고 bbox 만 갈아끼운다.
     ------------------------------------------------------------------ */

  var KM_PER_LAT = 111.132;
  var KM_PER_LON = 111.320;   /* 적도 기준. 중위도 cos 를 곱해서 쓴다. */

  /* bbox 의 실거리(km). 경도 1도의 길이는 위도에 따라 달라지므로
     bbox 중앙 위도에서 계산한다. */
  function spanKm(bbox) {
    var b = bbox || BBOX;
    var midRad = (b.north + b.south) / 2 * Math.PI / 180;
    return {
      horizontal: (b.east - b.west) * KM_PER_LON * Math.cos(midRad),
      vertical:   (b.north - b.south) * KM_PER_LAT
    };
  }

  /* 폭이 주어지면 높이는 실거리 비율에서 나온다. 고를 수 있는 값이 아니다 —
     비율을 어기면 가로·세로 축척이 달라져 점이 엉뚱한 자리에 찍힌다. */
  function heightFor(bbox, width) {
    var km = spanKm(bbox);
    return width * (km.vertical / km.horizontal);
  }

  /* 기본 bbox · 기본 폭이면 선언값(366)을 그대로 쓴다.
     계산하면 366.28 이 나오는데, HTML 의 viewBox="0 0 350 366" 속성과
     어긋나면 점이 최대 0.3px 밀린다. 선언값을 우선한다. */
  function boxFor(bbox, width) {
    var b = bbox || BBOX;
    var w = (width === undefined || width === null) ? VIEWBOX.width : width;
    if (b === BBOX && w === VIEWBOX.width) { return VIEWBOX; }
    return { width: w, height: heightFor(b, w) };
  }

  function toPixel(lat, lon, bbox, width) {
    var b = bbox || BBOX;
    var v = boxFor(bbox, width);
    return {
      x: (lon - b.west)  / (b.east  - b.west)  * v.width,
      y: (b.north - lat) / (b.north - b.south) * v.height
    };
  }

  /* 역변환 — 배경지도 위에서 찍은 픽셀이 어느 좌표인지 확인할 때 쓴다 */
  function toLatLon(x, y, bbox, width) {
    var b = bbox || BBOX;
    var v = boxFor(bbox, width);
    return {
      lat: b.north - (y / v.height) * (b.north - b.south),
      lon: b.west  + (x / v.width)  * (b.east  - b.west)
    };
  }

  /* bbox 밖이면 그리지 않는다. 조용히 화면 밖에 찍히는 것을 막는다. */
  function contains(lat, lon, bbox) {
    var b = bbox || BBOX;
    return lat <= b.north && lat >= b.south &&
           lon >= b.west  && lon <= b.east;
  }

  /* 축척 막대 길이 — n km 가 몇 px 인지 */
  function kmToPixels(km, bbox, width) {
    var v = boxFor(bbox, width);
    return km * (v.width / spanKm(bbox).horizontal);
  }

  /* ------------------------------------------------------------------
     4. 관측점
     해역명은 전부 `{해역} 해역(확인 중)` 형태다. 여섯 곳 모두. 창리도 예외가 아니다.
     `해역` 을 넣어 지명임을 밝히고, `추정` 대신 `확인 중` 을 쓴다 —
     `(추정)` 만 붙여 두면 수온이 추정치라는 뜻으로 읽힐 수 있다. (PRD §5, CHANGES #9)
     ------------------------------------------------------------------ */
  var STATIONS = [
    { id:'sj086', name:'서산 지곡',   lat:36.8935, lon:126.3524, area:'가로림만 해역(확인 중)',   ready:false },
    { id:'fsch6', name:'서산 창리',   lat:36.6163, lon:126.3717, area:'천수만 해역(확인 중)',     ready:true  },
    { id:'btai5', name:'태안 안면도', lat:36.5369, lon:126.2981, area:'천수만 해역(확인 중)',     ready:false },
    { id:'btni5', name:'태안 내포',   lat:36.4672, lon:126.4394, area:'천수만 해역(확인 중)',     ready:false },
    { id:'br001', name:'태안 고남',   lat:36.4158, lon:126.4333, area:'천수만 해역(확인 중)',     ready:false },
    { id:'bbsi5', name:'보령 삽시도', lat:36.3714, lon:126.3383, area:'천수만 입구 해역(확인 중)', ready:false }
  ];

  /* ------------------------------------------------------------------
     5. 개념도에 점을 앉힌다
     HTML 에는 계산된 값이 이미 박혀 있다 (JS 가 꺼져도 점은 보인다).
     이 함수는 bbox 를 고쳤을 때 HTML 을 손대지 않아도 되게 해 준다.
     ------------------------------------------------------------------ */
  function placePins(root) {
    var nodes = (root || document).querySelectorAll('[data-station]');
    Array.prototype.forEach.call(nodes, function (node) {
      var s = STATIONS.filter(function (x) { return x.id === node.dataset.station; })[0];
      if (!s || !contains(s.lat, s.lon)) { return; }
      var p = toPixel(s.lat, s.lon);
      /* 한 지점에 원이 둘일 수 있다 — 보이는 점과 터치용 투명 원.
         둘 다 같은 자리로 옮긴다. */
      var circles = node.tagName === 'circle' ? [node] : node.querySelectorAll('circle');
      var label  = node.querySelector ? node.querySelector('text') : null;
      Array.prototype.forEach.call(circles, function (circle) {
        circle.setAttribute('cx', p.x.toFixed(1));
        circle.setAttribute('cy', p.y.toFixed(1));
      });
      if (label) {
        label.setAttribute('x', (p.x + 15).toFixed(1));
        label.setAttribute('y', (p.y + 5).toFixed(1));
      }
    });
  }

  /* ------------------------------------------------------------------
     6. 지도 밖 지점 안내
     bbox 밖으로 뺀 지점은 방향과 거리로 말한다.
     거리를 화면에 적어 두지 않는다 — 좌표가 바뀌면 문구가 조용히 틀린다.
     ------------------------------------------------------------------ */
  function distanceKm(lat1, lon1, lat2, lon2) {
    var midRad = (lat1 + lat2) / 2 * Math.PI / 180;
    var dy = (lat2 - lat1) * 111.132;
    var dx = (lon2 - lon1) * 111.320 * Math.cos(midRad);
    return Math.sqrt(dx * dx + dy * dy);
  }

  function station(id) {
    return STATIONS.filter(function (s) { return s.id === id; })[0] || null;
  }

  /* data-offmap="지도 밖 지점 id" data-from="기준 지점 id" 인 요소를 채운다.
     JS 가 꺼져도 HTML 에 같은 문구가 적혀 있어 화면이 비지 않는다. */
  function placeOffMapNotes(root) {
    var nodes = (root || document).querySelectorAll('[data-offmap]');
    Array.prototype.forEach.call(nodes, function (node) {
      var target = station(node.dataset.offmap);
      var from   = station(node.dataset.from);
      if (!target || !from) { return; }
      var km = Math.round(distanceKm(from.lat, from.lon, target.lat, target.lon));
      var dir = target.lat > from.lat ? '북쪽' : '남쪽';
      var arrow = target.lat > from.lat ? '↑' : '↓';
      node.textContent = arrow + ' ' + dir + ' ' + km + 'km · ' +
                         target.name + ' (' + target.area + ')';
    });
  }

  global.GEO = {
    BBOX: BBOX,
    VIEWBOX: VIEWBOX,
    SPAN_KM: SPAN_KM,
    STATIONS: STATIONS,
    toPixel: toPixel,
    toLatLon: toLatLon,
    contains: contains,
    kmToPixels: kmToPixels,
    spanKm: spanKm,
    heightFor: heightFor,
    distanceKm: distanceKm,
    station: station,
    placePins: placePins,
    placeOffMapNotes: placeOffMapNotes
  };

  function draw() { placePins(); placeOffMapNotes(); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', draw);
  } else {
    draw();
  }

}(window));
