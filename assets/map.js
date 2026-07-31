/*
 * map.js — 지도 화면의 준비 중 지점 안내
 * 충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §5 ① / §11 지도
 *
 * 설명을 제공하지 않는 다섯 곳을 누르면 안내를 띄운다.
 * 지도의 점과 접힌 목록, 두 곳 모두에서 같은 안내가 나온다.
 *
 * 지점명·해역명은 geo.js 의 STATIONS 에서 가져온다. 여기 적지 않는다 —
 * 해역 표기가 바뀔 때 고칠 곳이 두 군데가 되면 언젠가 갈린다.
 *
 * 수온을 비롯한 어떤 값도 넣지 않는다. 검증하지 않은 지점이다. (PRD §5)
 */
(function (global) {
  'use strict';

  var dialog = document.getElementById('station-modal');
  if (!dialog) { return; }

  var nameEl = document.getElementById('modal-name');
  var areaEl = document.getElementById('modal-area');
  var closeBtn = document.getElementById('modal-close');
  var opener = null;   /* 닫은 뒤 포커스를 돌려줄 곳 */

  function open(id, trigger) {
    var s = global.GEO && global.GEO.station ? global.GEO.station(id) : null;
    if (!s) { return; }
    nameEl.textContent = s.name;
    areaEl.textContent = s.area;
    opener = trigger || null;
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');   /* <dialog> 미지원 브라우저 */
    }
  }

  function close() {
    if (typeof dialog.close === 'function' && dialog.open) {
      dialog.close();
    } else {
      dialog.removeAttribute('open');
    }
    if (opener && opener.focus) { opener.focus(); }
    opener = null;
  }

  closeBtn.addEventListener('click', close);

  /* 바깥(backdrop)을 눌러도 닫는다. 패널 안쪽 클릭은 통과시킨다. */
  dialog.addEventListener('click', function (e) {
    if (e.target === dialog) { close(); }
  });

  dialog.addEventListener('close', function () {
    if (opener && opener.focus) { opener.focus(); }
    opener = null;
  });

  /* ------------------------------------------------------------------
     누를 수 있게 만들 것 둘
       1) 지도의 점  — SVG <g role="button">. 클릭과 Enter/Space 를 직접 처리한다.
       2) 접힌 목록  — <button>. 클릭만 붙이면 키보드는 브라우저가 해 준다.
     창리(fsch6)는 여기 없다. 그쪽은 <a href="station.html"> 다.
     ------------------------------------------------------------------ */
  function wire(node) {
    var id = node.dataset.station;
    if (!id) { return; }
    node.addEventListener('click', function () { open(id, node); });
    if (node.tagName.toLowerCase() === 'g') {
      node.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          open(id, node);
        }
      });
    }
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('.app-pin--more[data-station], .app-more__item[data-station]'),
    wire
  );

  global.STATION_MODAL = { open: open, close: close };

}(window));
