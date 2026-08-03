#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify.py — 원자료에서 문서의 숫자를 다시 계산한다

충남 서해 연안 고수온 설명 서비스 · PRD 3.6 §7 · §9 · §13

이 파일이 존재하는 이유
  2026-07-31 시점에 §9 의 견본 값과 §13 의 채택률을 낸 스크립트가
  어디에도 남아 있지 않았다. 문서에 숫자만 있고 계산 과정이 없어서,
  §12 가 3주차 일로 적어 둔 "코드가 이 값을 재현하는지 확인"을 할 수 없었다.
  §14 #2 · #3 이 기록한 "같은 원자료에서 다른 숫자가 나온 적 두 번"도
  같은 이유로 보인다.

  그래서 이 스크립트를 남긴다. 여기가 계산의 단일 출처다.

두 창 규칙을 모두 계산해 나란히 찍는다
  LAG=1  D−7 ~ D−1   §7 규칙. 실시간에서 오늘 일사 합계가 없으므로 이쪽이 맞다
  LAG=0  D−6 ~ D     §9 의 옛 값이 나온 창. 왜 값이 바뀌었는지 대조용으로 남긴다

원자료 (이 맥북 기준)
  ~/김수민/원자료/OBS_ASOS_DD_*.csv          ASOS 129 서산 일자료, CP949
  ~/김수민/원자료/total_{연도}.zip
      └ ys_{연도}.zip                        서해
          └ 서해 {연도} {월}월.csv            CP949, 30분 간격, 관측소 48곳

쓰는 열
  ASOS   합계 일사량(MJ/m2) · 최고기온(°C)
  RISA   관측소 · 관측일시 · 표층수온(℃)

계산 규칙 (§7)
  요인 값      ASOS 7일 평균. 창 안에 하나라도 결측이면 값을 만들지 않는다
  평년 분포    롤링 5년 · 최소 3년, 대상일 ±21일(43일). 4년이면 172일
  백분위       자기보다 작은 표본 수 ÷ 전체 × 100
  채택         그룹 대표(요인 백분위의 최대) ≥ adoption_threshold(90)

실행
  python3 scripts/verify.py            전체
  python3 scripts/verify.py samples    §9 견본 A·B 만
  python3 scripts/verify.py rates      §13 채택률 만
  python3 scripts/verify.py clim       평년 분포 p10/p50/p90 만
  python3 scripts/verify.py hourly     §16 ⑧ 30분 vs 1시간 만
  python3 scripts/verify.py edge       §16 ⑦ A 창 경계 (비용 기록용)
  python3 scripts/verify.py bg         §16 ⑦ #28·#29 배경장 산출률

확정된 결정 (2026-08-03)
  §16 ⑧  일평균은 H1 정시(만점 24). 일 최고만 30분 그대로            confirmed_daily()
  §16 ⑦  A1 — 평년 창은 분석 기간 밖 자료를 쓴다                     clim_samples()
  #28·#29·#38  판정 보류일의 일평균은 어떤 계산에도 쓰지 않는다        reliable_means()
  #34    실효 독립 검정 수 k = ln(1−p)/ln(0.9)                     effective_tests()
"""

import csv, io, math, os, sys, zipfile, datetime as dt
from collections import defaultdict
from fractions import Fraction

RAW = os.path.expanduser('~/김수민/원자료')

# ── 고정값 (PRD) ──────────────────────────────────────────────────
THRESHOLD    = 90          # §7 채택 임계 백분위. 사전 고정
CLIM_HALF    = 21          # 대상일 ±21일 = 43일 창
CLIM_YEARS   = 5           # 롤링 5년
CLIM_MIN     = 3           # 최소 3년
FACTOR_DAYS  = 7           # ASOS 요인 창
CUM_DAYS     = 30          # 누적편차 창
SEASON       = ((5, 15), (9, 30))   # 분석 기간 5/15~9/30, 139일
MISSING_MAX  = 0.20        # 수온 결측률 20% 초과면 보류
OBS_PER_DAY  = 48          # 30분 간격
OBS_PER_DAY_H = 24         # 1시간으로 내렸을 때의 만점 (§16 ⑧)
STA_START    = dt.date(2017, 6, 13)   # 창리 관측 개시 (§3). 이전은 결측이 아니라 부재다

# 평년 재료가 될 수 있는 해. 창리 관측 개시가 2017-06-13 이라 2016 이전은 없다 (§3).
# ASOS 는 2016 부터 있지만 두 자료가 같은 해 집합을 써야 표본이 어긋나지 않는다 —
# 이 집합으로 계산해야 §9 의 표본 158 / 172 (4년 × 43일)가 재현된다.
SST_YEARS    = set(range(2017, 2026))

LAGS = {1: '§7 규칙  D−7~D−1', 0: '옛 창    D−6~D'}


# ── 자료 읽기 ─────────────────────────────────────────────────────

def read_asos():
    """ASOS 129 서산 일자료 → (일사, 최고기온) 두 dict"""
    path = None
    for n in sorted(os.listdir(RAW)):
        if n.startswith('OBS_ASOS_DD_') and n.endswith('.csv'):
            path = os.path.join(RAW, n)
    if not path:
        sys.exit('ASOS 일자료를 찾지 못했습니다: %s/OBS_ASOS_DD_*.csv' % RAW)
    rows = list(csv.reader(io.StringIO(open(path, 'rb').read().decode('cp949'))))
    h = rows[0]
    i_t, i_s = h.index('최고기온(°C)'), h.index('합계 일사량(MJ/m2)')
    tmax, solar = {}, {}
    for r in rows[1:]:
        if not r or r[0] != '129':
            continue
        d = dt.date.fromisoformat(r[2])
        if r[i_t].strip():
            tmax[d] = float(r[i_t])
        if r[i_s].strip():
            solar[d] = float(r[i_s])
    return solar, tmax


def read_sst(years, station='fsch6'):
    """창리 30분 표층수온 → {날짜: [(시각, 값)…]}  (중첩 zip 을 메모리에서 푼다)

    시각을 버리지 않는 이유. §16 ⑧(30분→1시간)을 재려면 어느 시각의 값인지가
    있어야 한다. 값의 집합·순서는 예전과 같으므로 30분 기준 계산은 변하지 않는다.
    """
    out = defaultdict(list)
    for y in years:
        outer = os.path.join(RAW, 'total_%d.zip' % y)
        if not os.path.exists(outer):
            continue
        with zipfile.ZipFile(outer) as z1:
            inner = [n for n in z1.namelist() if n.startswith('ys_')]
            if not inner:
                continue
            with zipfile.ZipFile(io.BytesIO(z1.read(inner[0]))) as z2:
                for name in z2.namelist():
                    rows = list(csv.reader(io.StringIO(
                        z2.read(name).decode('cp949'))))
                    for r in rows[1:]:
                        if not r or station not in r[0] or not r[2].strip():
                            continue
                        out[dt.date.fromisoformat(r[1][:10])].append(
                            (r[1][11:16], float(r[2])))
    return out


# ── 계산 ──────────────────────────────────────────────────────────

def window_mean(series, D, lag, days=FACTOR_DAYS):
    """창 안에 하나라도 결측이면 값을 만들지 않는다 (§7 보간 금지)"""
    vals = []
    for i in range(days):
        v = series.get(D - dt.timedelta(days=i + lag))
        if v is None:
            return None
        vals.append(v)
    return sum(vals) / days


def clim_years(target_year, have=None):
    """롤링 5년 · 최소 3년. 자료가 있는 해만 센다.

    2021 → 2017~2020 (4년, 43일 × 4 = 172). §9 의 표본 수와 맞는다.
    2020 → 2017~2019 (3년, 최소 3년 규칙에 걸려 겨우 성립)."""
    have = SST_YEARS if have is None else have
    ys = [y for y in range(target_year - CLIM_YEARS, target_year) if y in have]
    return ys if len(ys) >= CLIM_MIN else []


def clim_samples(series, D, lag, years, days=FACTOR_DAYS):
    out = []
    for y in years:
        try:
            base = dt.date(y, D.month, D.day)
        except ValueError:          # 2/29
            continue
        for k in range(-CLIM_HALF, CLIM_HALF + 1):
            v = window_mean(series, base + dt.timedelta(days=k), lag, days)
            if v is not None:
                out.append(v)
    return out


def percentile(samples, x):
    """자기보다 작은 표본의 비율. §9 의 87.3 / 90.7 을 재현한 정의."""
    return None if not samples else sum(1 for s in samples if s < x) / len(samples) * 100


def effective_tests(p):
    """실효 독립 검정 수 k — §13 의 「1 − 0.9^k」를 k 에 대해 푼 것

        p = 1 − 0.9^k      →      k = ln(1 − p) / ln(0.9)

    검산. k=1 → 10.0% · k=2 → 19.0% · k=3 → 27.1% 로 §13 표와 일치한다.

    이 식을 여기 적어 두는 이유. 3.7 까지 §13 본문에 「1.3개」라는 수만 있고
    그 수를 낸 식이 어디에도 없었다 — §12:1496 이 기록한 것과 같은 문제다.
    """
    return None if p is None or p >= 1 else math.log(1 - p) / math.log(0.9)


def season_days(year):
    (m0, d0), (m1, d1) = SEASON
    a, b = dt.date(year, m0, d0), dt.date(year, m1, d1)
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


# ── 1. §9 견본 ────────────────────────────────────────────────────

def run_samples(solar, tmax):
    print('═' * 70)
    print('§9 견본 — 두 창 규칙 비교')
    print('═' * 70)
    for label, D in (('견본 A', dt.date(2021, 7, 31)), ('견본 B', dt.date(2021, 8, 5))):
        print('\n%s — 대상일 %s' % (label, D))
        for lag in (1, 0):
            print('  [%s]  %s ~ %s' % (LAGS[lag],
                                       D - dt.timedelta(days=FACTOR_DAYS - 1 + lag),
                                       D - dt.timedelta(days=lag)))
            pcts = {}
            for fac, series in (('일사', solar), ('기온', tmax)):
                v = window_mean(series, D, lag)
                s = clim_samples(series, D, lag, clim_years(D.year))
                p = percentile(s, v)
                pcts[fac] = p
                print('    %s  값 %8.4f   표본 %3d   백분위 %6.2f' % (fac, v, len(s), p))
            rep = max(pcts.values())
            print('    대표 %.2f (%s)  →  %s'
                  % (rep, max(pcts, key=pcts.get), '채택' if rep >= THRESHOLD else '미채택'))


# ── 2. §13 채택률 ─────────────────────────────────────────────────

def daily_sst(sst_raw):
    """30분 관측 → 일평균 · 일최고 · 관측 횟수 · 결측률"""
    out = {}
    for d, pairs in sst_raw.items():
        vals = [v for _, v in pairs]
        out[d] = {'mean': sum(vals) / len(vals), 'max': max(vals),
                  'n': len(vals), 'missing': 1 - len(vals) / OBS_PER_DAY}
    return out


def h1_daily(sst_raw):
    """확정된 규칙으로 만든 일별 수온 (§16 ⑧ H1 정시 · 만점 24)"""
    out = {}
    for d, pairs in sst_raw.items():
        s = day_stat(pairs, 'H1', OBS_PER_DAY_H)
        if s:
            out[d] = s
    return out


def confirmed_daily(sst_raw):
    """확정된 결정을 모두 적용한 일별 값 — §13·배경장 계산의 입력

    일평균 · 관측 횟수 · 결측률   H1 정시, 만점 24        §16 ⑧ 결정 1
    일 최고                      30분 그대로              CHANGES #3

    일 최고만 30분에 남는 이유. 채점 분류(이상군/대조군) 전용이고 화면·문장이
    읽지 않는다. 함께 내리면 :30 의 최고값을 놓쳐 분류가 흔들린다.
    """
    d30 = daily_sst(sst_raw)
    out = {}
    for d, s in h1_daily(sst_raw).items():
        out[d] = dict(s, max=d30[d]['max'])
    return out


def sst_clim(mean_series, D, years):
    """§8 climatology_mean — 대상일 ±21일 × 평년 연도. (평년값, 표본 수)"""
    smp = []
    for y in years:
        try:
            base = dt.date(y, D.month, D.day)
        except ValueError:
            continue
        for k in range(-CLIM_HALF, CLIM_HALF + 1):
            v = mean_series.get(base + dt.timedelta(days=k))
            if v is not None:
                smp.append(v)
    return ((sum(smp) / len(smp)) if smp else None), len(smp)


def reliable_means(daily):
    """배경장이 쓰는 일평균 — 결측률 20% 초과일은 뺀다 (§16 ⑦ #29)

    §8 이 그런 날의 `current_sst` 를 null 로 두고 판정 보류로 선언했다.
    화면에 「이 날의 수온은 믿을 수 없다」고 말해놓고 그 일평균을 다른 계산에
    쓰면 모순이므로, 배경장 30일 창에서도 결측으로 본다.

    평년값(clim_day)도 같은 집합에서 만든다. 한 날의 일평균을 합산에서는
    못 믿겠다면서 평년 표본으로는 쓰는 것이 앞뒤가 맞지 않기 때문이다.
    """
    return {d: v['mean'] for d, v in daily.items() if v['missing'] <= MISSING_MAX}


def run_rates(solar, tmax, sst):
    print('═' * 70)
    print('§13 채택률 — 개발용 구간 2020~2021')
    print('═' * 70)
    print('입력: H1 일평균(만점 24) · 일 최고는 30분 · 보류일 제외 (§16 ⑧ · #38)\n')
    daily = confirmed_daily(sst)
    mean_series = reliable_means(daily)
    cums = {y: make_cum(mean_series, clim_years(y)) for y in (2020, 2021)}

    for lag in (1, 0):
        print('\n[%s]' % LAGS[lag])
        rows = []
        n_season = n_asos = n_hold = 0
        asos_gap = []
        for year in (2020, 2021):
            ys = clim_years(year)
            cum = cums[year]
            for D in season_days(year):
                n_season += 1
                fv = {f: window_mean(s, D, lag)
                      for f, s in (('일사', solar), ('기온', tmax))}
                if any(v is None for v in fv.values()):
                    asos_gap.append(D)            # ASOS 7일 평균 미산출
                    continue
                n_asos += 1
                day = daily.get(D)
                if day is None or day['missing'] > MISSING_MAX:
                    n_hold += 1
                    continue                      # 수온 결측·부재로 보류
                pcts = {}
                for f, s in (('일사', solar), ('기온', tmax)):
                    smp = clim_samples(s, D, lag, ys)
                    pcts[f] = percentile(smp, fv[f]) if smp else None
                if any(v is None for v in pcts.values()):
                    continue
                heat = max(pcts.values())

                # 배경장 — 30일 누적편차. 수온 자료라 창이 당일까지다 (§7)
                cv = cum(D)
                bg = None
                if cv is not None:
                    smp = []
                    for y in ys:
                        try:
                            base = dt.date(y, D.month, D.day)
                        except ValueError:
                            continue
                        for k in range(-CLIM_HALF, CLIM_HALF + 1):
                            c = cum(base + dt.timedelta(days=k))
                            if c is not None:
                                smp.append(c)
                    bg = percentile(smp, cv) if smp else None

                rows.append({'date': D, 'max': day['max'],
                             'heat': heat, 'bg': bg,
                             'heat_ok': heat >= THRESHOLD,
                             'bg_ok': bg is not None and bg >= THRESHOLD,
                             'adopted': heat >= THRESHOLD or (bg is not None and bg >= THRESHOLD)})

        print('  분석 기간 139일 × 2년        %4d' % n_season)
        print('  − ASOS 7일 평균 미산출       −%3d   %s ~ %s'
              % (n_season - n_asos, asos_gap[0], asos_gap[-1]) if asos_gap else '')
        print('  = ASOS 산출 가능일           %4d' % n_asos)
        print('  − 수온 결측·부재로 보류      −%3d' % n_hold)
        print('  = 판정 대상일                %4d' % len(rows))
        print()
        groups = [('전체', rows),
                  ('대조군 (일 최고 < 28℃)', [r for r in rows if r['max'] < 28]),
                  ('이상군 (일 최고 ≥ 28℃)', [r for r in rows if r['max'] >= 28])]
        print('  %-24s %6s | %6s %8s %6s | %6s %8s %6s' %
              ('구분', '일수', '열유입', '비율', 'k', '전체', '비율', 'k'))
        rate = {}
        for name, g in groups:
            h = sum(1 for r in g if r['heat_ok'])
            a = sum(1 for r in g if r['adopted'])
            rh = (h / len(g) * 100) if g else 0
            ra = (a / len(g) * 100) if g else 0
            rate[name[:3]] = rh          # 실패 기준은 문서 정의(열유입)로 본다
            kh, ka = effective_tests(rh / 100), effective_tests(ra / 100)
            print('  %-24s %6d | %6d %7.1f%% %6.2f | %6d %7.1f%% %6.2f'
                  % (name, len(g), h, rh, kh, a, ra, ka))
        print('  * 열유입 = §13 의 35/29/6 을 재현하는 정의. 전체 = 배경장까지 포함')
        print('  * k = 실효 독립 검정 수 = ln(1−p)/ln(0.9). §13 의 「1 − 0.9^k」를 푼 것')
        print()
        print('  어느 그룹이 채택을 만들었나')
        for name, g in groups:
            print('    %-24s 열유입 %3d · 배경장 %3d · 둘 다 %3d · 열유입만 %3d'
                  % (name,
                     sum(1 for r in g if r['heat_ok']),
                     sum(1 for r in g if r['bg_ok']),
                     sum(1 for r in g if r['heat_ok'] and r['bg_ok']),
                     sum(1 for r in g if r['heat_ok'] and not r['bg_ok'])))
        ok = rate['이상군'] > rate['대조군']
        print('\n  실패 기준 1 (이상군 ≤ 대조군) : %s'
              % ('통과 — 이상군 %.1f%% > 대조군 %.1f%%' % (rate['이상군'], rate['대조군'])
                 if ok else '실패'))


def make_cum(mean_series, ys):
    """30일 누적편차를 계산하는 함수를 만든다. 평년 기준연도(ys)를 고정해서 받는다.

    기준을 고정하는 이유. 과거 연도의 누적편차를 그 해의 롤링 평년으로 재면
    2017~2019 는 롤링 3년을 못 채워 표본이 통째로 사라진다(2020 만 남아 43개).
    §9 견본 A 의 `cum_anomaly.clim_sample_size` 가 172(4년 × 43)이므로,
    대상일의 평년 기준을 그대로 두고 과거 같은 시기를 재는 방식이 맞다.

    누적편차 = Σ(일평균 − 그날의 평년값), 창은 D−29 ~ D.
    배경장은 수온 자료라 창이 당일까지다 — ASOS 요인과 달리 하루 밀지 않는다 (§7).

    같은 날의 평년값과 누적편차를 수만 번 다시 계산하게 되므로 결과를 기억해 둔다.
    (없으면 채택률 한 번 도는 데 몇 시간이 걸린다)
    """
    clim_cache, cum_cache = {}, {}

    def clim_day(d):
        if d in clim_cache:
            return clim_cache[d]
        smp = []
        for y in ys:
            try:
                base = dt.date(y, d.month, d.day)
            except ValueError:
                continue
            for k in range(-CLIM_HALF, CLIM_HALF + 1):
                x = mean_series.get(base + dt.timedelta(days=k))
                if x is not None:
                    smp.append(x)
        clim_cache[d] = (sum(smp) / len(smp)) if smp else None
        return clim_cache[d]

    def cum(D):
        if D in cum_cache:
            return cum_cache[D]
        total = 0.0
        for i in range(CUM_DAYS):
            d = D - dt.timedelta(days=i)
            v, c = mean_series.get(d), clim_day(d)
            if v is None or c is None:
                cum_cache[D] = None
                return None
            total += v - c
        cum_cache[D] = total
        return total

    return cum


# ── 3. §16 ⑧ 시간 해상도 ─────────────────────────────────────────

def to_hourly(pairs, mode):
    """30분 관측을 1시간으로 내린다. 만점은 24.

    H1 정시      `:00` 행만 쓴다. 실시간이 시간당 스냅숏 하나를 긁는 것과 성질이 같다
    H2 시간대    시간대 안에 값이 있으면 그 시간을 채운 것으로 본다. 둘 다 있으면 평균

    H1 이 하한, H2 가 상한이다. 둘 사이 간격이 곧 과거를 실시간에 맞추는 비용이다.
    """
    if mode == 'H1':
        return [(t, v) for t, v in pairs if t.endswith(':00')]
    byh = defaultdict(list)
    for t, v in pairs:
        byh[t[:2]].append(v)
    return [(h + ':00', sum(vs) / len(vs)) for h, vs in sorted(byh.items())]


# (이름, 변환 모드, 만점)
BASES = (('30분', None, OBS_PER_DAY),
         ('H1 정시', 'H1', OBS_PER_DAY_H),
         ('H2 시간대', 'H2', OBS_PER_DAY_H))


def day_stat(pairs, mode, full):
    """하루치 (시각, 값) → 관측 횟수 · 결측률 · 일평균 · 일최고. 값이 없으면 None"""
    p = pairs if mode is None else to_hourly(pairs, mode)
    if not p:
        return None
    vals = [v for _, v in p]
    return {'n': len(vals), 'missing': max(0.0, 1 - len(vals) / full),
            'mean': sum(vals) / len(vals), 'max': max(vals)}


def stats_by_basis(sst_raw):
    """{기준이름: {날짜: day_stat}}"""
    out = {}
    for name, mode, full in BASES:
        out[name] = {d: s for d, pairs in sst_raw.items()
                     for s in [day_stat(pairs, mode, full)] if s}
    return out


def run_hourly(sst_raw):
    YEARS = range(2017, 2022)
    st = stats_by_basis(sst_raw)
    all_days = [D for y in YEARS for D in season_days(y)]
    total = len(all_days)

    print('═' * 74)
    print('§16 ⑧ 시간 해상도 — 30분 / H1 정시 / H2 시간대')
    print('═' * 74)
    print('분석 기간 5/15~9/30 × %d년 (%d~%d) = %d일\n'
          % (len(list(YEARS)), min(YEARS), max(YEARS), total))

    # ── 1. 보류일·보류율 ────────────────────────────────────────
    print('─' * 74)
    print('1. 보류일과 보류율   (분모 = 분석 기간 %d일, CHANGES #7)' % total)
    print('─' * 74)

    norow = [D for D in all_days if D not in st['30분']]
    pre   = [D for D in norow if D < STA_START]
    post  = [D for D in norow if D >= STA_START]
    print('\n(a) 행이 아예 없는 날  %d일' % len(norow))
    print('    ├ 관측 개시(%s) 전   %2d일   %s ~ %s'
          % (STA_START, len(pre), pre[0], pre[-1]) if pre else '')
    print('    └ 개시 후 실제 부재    %2d일   %s'
          % (len(post), ', '.join(str(d) for d in post)))
    print('    ※ 행이 없는 날은 세 기준 모두에서 같다 (원자료에 행 자체가 없다)')

    print('\n(b)(c) 기준별 — 결측률 20% 초과 판정은 만점이 달라 기준마다 다르다\n')
    hdr = ('  %-10s %6s %8s | %6s %6s %7s | %6s %7s'
           % ('기준', '만점', '결측허용', '(a)행없음', '(b)>20%', '(c)보류', '보류율', '개시전제외'))
    print(hdr)
    print('  ' + '─' * 70)
    summary = {}
    for name, mode, full in BASES:
        over = [D for D in all_days if D in st[name] and st[name][D]['missing'] > MISSING_MAX]
        hold = len(norow) + len(over)
        rate = hold / total * 100
        # 개시 전 29일을 분자·분모에서 모두 뺀 값
        hold2, tot2 = hold - len(pre), total - len(pre)
        rate2 = hold2 / tot2 * 100
        allow = int(full * MISSING_MAX)
        print('  %-10s %6d %8s | %9d %7d %7d | %6.1f%% %8.1f%%'
              % (name, full, '%d회' % allow, len(norow), len(over), hold, rate, rate2))
        summary[name] = {'over': over, 'hold': hold, 'rate': rate,
                         'hold2': hold2, 'tot2': tot2, 'rate2': rate2}
    print('\n  개시전제외 = 2017-05-15~06-12 %d일을 분자·분모에서 모두 뺀 값 (분모 %d)'
          % (len(pre), total - len(pre)))

    print('\n  연도별 (b) 결측률 20% 초과')
    print('  %-10s %s' % ('기준', ' '.join('%6d' % y for y in YEARS)))
    for name, _, _ in BASES:
        cnt = [sum(1 for D in summary[name]['over'] if D.year == y) for y in YEARS]
        print('  %-10s %s' % (name, ' '.join('%6d' % c for c in cnt)))

    print('\n  §13 보류율 표 재현 (30분 기준)')
    s = summary['30분']
    for label, got, want in (('분석 기간 총합', total, 695),
                             ('관측 자체가 없던 날', len(norow), 31),
                             ('관측일 중 결측률 20% 초과', len(s['over']), 28),
                             ('보류율 (%)', round(s['rate'], 1), 8.5)):
        ok = '일치' if got == want else '불일치'
        print('    %-26s 문서 %6s   계산 %6s   %s' % (label, want, got, ok))

    # ── 2. 일평균 차이 ──────────────────────────────────────────
    print('\n' + '─' * 74)
    print('2. 일평균이 달라지는 날   (daily_max_sst 는 30분 고정이므로 비교 대상 아님)')
    print('─' * 74)

    for label, sel in (('세 기준 모두 값이 나오는 날', lambda n, D: D in st[n]),
                       ('세 기준 모두 판정 대상 (결측률 ≤ 20%)',
                        lambda n, D: D in st[n] and st[n][D]['missing'] <= MISSING_MAX)):
        days = [D for D in all_days if all(sel(n, D) for n, _, _ in BASES)]
        print('\n  [%s]  %d일' % (label, len(days)))
        print('  %-16s %8s %8s %8s %10s %12s'
              % ('비교', '>0.005', '>0.05', '>0.1', '최대차이', '그날'))
        for other in ('H1 정시', 'H2 시간대'):
            diffs = [(abs(st['30분'][D]['mean'] - st[other][D]['mean']), D) for D in days]
            if not diffs:
                continue
            mx, mxd = max(diffs)
            print('  %-16s %8d %8d %8d %9.4f℃ %12s'
                  % ('30분 vs ' + other,
                     sum(1 for v, _ in diffs if v > 0.005),
                     sum(1 for v, _ in diffs if v > 0.05),
                     sum(1 for v, _ in diffs if v > 0.1), mx, mxd))
        # 28℃ 선을 넘나드는 날 — days_over_advisory 가 바뀐다
        print('\n  일평균 28℃ 선을 넘나드는 날 (days_over_advisory 영향)')
        for other in ('H1 정시', 'H2 시간대'):
            flip = [D for D in days
                    if (st['30분'][D]['mean'] >= 28) != (st[other][D]['mean'] >= 28)]
            print('    30분 vs %-12s %d일  %s'
                  % (other, len(flip), ', '.join(str(d) for d in flip) or '—'))

    # ── 2-b. 화면 표시가 바뀌는 날 ────────────────────────────
    # 차이의 크기가 아니라 표시가 바뀌는 날의 수다.
    # 반올림 경계 근처에서는 0.002℃ 차이로도 표시가 갈린다.
    #
    # 부동소수점을 쓰지 않는다. 2017-06-17 의 일평균은 정확히 22.25 인데,
    # float 로 48 개를 더하면 22.2499999999999893 이 되어 30분만 22.2 로 떨어진다.
    # 원자료가 전부 소수 1자리 이하이므로 1/10 단위 정수로 정확히 다룰 수 있다.
    #
    # §10 은 "원값을 소수 첫째 자리 사사오입"이라 파이썬 round() 도 쓰지 않는다
    # (round() 는 은행가 반올림이라 22.25 → 22.2 로 내려간다).
    def disp10(pairs, mode):
        """일평균을 사사오입한 소수 1자리 표시값. 1/10 단위 정수로 돌려준다."""
        p = pairs if mode is None else to_hourly(pairs, mode)
        tenths = [Fraction(round(v * 10)) for _, v in p]
        m = sum(tenths) / len(tenths)          # 1/10 단위 평균 (정확)
        return (2 * m + 1) // 2                # floor(m + 1/2) = 사사오입

    print('\n  화면 표시(소수 1자리, §10 사사오입)가 바뀌는 날')
    judged = [D for D in all_days
              if all(D in st[n] and st[n][D]['missing'] <= MISSING_MAX
                     for n, _, _ in BASES)]
    print('  판정 대상 %d일 기준' % len(judged))
    shown = {name: {D: disp10(sst_raw[D], mode) for D in judged}
             for name, mode, _ in BASES}
    for other in ('H1 정시', 'H2 시간대'):
        flip = [D for D in judged if shown['30분'][D] != shown[other][D]]
        pct = len(flip) / len(judged) * 100
        print('    30분 vs %-12s %3d일 / %d일 = %5.1f%%   기준 5%%(%d일) %s'
              % (other, len(flip), len(judged), pct, round(len(judged) * 0.05),
                 '충족' if pct >= 5 else '미충족'))
        if flip:
            print('      예: ' + ', '.join(
                '%s (%.1f℃ / %.1f℃)'
                % (D, shown['30분'][D] / 10, shown[other][D] / 10)
                for D in flip[:3]))

    # 참고 — 만약 daily_max 까지 함께 내렸다면 어떻게 되는가
    days = [D for D in all_days if all(D in st[n] for n, _, _ in BASES)]
    print('\n  [참고] daily_max 도 함께 내렸을 경우 이상군/대조군 분류가 바뀌는 날')
    for other in ('H1 정시', 'H2 시간대'):
        flip = [D for D in days
                if (st['30분'][D]['max'] >= 28) != (st[other][D]['max'] >= 28)]
        print('    30분 vs %-12s %d일  %s'
              % (other, len(flip), ', '.join(str(d) for d in flip) or '—'))
    print('    ※ 분리하기로 했으므로 실제로는 흔들리지 않는다. 분리의 값을 보이는 수치다')

    # ── 3. 견본 C ───────────────────────────────────────────────
    print('\n' + '─' * 74)
    print('3. 견본 C — 2021-08-11')
    print('─' * 74)
    C = dt.date(2021, 8, 11)
    print('  %-10s %8s %10s %10s %10s %8s'
          % ('기준', '관측횟수', '결측률', '일평균', '일최고', '판정'))
    for name, _, full in BASES:
        s = st[name].get(C)
        if not s:
            continue
        print('  %-10s %5d/%-3d %9.1f%% %9.2f℃ %9.2f℃ %8s'
              % (name, s['n'], full, s['missing'] * 100, s['mean'], s['max'],
                 '보류' if s['missing'] > MISSING_MAX else '판정'))
    print('\n  문서값: 관측 29회 · 결측률 39.6% (§9 견본 C, data/sample-c.json)')


# ── 4. §16 ⑦ 창 경계 — 비용 기록용 ───────────────────────────────
#
# A 는 규칙만으로 이미 정해졌다. 2020년 대상일 5/15 를 A2(분석 기간 밖을 안 쓴다)로
# 계산하면 표본이 44일이다 — §7 표가 판정 가능의 하한으로 적어 둔 「3년 = 129일」의
# 3분의 1이다. A2 는 §7 의 최소 3년 규칙과 정면으로 충돌하므로 A1(쓴다)로 확정한다.
# 아래 비교는 판단 근거가 아니라 **A2 를 택했다면 치렀을 비용의 기록**이다.

def in_season(d):
    (m0, d0), (m1, d1) = SEASON
    return (m0, d0) <= (d.month, d.day) <= (m1, d1)


def clim_samples_clip(series, D, lag, years, days=FACTOR_DAYS):
    """clim_samples 와 같되 분석 기간 밖의 대상일을 표본에서 뺀다 (A2)"""
    out = []
    for y in years:
        try:
            base = dt.date(y, D.month, D.day)
        except ValueError:
            continue
        for k in range(-CLIM_HALF, CLIM_HALF + 1):
            d = base + dt.timedelta(days=k)
            if not in_season(d):
                continue
            v = window_mean(series, d, lag, days)
            if v is not None:
                out.append(v)
    return out


def run_edge(solar, tmax, sst):
    print('═' * 74)
    print('§16 ⑦ A — 창 경계   [비용 기록용. 판단 근거 아님]')
    print('═' * 74)
    print('A1 쓴다 (현행) / A2 분석 기간 밖을 안 쓴다\n')

    print('A 가 규칙만으로 정해진 자리')
    D0, ys0 = dt.date(2020, 5, 15), clim_years(2020)
    daily = daily_sst(sst)
    mean_series = {d: v['mean'] for d, v in daily.items()}
    n2 = sum(1 for y in ys0 for k in range(-CLIM_HALF, CLIM_HALF + 1)
             if in_season(dt.date(y, 5, 15) + dt.timedelta(days=k))
             and (dt.date(y, 5, 15) + dt.timedelta(days=k)) in mean_series)
    print('  2020년 대상일 5/15, 평년 연도 %s' % ys0)
    print('  A2 수온 평년 표본 = %d일   §7 표의 3년 하한 = %d일   → **충돌**\n'
          % (n2, 3 * (2 * CLIM_HALF + 1)))

    rows = []
    for year in (2020, 2021):
        ys = clim_years(year)
        for D in season_days(year):
            fv = {f: window_mean(s, D, 1) for f, s in (('일사', solar), ('기온', tmax))}
            if any(v is None for v in fv.values()):
                continue
            day = daily.get(D)
            if day is None or day['missing'] > MISSING_MAX:
                continue
            p1, p2, n1s, n2s = {}, {}, [], []
            for f, s in (('일사', solar), ('기온', tmax)):
                a = clim_samples(s, D, 1, ys)
                b = clim_samples_clip(s, D, 1, ys)
                p1[f] = percentile(a, fv[f]) if a else None
                p2[f] = percentile(b, fv[f]) if b else None
                n1s.append(len(a)); n2s.append(len(b))
            if any(v is None for v in list(p1.values()) + list(p2.values())):
                continue
            rows.append({'D': D, 'r1': max(p1.values()), 'r2': max(p2.values()),
                         'n1': min(n1s), 'n2': min(n2s),
                         'edge': not (in_season(D - dt.timedelta(days=CLIM_HALF))
                                      and in_season(D + dt.timedelta(days=CLIM_HALF)))})
    edge = [r for r in rows if r['edge']]
    flip = [r for r in rows if (r['r1'] >= THRESHOLD) != (r['r2'] >= THRESHOLD)]
    print('개발용 2020~2021 판정 대상일 %d일 중 경계에 걸리는 날 %d일 (%.1f%%)'
          % (len(rows), len(edge), len(edge) / len(rows) * 100))
    print('  요인 평년 표본 최소   A1 %d일 → A2 %d일'
          % (min(r['n1'] for r in rows), min(r['n2'] for r in rows)))
    print('  열유입 대표 백분위가 5 이상 움직인 날   %d일'
          % sum(1 for r in rows if abs(r['r1'] - r['r2']) >= 5))
    print('  **채택 여부가 뒤집히는 날   %d일 (%.1f%%)**'
          % (len(flip), len(flip) / len(rows) * 100))
    for r in flip[:8]:
        print('     %s  A1 %.1f %s → A2 %.1f %s  (표본 %d→%d)'
              % (r['D'], r['r1'], '채택' if r['r1'] >= THRESHOLD else '미채택',
                 r['r2'], '채택' if r['r2'] >= THRESHOLD else '미채택', r['n1'], r['n2']))


# ── 5. §16 ⑦ #28·#29 배경장 산출률 ───────────────────────────────
#
# #29  결측률 20% 초과일은 배경장 창에서도 결측이다
# #28  §7 보간 금지를 30일 창에 그대로 적용한다 — 창에 하나라도 결측이면 값이 없다
#      (30/N 환산은 없는 날을 평균으로 메우는 것과 수학적으로 같아 보간이다)
#
# 배경장이 산출되지 않아도 그 날은 판정 보류가 아니다. 배경장 그룹만 adopted:null 이고
# ASOS 요인은 그대로 판정되며 §13 채택률 분모(판정 대상일)는 ASOS 기준이라 안 바뀐다.
# 아래 산출률은 기록용이다 — 규칙을 바꾸는 데 쓰지 않는다.

def run_bg(solar, tmax, sst):
    print('═' * 74)
    print('§16 ⑦ #28·#29 — 배경장 산출률   [기록용. 규칙 변경 근거 아님]')
    print('═' * 74)
    daily = confirmed_daily(sst)
    variants = (('옛 규칙  0행인 날만 결측', {d: v['mean'] for d, v in daily.items()}),
                ('새 규칙  결측률 20% 초과도 결측 (#29·#38)', reliable_means(daily)))

    for label, mean_series in variants:
        cums = {y: make_cum(mean_series, clim_years(y)) for y in (2020, 2021)}
        n_judged = n_bg = n_bg_ok = 0
        n_heat_ok = n_adopted = 0
        groups = {'대조군': [0, 0, 0], '이상군': [0, 0, 0]}   # 판정대상 · 배경장산출 · 배경장채택
        for year in (2020, 2021):
            ys, cum = clim_years(year), cums[year]
            for D in season_days(year):
                fv = {f: window_mean(s, D, 1) for f, s in (('일사', solar), ('기온', tmax))}
                if any(v is None for v in fv.values()):
                    continue
                day = daily.get(D)
                if day is None or day['missing'] > MISSING_MAX:
                    continue
                pcts = {}
                for f, s in (('일사', solar), ('기온', tmax)):
                    smp = clim_samples(s, D, 1, ys)
                    pcts[f] = percentile(smp, fv[f]) if smp else None
                if any(v is None for v in pcts.values()):
                    continue
                n_judged += 1
                heat = max(pcts.values())
                heat_ok = heat >= THRESHOLD
                n_heat_ok += heat_ok

                cv = cum(D)
                bg = None
                if cv is not None:
                    smp = []
                    for y in ys:
                        try:
                            base = dt.date(y, D.month, D.day)
                        except ValueError:
                            continue
                        for k in range(-CLIM_HALF, CLIM_HALF + 1):
                            c = cum(base + dt.timedelta(days=k))
                            if c is not None:
                                smp.append(c)
                    bg = percentile(smp, cv) if smp else None
                bg_ok = bg is not None and bg >= THRESHOLD
                n_bg += bg is not None
                n_bg_ok += bg_ok
                n_adopted += (heat_ok or bg_ok)
                g = groups['이상군' if day['max'] >= 28 else '대조군']
                g[0] += 1; g[1] += bg is not None; g[2] += bg_ok

        print('\n[%s]' % label)
        print('  판정 대상일                 %3d   (ASOS 기준. 배경장 미산출로 줄지 않는다)' % n_judged)
        print('  배경장 산출됨               %3d   = %.1f%%' % (n_bg, n_bg / n_judged * 100))
        print('  배경장 미산출 (adopted:null) %3d   = %.1f%%'
              % (n_judged - n_bg, (n_judged - n_bg) / n_judged * 100))
        print('  배경장 채택 (≥90)           %3d   §13 문서값 17' % n_bg_ok)
        print('  열유입 채택                 %3d   (수온 규칙과 무관 — 바뀌지 않는다)' % n_heat_ok)
        print('  하나라도 채택               %3d   = %.1f%%' % (n_adopted, n_adopted / n_judged * 100))
        for name in ('대조군', '이상군'):
            a, b, c = groups[name]
            print('    %s (일 최고 %s 28℃)  판정 %3d · 배경장 산출 %3d · 배경장 채택 %2d'
                  % (name, '≥' if name == '이상군' else '<', a, b, c))


# ── 6. 평년 분포 ──────────────────────────────────────────────────

def quantile(sorted_vals, q):
    """percentile() 과 같은 정의의 역함수 — 아래쪽 비율이 q 가 되는 값"""
    if not sorted_vals:
        return None
    i = min(int(q / 100 * len(sorted_vals)), len(sorted_vals) - 1)
    return sorted_vals[i]


def run_clim(solar, tmax):
    print('═' * 70)
    print('평년 분포 p10 / p50 / p90 — §7 규칙(D−7~D−1) 기준')
    print('═' * 70)
    print('p90 이 곧 채택 임계값이다.\n')
    for label, D in (('견본 A  2021-07-31', dt.date(2021, 7, 31)),
                     ('견본 B  2021-08-05', dt.date(2021, 8, 5))):
        print('%s' % label)
        ys = clim_years(D.year)
        for fac, series, unit in (('일사', solar, 'MJ/m²'), ('기온', tmax, '℃')):
            s = sorted(clim_samples(series, D, 1, ys))
            cur = window_mean(series, D, 1)
            p10, p50, p90 = (quantile(s, q) for q in (10, 50, 90))
            print('  %s  표본 %3d   p10 %6.2f   p50 %6.2f   p90 %6.2f %s'
                  % (fac, len(s), p10, p50, p90, unit))
            print('        당일 %6.2f  →  %s' % (cur, '임계 초과' if cur >= p90 else '임계 미달'))
        print()


# ── 실행 ──────────────────────────────────────────────────────────

def main():
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    solar, tmax = read_asos()
    print('ASOS 129 서산 — 일사 %d일 · 최고기온 %d일\n' % (len(solar), len(tmax)))

    if what in ('all', 'samples'):
        run_samples(solar, tmax); print()
    if what in ('all', 'clim'):
        run_clim(solar, tmax); print()
    if what in ('all', 'rates', 'hourly', 'edge', 'bg'):
        print('창리 수온 읽는 중 (zip 여러 개, 시간이 걸립니다)…')
        sst = read_sst(range(2016, 2022))
        print('  %d일\n' % len(sst))
        if what in ('all', 'hourly'):
            run_hourly(sst); print()
        if what in ('all', 'edge'):
            run_edge(solar, tmax, sst); print()
        if what in ('all', 'bg'):
            run_bg(solar, tmax, sst); print()
        if what in ('all', 'rates'):
            run_rates(solar, tmax, sst)


if __name__ == '__main__':
    main()
