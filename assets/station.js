/*
 * station.js — 설명 화면에 근거 파일을 그린다
 * 충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §5 ② / §8 / §11
 *
 * 값은 전부 data/fsch6.json 에서 온다. 화면에 숫자를 적어 두지 않는다.
 * 포맷은 assets/format.js 하나만 쓴다 — 화면과 AI 문장이 갈리지 않게 하려는 것이다.
 *
 * 보류일(stage = withheld)에 없는 값이 많다. null 을 만나면
 * "—" 를 찍지 않고 그 줄을 통째로 감춘다. 빈 자리를 보여 주는 것보다
 * 그 자리가 없는 편이 정직하다. (§8 「보류일에 담는 것과 담지 않는 것」)
 */
(function (global) {
  'use strict';

  var F = global.FMT;

  /* ------------------------------------------------------------------
     어느 파일을 읽을 것인가

       station.html                  → data/fsch6.json   (기본값)
       station.html?station=btni5    → data/btni5.json
       station.html?sample=b         → data/sample-b.json

     지점이 늘면 data/{id}.json 을 추가하고 지도에서 그 id 로 링크하면 된다.
     선택 UI 는 만들지 않는다 — 지도의 점과 목록 항목이 곧 링크다.

     `sample` 이 있으면 그쪽이 이긴다. 견본 A·B·C 는 창리 실측이라
     지점 개념이 없는 시연용 고정 파일이기 때문이다. (PRD §9)

     id 는 형태를 검사한다. 검사 없이 경로에 이어 붙이면
     ?station=../../어딘가 로 저장소의 다른 파일을 읽게 할 수 있다.
     ------------------------------------------------------------------ */
  var SAMPLES = { b: 'data/sample-b.json', c: 'data/sample-c.json' };
  var DEFAULT_STATION = 'fsch6';

  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(global.location.search);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function resolveSource() {
    var sample = (param('sample') || '').toLowerCase();
    if (SAMPLES[sample]) { return SAMPLES[sample]; }
    var id = param('station') || DEFAULT_STATION;
    if (!/^[a-z0-9_-]{2,16}$/i.test(id)) { id = DEFAULT_STATION; }
    return 'data/' + id + '.json';
  }

  var SOURCE = resolveSource();

  /* 개발용 견본 전환 — 지금 보고 있는 것을 눌린 상태로 표시한다.
     `?sample=` 이 없으면 A(기본 지점 파일)를 보고 있는 것이다. */
  function markCurrentSample() {
    var current = (param('sample') || '').toLowerCase();
    if (!SAMPLES[current]) { current = ''; }
    var nodes = document.querySelectorAll('.app-samples__btn');
    Array.prototype.forEach.call(nodes, function (node) {
      var on = (node.dataset.sample || '') === current;
      node.classList.toggle('is-current', on);
      if (on) { node.setAttribute('aria-current', 'page'); }
      else { node.removeAttribute('aria-current'); }
    });
  }
  markCurrentSample();

  function $(id) { return document.getElementById(id); }

  /* 값이 있으면 넣고 보이게, 없으면 통째로 감춘다 */
  function setLine(id, text) {
    var el = $(id);
    if (!el) { return; }
    if (text === null || text === undefined) {
      el.hidden = true;
      el.textContent = '';
    } else {
      el.textContent = text;
      el.hidden = false;
    }
  }

  function show(id, on) {
    var el = $(id);
    if (el) { el.hidden = !on; }
  }

  /* ------------------------------------------------------------------
     요인 자료 시각
     ASOS 요인(일사·기온)의 7일 창은 대상일 전날까지이고,
     배경장(수온 30일 누적편차)만 대상일과 같다. (§7)
     그래서 as_of 가 섞인다 — 견본 A 는 7/30 과 7/31 이 함께 있다.
     화면에는 가장 이른 날짜를 쓴다. "이 날짜까지는 모든 요인에 자료가 있다"가
     참인 유일한 날짜이기 때문이다. §5 목업의 `요인: 7월 30일까지 자료` 와 같다.
     ------------------------------------------------------------------ */
  function earliestFactorDate(groups) {
    var dates = [];
    (groups || []).forEach(function (g) {
      (g.factors || []).forEach(function (f) {
        if (f.as_of) { dates.push(f.as_of); }
      });
    });
    if (!dates.length) { return null; }
    return dates.sort()[0];
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }

  /* ------------------------------------------------------------------
     요인 막대 — 채우는 바가 아니라 트랙 위의 점 하나 (§5 「요인 막대」)

     스케일은 백분위 0~100 을 트랙 폭에 선형 대응시킨다.
     50~100 으로 확대하지 않는다. 견본 A 의 87.3 과 90.7 은 3.4 밖에
     차이 나지 않아 막대에서 거의 붙어 보이는데, 그게 정직하다.
     판별은 임계선과 숫자가 하고 막대는 인상만 준다.

     임계 위치는 파일에서 읽는다. 90 을 하드코딩하지 않는다.
     ------------------------------------------------------------------ */
  function factorBar(factor, threshold) {
    var wrap = el('div', 'app-bar');

    wrap.appendChild(el('span', 'app-bar__track'));

    /* 임계선을 마커보다 뒤에 붙인다 — z-index 와 함께 이중으로 보장한다.
       견본 A 의 기온은 임계선에서 0.7% 떨어져 있고, 폭 334px 트랙에서
       2.3px 다. 지름 12px 마커가 선을 통째로 덮으면
       §9 가 견본 A 를 고른 이유가 화면에서 사라진다. (§5, §14 #16) */
    var marker = el('span', 'app-bar__marker');
    marker.style.left = factor.percentile + '%';   /* 중심 맞추기는 CSS transform */
    wrap.appendChild(marker);

    var line = el('span', 'app-bar__threshold');
    line.style.left = threshold + '%';
    wrap.appendChild(line);

    return wrap;
  }

  function factorRow(factor, threshold) {
    var row = el('div', 'app-factor wv-stack wv-gap-2');

    var head = el('div', 'wv-row wv-between wv-gap-3');
    head.appendChild(el('span', 'wv-body app-factor__name', factor.name + ' (' + factor.window + ')'));
    head.appendChild(el('span', 'wv-body app-factor__top', F.fmtTop(factor.percentile)));
    row.appendChild(head);

    row.appendChild(factorBar(factor, threshold));

    /* 막대 아래 — 왼쪽에 요인 값, 임계선 자리에 임계선 라벨.
       라벨을 `90` 이라고 쓰지 않는다. 오른쪽에 이미 `상위 13%` 가 있고
       백분위와 상위%는 커지는 방향이 반대라 나란히 두면 비교가 안 된다. (§11) */
    var below = el('div', 'app-bar__below');
    below.appendChild(el('span', 'wv-caption', F.fmtValue(factor.value_raw, factor.unit)));
    var thLabel = el('span', 'app-bar__thlabel', '기준 ' + F.fmtTop(threshold));
    thLabel.style.left = threshold + '%';
    below.appendChild(thLabel);
    row.appendChild(below);

    return row;
  }

  /* ------------------------------------------------------------------
     그룹 카드 하나.

     미채택 그룹도 채택 그룹과 같은 형식으로 그린다 —
     이름(창) · 상위 N% · 막대 · 값 · 임계선 라벨, 그리고 그 아래 판정 문구.
     `판정 기준에 못 미칩니다` 한 줄만 두면 왜 못 미치는지 알 수 없다.
     견본 A 의 배경장은 백분위 61.0(상위 39%)인데 그 숫자가 화면에 없었다.

     구분은 글자 농도로만 한다 — 그룹 이름과 요인 이름 한 단계 흐리게.
     막대·마커·임계선·백분위·값은 그대로 둔다. 흐리면 왜 못 미치는지가
     안 보여서, 값을 보여 주기로 한 이유가 사라진다.
     (요청한 --wv-text-secondary 는 없는 토큰이라 --wv-text-muted 를 쓴다)
     ------------------------------------------------------------------ */
  /* adopted 는 세 가지다. false 와 null 은 다르다.

       true   채택했다
       false  봤는데 기준에 못 미쳤다   → 값과 막대를 보여 주고 그렇게 말한다
       null   아직 못 봤다             → 막대를 그리지 않고 모른다고 말한다

     null 을 false 로 뭉치면 "확인해 보니 평범했다"가 되어, 확인하지 않은 것을
     확인한 것처럼 주장하게 된다. 감추는 것도 안 된다 — 견본 B 의 논지는
     "셋 다 평범했다"인데 둘만 보이면 반쪽이 된다. 값이 없다는 사실이
     화면에 남아야 한다. */
  function isUnknown(g) {
    return g.adopted === null || g.adopted === undefined;
  }

  function groupCard(g, threshold) {
    var card = el('div', 'wv-card wv-card--glass app-group wv-stack wv-gap-3' +
                         (g.adopted === true ? '' : ' app-group--muted'));
    card.appendChild(el('p', 'wv-subtitle app-group__name', g.name));

    if (isUnknown(g)) {
      card.appendChild(el('p', 'wv-caption app-group__verdict', '값을 아직 확인하지 못했습니다'));
      return card;   /* 막대를 그리지 않는다. 그릴 값이 없다. */
    }

    (g.factors || []).forEach(function (f) {
      card.appendChild(factorRow(f, threshold));
    });

    if (!g.adopted) {
      card.appendChild(el('p', 'wv-caption app-group__verdict', '판정 기준에 못 미칩니다'));
    }
    return card;
  }

  /* ------------------------------------------------------------------
     요인 영역 표시 규칙

       stage 가 withheld  → 요인 영역 전체를 보류 문구로 대체 (§11 그대로)
       그 밖              → 모든 그룹을 display_order 순으로 그린다.
                            채택이 하나도 없으면 그 사실을 한 줄 먼저 적고
                            그 아래에 같은 형식으로 나열한다.

     §11 은 "채택이 하나도 없으면 한 줄만 쓰고 그룹을 나열하지 않는다"였다.
     그대로 두면 우리가 아무것도 안 본 것처럼 읽혀 무책임해 보인다.
     본 것을 보여 주고, 그것들이 기준에 못 미쳤다고 말하는 편이 정직하다.

     값 크기로 정렬하지 않는다. display_order 가 순서다.
     ------------------------------------------------------------------ */
  function renderFactors(ev, withheld) {
    var body = $('factors-body');
    if (!body) { return; }
    body.textContent = '';

    /* 보류일에는 요인 영역 자리에 보류 문구가 대신 들어간다.
       그 문구는 이미 바로 위에 있으므로 여기서는 영역을 통째로 감춘다. */
    if (withheld) {
      show('factors', false);
      show('factors-note', false);
      return;
    }

    var groups = (ev.groups || []).slice().sort(function (a, b) {
      return (a.display_order || 0) - (b.display_order || 0);
    });
    var threshold = (ev.adoption_threshold || {}).percentile;
    var adopted = groups.filter(function (g) { return g.adopted; });

    show('factors', true);

    /* 채택이 하나도 없다는 사실을 먼저 짧게 말한다.
       그 아래 나열되는 막대들이 왜 그런지를 보여 준다. */
    if (!adopted.length && groups.length) {
      body.appendChild(el('p', 'wv-body app-factors__none', '평년을 크게 벗어난 요인이 없습니다.'));
    }

    groups.forEach(function (g) {
      body.appendChild(groupCard(g, threshold));
    });

    /* ⓘ 안내는 막대가 그려진 화면에서만 띄운다 (§11).
       이제 미채택 그룹도 막대를 그리므로, 요인이 하나라도 있으면 띄운다.
       보류일에는 groups 가 [] 라 여기 오지 않는다. */
    var hasBar = groups.some(function (g) {
      return !isUnknown(g) && (g.factors || []).length > 0;
    });
    show('factors-note', hasBar);
  }

  function render(ev) {
    var s  = ev.status || {};
    var dq = ev.data_quality || {};
    var withheld = s.stage === 'withheld' || dq.judgment_withheld === true;

    /* ── 머리말 ───────────────────────────────────────────────
       지점명은 근거 파일에서, 해역 표기는 geo.js 의 STATIONS 에서 가져온다.
       해역 표기(`{해역} 해역(확인 중)`)는 지도와 같은 문자열이어야 하고,
       근거 파일의 station.area 는 `충남 천수만` 이라 표기 규약이 다르다.
       둘 중 하나라도 없으면 HTML 에 적힌 글자를 그대로 둔다. */
    var st = ev.station || {};
    if (st.name) { setLine('head-station', st.name); }
    var meta = (global.GEO && global.GEO.station) ? global.GEO.station(st.id) : null;
    if (meta) { setLine('head-area', meta.area); }

    var basisWord = s.sst_basis === 'rolling_24h' ? '24시간 평균' : '일평균';
    var d = F.fmtDate(s.observed_at);
    setLine('head-date', d ? (s.observed_at.slice(0, 4) + '년 ' + d + ' ' + basisWord) : null);

    /* ── 수온 · 평년 대비 ───────────────────────────────────
       보류일에는 두 값이 모두 null 이다. 줄을 감춘다. */
    setLine('sst', F.fmtValue(s.current_sst_raw, '℃'));
    setLine('anomaly', F.fmtAnomaly(s.anomaly_raw));

    /* ── 상태 배지 ──────────────────────────────────────────── */
    setLine('stage-label', s.stage_label || null);

    /* 연속일수는 advisory · warning 에서만 쓴다 (§11 자료 시각) */
    var showDays = (s.stage === 'advisory' || s.stage === 'warning') &&
                   typeof s.days_over_advisory === 'number' && s.days_over_advisory > 0;
    setLine('stage-days', (showDays && d) ? (d + '까지 ' + s.days_over_advisory + '일 연속') : null);

    /* stage_caveat 는 보류일 화면에 띄우지 않는다.
       "이 값은 관측점 재계산치입니다"인데 화면에 값 자체가 없다. (§8) */
    setLine('stage-caveat', withheld ? null : (s.stage_caveat || null));

    /* ── 자료 시각 (§11) ────────────────────────────────────── */
    if (withheld) {
      /* 보류일에는 일평균이 없다. 있는 것처럼 적지 않는다. */
      setLine('data-sst', null);
      setLine('withheld',
        '자료 결측으로 이번 시각은 판정을 보류했습니다. (수온 결측률 ' +
        (F.fmtMissingRate(dq.sst_missing_rate) || '—') + ')');
    } else {
      setLine('withheld', null);
      var obs = typeof dq.obs_count === 'number' ? ' (' + dq.obs_count + '회 관측)' : '';
      setLine('data-sst', d ? ('수온: ' + d + ' ' + basisWord + obs) : null);
    }

    /* 요인 시각. 보류일은 groups 가 [] 라 날짜가 없고, 줄도 없다. */
    var fd = F.fmtDate(earliestFactorDate(ev.groups));
    setLine('data-factor', fd ? ('요인: ' + fd + '까지 자료') : null);

    /* ── 요인 영역 ─────────────────────────────────────────── */
    renderFactors(ev, withheld);

    /* ── 한계 블록 (§11) ────────────────────────────────────
       일곱 줄 중 여섯은 고정 문구라 HTML 에 있다. 평년값 줄만 값을 받는다.
       stage 와 무관하게 항상 보인다 — 보류일에도 마찬가지다. 그래서 §8 이
       보류일 파일에서도 최상위 climatology 블록만은 담기로 했다. */
    var clim = ev.climatology || {};
    setLine('limit-climatology',
      (typeof clim.years === 'number' && typeof clim.sample_size === 'number')
        ? ('평년값: 최근 ' + clim.years + '년 · 표본 ' + clim.sample_size + '일')
        : null);

    show('load-error', false);
    show('content', true);
  }

  function fail(reason) {
    show('content', false);
    show('load-error', true);
    /* 어느 파일을 찾다 실패했는지 적는다 — URL 로 지점이 바뀌므로 */
    var src = $('load-error-source');
    if (src) { src.textContent = SOURCE; }
    var el = $('load-error-detail');
    if (el) { el.textContent = reason; }
  }

  fetch(SOURCE, { cache: 'no-store' })
    .then(function (res) {
      if (!res.ok) { throw new Error(SOURCE + ' — HTTP ' + res.status); }
      return res.json();
    })
    .then(render)
    .catch(function (err) {
      /* file:// 로 열면 fetch 가 CORS 로 막힌다.
         화면을 비워 두지 않고 왜 안 보이는지 적는다. */
      fail(String(err && err.message ? err.message : err));
    });

  global.STATION = { render: render };

}(window));
