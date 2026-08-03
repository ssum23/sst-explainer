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
  python3 scripts/verify.py bc         §16 ⑦ B·C 3년 미만 판정
  python3 scripts/verify.py evidence   견본 JSON 3종이 코드와 일치하는지 검증
  python3 scripts/verify.py build      견본 JSON 3종 재생성 (파일을 고친다)

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

    for lag in (1, 0):
        print('\n[%s]' % LAGS[lag])
        rows = []
        n_season = n_asos = n_hold = n_noclim = 0
        asos_gap = []
        for year in (2020, 2021):
            cum_by_years = {}
            for D in season_days(year):
                n_season += 1
                ys = clim_years_daily(mean_series, D, C_NEED)   # §16 ⑦ B·C 확정
                if not ys:
                    n_noclim += 1
                    continue
                key = tuple(ys)
                if key not in cum_by_years:
                    cum_by_years[key] = make_cum(mean_series, list(ys))
                cum = cum_by_years[key]
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
        print('  − 평년 3년 미만 (⑦ C2)      −%3d' % n_noclim)
        print('  − ASOS 7일 평균 미산출       −%3d   %s ~ %s'
              % (len(asos_gap), asos_gap[0], asos_gap[-1]) if asos_gap else '')
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


# ── 6. §16 ⑦ B·C — 「3년 미만」이 연 단위인가 일 단위인가 ─────────
#
# B  연 단위    2020 → 2017·2018·2019 = 3년. 창리 개시(2017-06-13) 전이어도 3년으로 센다
#    일 단위    대상일마다 그 해가 실제로 기여했는지 보고 3년 미만이면 판정하지 않는다
# C  일 단위일 때 「그 해가 있다」의 기준
#
# 연도 집합은 수온 일평균 가용성으로 정한다. 개시일 문제는 수온에만 있고(ASOS 는
# 2016 부터 완비), §7 이 「수온과 ASOS 는 같은 연도 창을 쓴다」고 못박았기 때문이다.
# 변수별 표본 수가 다른 것은 §7 이 이미 인정한다(견본 A 일사 158 / 기온 172).

C_RULES = (('C1 하루라도', 1), ('C2 절반 이상', 22), ('C3 43일 전부', 43))

# 확정값 (§16 ⑦ B·C, 2026-08-03). 「3년 미만」은 일 단위이며 기준은 C2 다 —
# 43일 창에 22일 이상 기여한 해만 1년으로 센다.
# 연 단위는 2020-05-15 에서 2017년이 하루도 기여하지 않는데 3년으로 세어
# 표본 85일(실질 2년치)로 판정한다. A2 를 물리친 것과 같은 문제다.
C_NEED = 22


def year_contrib(mean_series, y, D):
    """평년 연도 y 가 대상일 D 의 43일 창에 며칠 기여하는가 (수온 일평균 기준)"""
    try:
        base = dt.date(y, D.month, D.day)
    except ValueError:
        return 0
    return sum(1 for k in range(-CLIM_HALF, CLIM_HALF + 1)
               if (base + dt.timedelta(days=k)) in mean_series)


def clim_years_daily(mean_series, D, need):
    """일 단위 판정. need 일 이상 기여한 해만 세고, 3년 미만이면 판정하지 않는다"""
    ys = [y for y in range(D.year - CLIM_YEARS, D.year)
          if y in SST_YEARS and year_contrib(mean_series, y, D) >= need]
    return ys if len(ys) >= CLIM_MIN else []


def run_bc(solar, tmax, sst):
    print('═' * 74)
    print('§16 ⑦ B·C — 「3년 미만」이 연 단위인가 일 단위인가')
    print('═' * 74)
    daily = confirmed_daily(sst)
    mean_series = reliable_means(daily)

    print('\n창리 개시(%s)가 2020년 대상일에 어떻게 걸리는가' % STA_START)
    print('  대상일   2017년 기여일수 / 43')
    for md in ((5, 15), (5, 22), (5, 23), (6, 4), (6, 22), (7, 3), (7, 4), (8, 5)):
        D = dt.date(2020, *md)
        n = year_contrib(mean_series, 2017, D)
        flags = ' '.join('%s %s' % (nm, '○' if n >= k else '✕') for nm, k in C_RULES)
        print('  %s      %2d      %s' % (D, n, flags))

    rules = [('연 단위 (현행)', None)] + list(C_RULES)
    print('\n개발용 2020~2021 — 분석 기간 139일 × 2년 = 278일')
    print('  %-14s %8s %8s %8s %10s %10s'
          % ('기준', '판정대상', '이상군', '대조군', '수온표본최소', '배경장산출'))
    out = {}
    for label, need in rules:
        n_judge = n_ab = n_ctl = n_bg = 0
        smin = 10 ** 9
        lost = []
        for year in (2020, 2021):
            cum_cache = {}
            for D in season_days(year):
                ys = clim_years(year) if need is None \
                    else clim_years_daily(mean_series, D, need)
                if not ys:
                    lost.append(D)
                    continue
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
                n_judge += 1
                if day['max'] >= 28:
                    n_ab += 1
                else:
                    n_ctl += 1
                _, ns = sst_clim(mean_series, D, ys)
                smin = min(smin, ns)
                key = tuple(ys)
                if key not in cum_cache:
                    cum_cache[key] = make_cum(mean_series, list(ys))
                if cum_cache[key](D) is not None:
                    n_bg += 1
        out[label] = (n_judge, n_ab, n_ctl, smin, n_bg, lost)
        print('  %-14s %8d %8d %8d %10d %10d'
              % (label, n_judge, n_ab, n_ctl, smin, n_bg))

    base_ab = out['연 단위 (현행)'][1]
    print('\n  사전 기준 — 일 단위로 개발용 이상군이 %d일에서 **15일 미만**으로 줄면'
          % base_ab)
    print('  연 단위로 후퇴하고 §7 에 「2020년 5~7월 초는 실질 2년치」를 명시한다.')
    for label, _ in C_RULES:
        ab = out[label][1]
        print('    %-14s 이상군 %2d일  →  %s'
              % (label, ab, '기준 충족 (일 단위 가능)' if ab >= 15 else '**미달 — 연 단위로 후퇴**'))

    for label, _ in C_RULES:
        lost = out[label][5]
        if lost:
            print('\n  [%s] 판정 자체가 불가능해지는 날 %d일' % (label, len(lost)))
            print('     %s ~ %s' % (lost[0], lost[-1]))

    print('\n견본 3종의 연도별 기여일수 (수온 일평균 기준)')
    for label, D in (('견본 A', dt.date(2021, 7, 31)), ('견본 B', dt.date(2021, 8, 5)),
                     ('견본 C', dt.date(2021, 8, 11))):
        parts = []
        for y in clim_years(D.year):
            n = year_contrib(mean_series, y, D)
            parts.append('%d:%2d' % (y, n))
        print('  %s %s   %s' % (label, D, ' · '.join(parts)))


# ── 7. 근거 파일 생성 (§8) — 견본 A·B·C ──────────────────────────
#
# 확정된 결정을 전부 적용한다.
#   §16 ⑧   일평균·결측률은 H1 정시(만점 24). 일 최고만 30분          #1·#2·#3
#   §16 ⑦   A1 창 경계 · C2 「3년 미만」 일 단위                      #26·#40
#   #28·#29·#38  판정 보류일의 일평균은 어떤 계산에도 쓰지 않는다
#   §10     사사오입은 1/10 단위 정수 산술. round() 도 float 도 안 쓴다  #9·#10
#
# 계산되지 않는 것은 손대지 않는다 — 조석(conditions)·stage_label·설명문·면책.

STAGE_LABEL = {'normal': '특보 기준 미만', 'preliminary': '예비특보 기준 도달',
               'advisory': '주의보 기준 도달', 'warning': '경보 기준 도달',
               'withheld': '판정 보류'}

# ── §12 일정 ③ 스키마 확정 (2026-08-03) ──────────────────────────
#
# schema_version 2.0. 기준 — 필드가 늘기만 하면 minor, 기존 필드의 뜻·값 범위가
# 바뀌면 major. obs_count 만점이 48 → 24 로 바뀌어 48 을 가정한 소비자가 조용히
# 틀리므로 major 다. climatology.sample_size 정의(#38)와 adopted:null 의 실제
# 사용도 같은 성격이다.
SCHEMA_VERSION = '2.0'

# stage 가 withheld 인 것은 수온을 못 믿는 경우뿐이다 (결정 1 「가」).
#   평년 3년 미만 · ASOS 미산출은 stage 를 정상값으로 두고
#   해당 값만 null, 그룹은 adopted:null 로 표현한다.
#   stage 는 일평균의 절대값(25/28℃)으로 정해지므로 평년이 없어도 낼 수 있다.
WITHHELD_REASON = {
    'sst_missing': '결측률이 20%를 넘음',
    'sst_absent': '그날 관측 행이 아예 없음',
    # station_not_started 는 **근거 파일에서 나타나지 않는다.**
    # §3 이 2017~2019 는 근거 파일을 만들지 않는다고 했고 2020 년 이후는 전부
    # 개시 후다. §13 보류율 집계(2017~2021)에서만 쓴다 — 31 일 중 29 일이 여기다.
    'station_not_started': '관측 개시 전 (§13 집계 전용)',
}

# factors[].quality — §8:870 이 ok·partial 이라 적어 두고 정의하지 않은 자리
QUALITY = {
    'ok': '값과 백분위를 둘 다 냈다',
    'partial': '값은 냈고 백분위를 못 냈다 (평년 표본이 없음)',
    # None → 값도 못 냈다. adopted:null 과 함께 온다
}

# 예비특보 25℃ 는 2024년 6월 이후 기준이다. 그 이전은 normal (§8)
PRELIM_FROM = dt.date(2024, 6, 1)


def frac(x):
    """float/str → Fraction. 십진 표기를 그대로 옮긴다 (2진 오차를 들이지 않는다)"""
    from decimal import Decimal
    return Fraction(Decimal(str(x)))


def round_half_up(x, nd):
    """사사오입. 절댓값 기준으로 반올림한다 (§10, assets/format.js round1 과 같은 정의).

    파이썬 round() 는 은행가 반올림이라 26.25 → 26.2 가 된다. 쓰지 않는다.
    """
    if x is None:
        return None
    sign = -1 if x < 0 else 1
    a = abs(Fraction(x)) * (10 ** nd)
    return sign * Fraction((2 * a + 1) // 2, 10 ** nd)


def num(x, nd):
    """JSON 에 넣을 수 (사사오입 뒤 float). None 은 그대로 None"""
    return None if x is None else float(round_half_up(x, nd))


def exact_h1(pairs):
    """H1 정시 일평균 — 1/10 단위 정수에서 정확히 계산한다"""
    q = to_hourly(pairs, 'H1')
    if not q:
        return None, 0
    t = [Fraction(round(v * 10), 10) for _, v in q]
    return sum(t) / len(t), len(t)


def evidence(D, sst, solar, tmax):
    """대상일 D 의 근거 파일 계산 필드. 값은 Fraction 이다."""
    pairs = sst.get(D)
    if pairs is None:
        return None
    mean, n_obs = exact_h1(pairs)
    missing = Fraction(1) - Fraction(n_obs, OBS_PER_DAY_H)
    withheld = missing > Fraction(MISSING_MAX).limit_denominator(100)
    d30 = [v for _, v in pairs]
    out = {'observed_at': D, 'obs_count': n_obs, 'missing': missing,
           'daily_max': frac(max(d30)), 'withheld': withheld}

    # 평년값 — 판정 보류일을 뺀 H1 일평균으로 만든다 (#38)
    means = {}
    for d, p in sst.items():
        m, k = exact_h1(p)
        if m is not None and Fraction(1) - Fraction(k, OBS_PER_DAY_H) <= Fraction(1, 5):
            means[d] = m
    ys = clim_years_daily(means, D, C_NEED)
    smp = [means[dt.date(y, D.month, D.day) + dt.timedelta(days=k)]
           for y in ys for k in range(-CLIM_HALF, CLIM_HALF + 1)
           if dt.date(y, D.month, D.day) + dt.timedelta(days=k) in means]
    out['clim_years'] = len(ys)
    out['clim_n'] = len(smp)
    out['clim'] = (sum(smp) / len(smp)) if smp else None

    if withheld:
        # 겹칠 때는 수온이 먼저다 — 수온이 없으면 평년을 따질 것도 없다 (결정 3).
        # 평년이 모자랐다는 사실은 climatology.years 로 드러난다.
        out.update(stage='withheld', mean=None, anomaly=None, days_over=0,
                   groups=None,
                   reason='sst_absent' if n_obs == 0 else 'sst_missing')
        return out
    out['reason'] = None

    out['mean'] = mean
    out['anomaly'] = (mean - out['clim']) if out['clim'] is not None else None

    # 28℃ 이상 연속 일수 — 일평균 기준, 보류일에서 끊긴다 (§8)
    n_over = 0
    d = D
    while d in means and means[d] >= 28:
        n_over += 1
        d -= dt.timedelta(days=1)
    out['days_over'] = n_over
    if mean >= 28:
        out['stage'] = 'warning' if n_over >= 3 else 'advisory'
    elif mean >= 25 and D >= PRELIM_FROM:
        out['stage'] = 'preliminary'
    else:
        out['stage'] = 'normal'

    # 열유입 — ASOS 7일 평균, 창 D−7~D−1 (§7)
    facs = {}
    for fid, series in (('solar', solar), ('airtemp', tmax)):
        vals = [series.get(D - dt.timedelta(days=i + 1)) for i in range(FACTOR_DAYS)]
        if any(v is None for v in vals):
            facs[fid] = None
            continue
        v = sum(frac(x) for x in vals) / FACTOR_DAYS
        s = []
        for y in ys:
            base = dt.date(y, D.month, D.day)
            for k in range(-CLIM_HALF, CLIM_HALF + 1):
                w = [series.get(base + dt.timedelta(days=k - i - 1))
                     for i in range(FACTOR_DAYS)]
                if all(x is not None for x in w):
                    s.append(sum(frac(x) for x in w) / FACTOR_DAYS)
        facs[fid] = {'value': v, 'n': len(s),
                     'pct': (Fraction(sum(1 for x in s if x < v), len(s)) * 100)
                            if s else None}

    # 이전부터 높았던 수온 — 30일 누적편차, 창 D−29~D (§7). #28 보간 금지
    def clim_day(d):
        s = [means[dt.date(y, d.month, d.day) + dt.timedelta(days=k)]
             for y in ys for k in range(-CLIM_HALF, CLIM_HALF + 1)
             if dt.date(y, d.month, d.day) + dt.timedelta(days=k) in means]
        return (sum(s) / len(s)) if s else None

    def cum(Dx):
        tot = Fraction(0)
        for i in range(CUM_DAYS):
            d = Dx - dt.timedelta(days=i)
            v, c = means.get(d), clim_day(d)
            if v is None or c is None:
                return None
            tot += v - c
        return tot

    cv = cum(D)
    if cv is None:
        facs['cum_anomaly'] = None
    else:
        s = [c for y in ys for k in range(-CLIM_HALF, CLIM_HALF + 1)
             for c in [cum(dt.date(y, D.month, D.day) + dt.timedelta(days=k))]
             if c is not None]
        facs['cum_anomaly'] = {'value': cv, 'n': len(s),
                               'pct': (Fraction(sum(1 for x in s if x < cv), len(s)) * 100)
                                      if s else None}
    out['groups'] = facs
    return out


NONE_EXCEEDED = '평년을 크게 벗어난 요인이 없습니다.'
NOT_ENOUGH = '요인을 판정할 자료가 부족합니다.'


def factors_summary(doc):
    """요인 영역 머리의 요약 문구 — assets/station.js renderFactors 와 같은 규칙 (#69)

    요약 문구는 「봤다」가 전제다. `없습니다` 는 **전부 adopted:false 일 때만** 낸다.
    false 는 「봤는데 못 미쳤다」라 참이고, null 이 섞이면 거짓이다.
    섞였을 때는 요약하지 않는다 — 한 문장으로 요약하면 반드시 과장이거나 축소다.
    """
    gs = doc.get('groups') or []
    if not gs:
        return None
    if any(g.get('adopted') is True for g in gs):
        return None
    unknown = [g for g in gs if g.get('adopted') is None]
    if not unknown:
        return NONE_EXCEEDED
    if len(unknown) == len(gs):
        return NOT_ENOUGH
    return None


def check_schema(doc):
    """§8 스키마 불변식 — ③ 에서 확정한 규칙을 강제한다. 어긋난 것들의 목록을 낸다."""
    bad = []
    st, dq = doc.get('status', {}), doc.get('data_quality', {})

    def want(cond, msg):
        if not cond:
            bad.append(msg)

    want(doc.get('schema_version') == SCHEMA_VERSION,
         'schema_version 이 %s 가 아니다: %r' % (SCHEMA_VERSION, doc.get('schema_version')))

    # 결정 5 — judgment_withheld 는 stage=='withheld' 의 파생값이다
    wh = st.get('stage') == 'withheld'
    want(dq.get('judgment_withheld') is wh,
         'judgment_withheld(%r) 가 stage(%r) 와 어긋난다'
         % (dq.get('judgment_withheld'), st.get('stage')))

    # 결정 2 — withheld_reason 은 보류일에만, 그리고 enum 안에서
    r = dq.get('withheld_reason')
    want((r is not None) == wh,
         'withheld_reason(%r) 은 보류일에만 있어야 한다 (stage=%r)' % (r, st.get('stage')))
    want(r is None or r in WITHHELD_REASON, 'withheld_reason 이 enum 밖이다: %r' % r)
    want(r != 'station_not_started',
         'station_not_started 는 근거 파일에 나타나지 않는다 (§13 집계 전용)')

    # 결정 1 — 보류일 규약은 수온 사유일 때만 적용된다 (§8 「보류일에 담는 것」)
    if wh:
        for k in ('current_sst', 'current_sst_raw', 'climatology_mean',
                  'climatology_mean_raw', 'anomaly', 'anomaly_raw'):
            want(st.get(k) is None, '보류일인데 %s 가 비어 있지 않다: %r' % (k, st.get(k)))
        want(doc.get('groups') == [], '보류일인데 groups 가 [] 가 아니다')

    # 결정 7 — 실시간이면 daily_max_sst 는 없다.
    # 「최근 24시간 최고값」은 일 최고수온이 아니라 다른 물건이고,
    # daily_max_sst 는 30분(만점 48) 기준으로 남겨 두었다 (CHANGES #3).
    if st.get('sst_basis') == 'rolling_24h':
        want(st.get('daily_max_sst') is None and st.get('daily_max_sst_raw') is None,
             'rolling_24h 인데 daily_max_sst 가 있다: %r' % st.get('daily_max_sst'))

    # 결정 4 — quality enum, 그리고 adopted:null 과의 관계
    for g in doc.get('groups', []):
        unknown = g.get('adopted') is None
        want(not unknown or g.get('representative_percentile') is None,
             '%s: adopted 가 null 인데 representative_percentile 이 있다' % g.get('id'))
        for f in g.get('factors', []):
            q = f.get('quality')
            want(q is None or q in QUALITY, '%s: quality 가 enum 밖이다: %r' % (f.get('id'), q))
            if q == 'ok':
                want(f.get('value_raw') is not None and f.get('percentile') is not None,
                     '%s: quality=ok 인데 값이나 백분위가 없다' % f.get('id'))
            elif q == 'partial':
                want(f.get('value_raw') is not None and f.get('percentile') is None,
                     '%s: quality=partial 은 값만 있고 백분위가 없어야 한다' % f.get('id'))
            else:
                want(f.get('value_raw') is None and f.get('percentile') is None,
                     '%s: quality 가 null 인데 값이 있다' % f.get('id'))
            if f.get('percentile') is None:
                want(unknown, '%s: 백분위가 없는데 그룹이 adopted:null 이 아니다' % f.get('id'))

    # #69 — adopted:null 이 하나라도 있으면 「없습니다」 요약을 낼 수 없다.
    # 보지도 않고 평범했다고 말하는 것이며 §8:770 이 금지한 동작이다.
    if any(g.get('adopted') is None for g in doc.get('groups') or []):
        want(factors_summary(doc) != NONE_EXCEEDED,
             'adopted:null 이 있는데 요약이 「%s」다' % NONE_EXCEEDED)
    return bad


SAMPLES = (('견본 A', 'data/fsch6.json', dt.date(2021, 7, 31)),
           ('견본 B', 'data/sample-b.json', dt.date(2021, 8, 5)),
           ('견본 C', 'data/sample-c.json', dt.date(2021, 8, 11)))


def apply_evidence(doc, e):
    """계산된 값을 근거 파일에 넣는다. 계산되지 않는 필드는 손대지 않는다."""
    st, dq = doc['status'], doc['data_quality']
    st['observed_at'] = e['observed_at'].isoformat()
    st['daily_max_sst'] = num(e['daily_max'], 2)
    st['daily_max_sst_raw'] = num(e['daily_max'], 4)
    st['stage'] = e['stage']
    st['stage_label'] = STAGE_LABEL[e['stage']]
    st['days_over_advisory'] = e['days_over']
    for key, val in (('current_sst', e['mean']), ('climatology_mean', e['clim']),
                     ('anomaly', e['anomaly'])):
        st[key] = num(val, 2) if not e['withheld'] else None
        st[key + '_raw'] = num(val, 4) if not e['withheld'] else None
    doc['schema_version'] = SCHEMA_VERSION
    dq['obs_count'] = e['obs_count']
    dq['sst_missing_rate'] = num(e['missing'], 3)
    # judgment_withheld 는 stage == 'withheld' 의 파생값이다 (결정 5).
    # 둘이 어긋나면 check_schema 가 잡는다.
    dq['judgment_withheld'] = (e['stage'] == 'withheld')
    dq['withheld_reason'] = e['reason']
    doc['climatology']['years'] = e['clim_years']
    doc['climatology']['sample_size'] = e['clim_n']

    if e['withheld']:
        doc['groups'] = []
        return doc

    unit = {'solar': 'MJ/m²', 'airtemp': '℃', 'cum_anomaly': '℃·일'}
    for g in doc['groups']:
        pcts = []
        for f in g['factors']:
            c = e['groups'].get(f['id'])
            f['unit'] = unit[f['id']]
            f['as_of'] = (e['observed_at'] if f['id'] == 'cum_anomaly'
                          else e['observed_at'] - dt.timedelta(days=1)).isoformat()
            if c is None:
                f.update(value=None, value_raw=None, percentile=None,
                         clim_sample_size=None, quality=None, as_of=None)
                pcts.append(None)
                continue
            f.update(value=num(c['value'], 2), value_raw=num(c['value'], 4),
                     percentile=num(c['pct'], 1), clim_sample_size=c['n'],
                     quality='ok' if c['pct'] is not None else 'partial')
            pcts.append(round_half_up(c['pct'], 1) if c['pct'] is not None else None)
        if any(p is None for p in pcts):
            g['adopted'] = None
            g['representative_percentile'] = None
        else:
            rep = max(pcts)
            g['adopted'] = rep >= THRESHOLD
            g['representative_percentile'] = float(rep)
    return doc


def run_evidence(solar, tmax, sst, write=False):
    import json
    print('═' * 74)
    print('§8 근거 파일 — 확정 규칙으로 %s' % ('재생성' if write else '검증'))
    print('═' * 74)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ok = True
    for label, rel, D in SAMPLES:
        path = os.path.join(root, rel)
        e = evidence(D, sst, solar, tmax)
        doc = json.load(open(path, encoding='utf-8'))
        want = apply_evidence(json.loads(json.dumps(doc)), e)
        print('\n%s  %s  (%s)' % (label, D, rel))
        st, dq = want['status'], want['data_quality']
        print('   관측 %s/24 · 결측률 %s · stage %s · 연속 %s일'
              % (dq['obs_count'], dq['sst_missing_rate'], st['stage'],
                 st['days_over_advisory']))
        print('   일평균 %s (%s) · 평년 %s (%s) · 평년대비 %s (%s) · 일최고 %s'
              % (st['current_sst'], st['current_sst_raw'],
                 st['climatology_mean'], st['climatology_mean_raw'],
                 st['anomaly'], st['anomaly_raw'], st['daily_max_sst']))
        print('   평년 %d년 · 표본 %d일' % (want['climatology']['years'],
                                        want['climatology']['sample_size']))
        for g in want['groups']:
            print('   %-10s adopted=%-5s rep=%s' % (g['id'], g['adopted'],
                                                    g['representative_percentile']))
            for f in g['factors']:
                print('      %-12s %-9s %-6s 표본 %-5s as_of %s'
                      % (f['id'], f['value_raw'], f['percentile'],
                         f['clim_sample_size'], f['as_of']))
        bad = check_schema(want)
        print('   스키마 검사 %s' % ('통과' if not bad else '**실패**'))
        for m in bad:
            print('      · ' + m)
        ok = ok and not bad
        if write:
            want['generated_at'] = GENERATED_AT
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(want, fh, ensure_ascii=False, indent=2)
                fh.write('\n')
            print('   → 기록함')
        else:
            cur = json.loads(json.dumps(doc))
            cur.pop('generated_at', None)
            chk = json.loads(json.dumps(want))
            chk.pop('generated_at', None)
            same = json.dumps(cur, sort_keys=True) == json.dumps(chk, sort_keys=True)
            print('   파일과 %s' % ('일치' if same else '**불일치**'))
            ok = ok and same
    if not write:
        print('\n%s' % ('세 견본 모두 코드가 재현한다.' if ok
                        else '**불일치가 있다. `verify.py build` 로 재생성하라.**'))
    return ok


GENERATED_AT = '2026-08-03T18:00:00+09:00'


# ── 8. 평년 분포 ──────────────────────────────────────────────────

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
    if what in ('all', 'rates', 'hourly', 'edge', 'bg', 'bc', 'evidence', 'build'):
        print('창리 수온 읽는 중 (zip 여러 개, 시간이 걸립니다)…')
        sst = read_sst(range(2016, 2022))
        print('  %d일\n' % len(sst))
        if what in ('all', 'hourly'):
            run_hourly(sst); print()
        if what in ('all', 'edge'):
            run_edge(solar, tmax, sst); print()
        if what in ('all', 'bg'):
            run_bg(solar, tmax, sst); print()
        if what in ('all', 'bc'):
            run_bc(solar, tmax, sst); print()
        if what in ('all', 'evidence', 'build'):
            run_evidence(solar, tmax, sst, write=(what == 'build')); print()
        if what in ('all', 'rates'):
            run_rates(solar, tmax, sst)


if __name__ == '__main__':
    main()
