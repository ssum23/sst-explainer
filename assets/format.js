/*
 * format.js — 값 하나를 화면 문구 하나로 바꾸는 함수들
 * 충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §10 「렌더 규칙」 / §11 「평년 대비」
 *
 * 이 파일이 존재하는 이유
 *   §11 이 "§10 의 {anomaly_phrase} 렌더러와 같은 함수를 쓴다"고 못 박았다.
 *   화면이 28.5℃ 를 쓰는데 AI 문장이 28.47℃ 를 쓰는 일이 구조적으로
 *   생기지 않게 하려는 것이다. 그러므로 여기 있는 함수는
 *   §10 의 자리표시자 렌더러가 그대로 다시 쓴다. 사본을 만들지 않는다.
 *
 * 두 가지 규칙만 지키면 된다.
 *   1. 원값(_raw)에서 계산한다. 표기값(current_sst = 28.47)을 다시 반올림하면
 *      26.25 → 26.3 이 되어 원값 기준(26.2)과 어긋난다. (§10)
 *   2. 사사오입한다. JavaScript 의 Math.round 는 음수에서 half-up 이 아니라
 *      half-toward-+∞ 다 — Math.round(-2.5) 가 -3 이 아니라 -2 다.
 *      그래서 절댓값을 먼저 취해 반올림하고 부호를 나중에 붙인다.
 *
 * 빌드 도구를 쓰지 않으므로 ES module 이 아니라 일반 스크립트다.
 */
(function (global) {
  'use strict';

  /* 소수 첫째 자리 사사오입. 음수도 크기 기준으로 반올림한다. */
  function round1(raw) {
    var sign = raw < 0 ? -1 : 1;
    return sign * Math.round(Math.abs(raw) * 10) / 10;
  }

  /* 소수 첫째 자리를 항상 붙인다. 28 이 아니라 28.0 으로 적는다.
     자릿수가 흔들리면 실시간 갱신 때 숫자가 튄다. */
  function fixed1(n) {
    return n.toFixed(1);
  }

  /* ------------------------------------------------------------------
     fmtValue — 수치 + 단위
       fmtValue(28.4708, '℃')       → '28.5℃'
       fmtValue(23.1429, 'MJ/m²')   → '23.1 MJ/m²'
     ℃ 는 붙여 쓰고 그 밖의 단위는 띄어 쓴다 (§5 목업 표기).
     ------------------------------------------------------------------ */
  function fmtValue(raw, unit) {
    if (raw === null || raw === undefined || isNaN(raw)) { return null; }
    var n = fixed1(round1(raw));
    if (!unit) { return n; }
    return unit === '℃' ? n + unit : n + ' ' + unit;
  }

  /* ------------------------------------------------------------------
     fmtAnomaly — 평년 대비 한 문장 (§11 표 / §10 {anomaly_phrase})

       분기 판정은 원값이 아니라 "절댓값을 소수 첫째 자리로 반올림한 값"으로 한다.
       원값으로 분기하면 raw = 0.48 일 때
         화면(반올림 0.5 기준) → 평년과 비슷합니다
         문장(원값 0.48 기준)  → 0.5℃ 높습니다
       로 갈린다. 반올림을 먼저 하면 그럴 수 없다.

       fmtAnomaly(2.2257)  → '평년보다 2.2℃ 높습니다'
       fmtAnomaly(-1.84)   → '평년보다 1.8℃ 낮습니다'
       fmtAnomaly(0.48)    → '평년보다 0.5℃ 높습니다'  (0.48 → 반올림 0.5 → 기준 이상)
       fmtAnomaly(0.44)    → '평년과 비슷합니다'        (0.44 → 반올림 0.4 → 기준 미만)
       fmtAnomaly(-0.44)   → '평년과 비슷합니다'        (부호와 무관하게 크기로 가른다)
     ------------------------------------------------------------------ */
  function fmtAnomaly(raw) {
    if (raw === null || raw === undefined || isNaN(raw)) { return null; }
    var magnitude = Math.round(Math.abs(raw) * 10) / 10;   /* 절댓값을 먼저 반올림 */
    if (magnitude < 0.5) { return '평년과 비슷합니다'; }
    var direction = raw < 0 ? '낮습니다' : '높습니다';      /* 방향은 원값의 부호로 */
    return '평년보다 ' + fixed1(magnitude) + '℃ ' + direction;
  }

  /* ------------------------------------------------------------------
     fmtTop — 백분위를 '상위 N%' 로 (§10 {*_top})
       fmtTop(87.3) → '상위 13%'
       fmtTop(90.7) → '상위 9%'
     백분위와 상위%는 커지는 방향이 반대다. 화면에는 상위%만 쓴다.
     ------------------------------------------------------------------ */
  function fmtTop(percentile) {
    if (percentile === null || percentile === undefined || isNaN(percentile)) { return null; }
    return '상위 ' + Math.round(100 - percentile) + '%';
  }

  /* ------------------------------------------------------------------
     fmtDate — 'M월 D일'
       fmtDate('2021-07-31')              → '7월 31일'
       fmtDate('2026-07-31T14:00:00+09:00') → '7월 31일'

     new Date() 로 파싱하지 않는다. '2021-07-31' 은 UTC 자정으로 해석돼
     KST 기준으로 하루 밀린다. 문자열을 그대로 자른다.
     ------------------------------------------------------------------ */
  function fmtDate(iso) {
    if (!iso) { return null; }
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) { return null; }
    return parseInt(m[2], 10) + '월 ' + parseInt(m[3], 10) + '일';
  }

  /* ------------------------------------------------------------------
     fmtMissingRate — 결측률 (§10 {missing_rate})
     0.396 → '39.6%'. 판정 보류 문구가 이 값을 쓴다 (§11 판정 보류).
     ------------------------------------------------------------------ */
  function fmtMissingRate(rate) {
    if (rate === null || rate === undefined || isNaN(rate)) { return null; }
    return (Math.round(rate * 1000) / 10).toFixed(1) + '%';
  }

  global.FMT = {
    round1: round1,
    fmtValue: fmtValue,
    fmtAnomaly: fmtAnomaly,
    fmtTop: fmtTop,
    fmtDate: fmtDate,
    fmtMissingRate: fmtMissingRate
  };

}(window));
