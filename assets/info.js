/*
 * info.js — 정보 화면의 「← 뒤로」
 * 충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §5 ③ / §11 정보 화면
 *
 * §11 이 "왔던 화면으로" 라고 했다. 정보 화면은 지도(①)와 설명(②)
 * 양쪽에서 들어오므로 목적지를 고정할 수 없다.
 *
 * HTML 에는 href="index.html" 이 적혀 있다. JS 가 꺼져 있거나
 * 이 페이지를 직접 연 경우(뒤로 갈 곳이 없는 경우)의 목적지다.
 * 뒤로 갈 이력이 있을 때만 history.back() 으로 바꾼다.
 */
(function () {
  'use strict';

  var back = document.getElementById('back');
  if (!back) { return; }

  back.addEventListener('click', function (e) {
    /* 이력이 없으면 href 를 그대로 따라간다 (직접 열었거나 새 탭인 경우) */
    if (window.history.length <= 1) { return; }
    e.preventDefault();
    window.history.back();
  });

}());
