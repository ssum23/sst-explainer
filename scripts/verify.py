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
"""

import csv, io, os, sys, zipfile, datetime as dt
from collections import defaultdict

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
    """창리 30분 표층수온 → {날짜: [값…]}  (중첩 zip 을 메모리에서 푼다)"""
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
                        out[dt.date.fromisoformat(r[1][:10])].append(float(r[2]))
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
    for d, vals in sst_raw.items():
        out[d] = {'mean': sum(vals) / len(vals), 'max': max(vals),
                  'n': len(vals), 'missing': 1 - len(vals) / OBS_PER_DAY}
    return out


def run_rates(solar, tmax, sst):
    print('═' * 70)
    print('§13 채택률 — 개발용 구간 2020~2021')
    print('═' * 70)
    daily = daily_sst(sst)
    mean_series = {d: v['mean'] for d, v in daily.items()}
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
        print('  %-24s %6s | %6s %8s | %6s %8s' %
              ('구분', '일수', '열유입', '비율', '전체', '비율'))
        rate = {}
        for name, g in groups:
            h = sum(1 for r in g if r['heat_ok'])
            a = sum(1 for r in g if r['adopted'])
            rh = (h / len(g) * 100) if g else 0
            ra = (a / len(g) * 100) if g else 0
            rate[name[:3]] = rh          # 실패 기준은 문서 정의(열유입)로 본다
            print('  %-24s %6d | %6d %7.1f%% | %6d %7.1f%%' % (name, len(g), h, rh, a, ra))
        print('  * 열유입 = §13 의 35/29/6 을 재현하는 정의. 전체 = 배경장까지 포함')
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


# ── 3. 평년 분포 ──────────────────────────────────────────────────

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
    if what in ('all', 'rates'):
        print('창리 수온 읽는 중 (zip 여러 개, 시간이 걸립니다)…')
        sst = read_sst(range(2016, 2022))
        print('  %d일\n' % len(sst))
        run_rates(solar, tmax, sst)


if __name__ == '__main__':
    main()
