#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect.py — 실시간 수온을 받아서 쌓기만 한다

충남 서해 연안 고수온 설명 서비스 · §12 갱신 파이프라인

이 파일이 존재하는 이유
  `risaList` 는 **최신 스냅숏 한 번**만 준다. 기간 조회가 없다
  (`data/api/2026-08-03_API확인.md` §4 ③). 그래서 실시간 값은 **우리가 쌓아야만**
  존재하게 되고, 오늘 안 받으면 오늘 것은 영영 없다.
  과거 zip 은 나중에 받을 수 있지만 실시간은 그렇지 않다.

무엇을 하지 않는가 — 여기가 중요하다
  계산하지 않는다. H1(정시) 선별도, 일평균도, 결측률도, evidence.json 도 만들지 않는다.
  §16 ⑧ 이 H1 로 확정했지만 **GitHub Actions cron 은 5~20분 늦는 일이 흔하다.**
  지금 `:00` 만 골라 버리면 그 시간대를 영영 잃는다. 받은 것을 그대로 쌓고
  고르는 일은 계산할 때 한다.

  중층(obs_lay=2)도 버리지 않는다. 활용가이드에 없는 `rpr_yn` 도 그대로 쌓는다.
  **원본 그대로가 원칙이다** — 문서에 없는 필드가 와도 버리지 않는다.

실패하면 조용히 넘어간다 (§12)
  호출 실패 · 파싱 실패 · resultCode 이상 · 창리 행 없음 — 어느 경우든
  **이전 파일을 그대로 두고 exit 0** 이다. 빨간 X 를 띄우지 않는다.

키를 로그에 흘리지 않는다
  URL 에 키가 들어가므로 curl 을 쓰지 않는다(`set -x` 사고 방지).
  예외도 메시지 대신 **종류만** 찍는다 — HTTPError 는 메시지에 URL 을 담는다.

쌓는 곳
  data/realtime/fsch6-YYYY-MM.ndjson   한 줄이 관측 하나. 월별로 나눈다

인코딩 (2026-08-03 실측)
  JSON 엔드포인트(`/api/OpenAPI_json`) 응답은 **UTF-8** 이다.
  ① 기록이 EUC-KR 이라 적었으나 저장된 .raw 3건도 EUC-KR 로는 디코드가 실패한다.
  그래도 utf-8 → euc-kr 순으로 시도한다. 기관이 바꿔도 조용히 살아남게.
"""

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

STATION = 'fsch6'
URL = 'https://www.nifs.go.kr/api/OpenAPI_json'
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'realtime')
KST = dt.timezone(dt.timedelta(hours=9))
TIMEOUT = 30

# 활용가이드가 적은 7개 + 실제 응답에만 있는 rpr_yn = 8개 (2026-08-03 실측)
FIELDS = ('sta_cde', 'sta_nam_kor', 'obs_dat', 'obs_tim',
          'obs_lay', 'wtr_tmp', 'repair_gbn', 'rpr_yn')


def log(msg):
    print(msg, flush=True)


def fetch(key):
    """응답 바이트. 실패하면 None — 사유는 종류만 찍는다 (URL 유출 방지)"""
    url = '%s?%s' % (URL, urllib.parse.urlencode({'id': 'risaList', 'key': key}))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                log('HTTP %s — 파일을 건드리지 않는다' % r.status)
                return None
            return r.read()
    except Exception as e:
        log('호출 실패 (%s) — 파일을 건드리지 않는다' % type(e).__name__)
        return None


def decode(raw):
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, None


def rows_of(raw):
    """응답 → 창리 행 목록. 하나라도 이상하면 빈 목록"""
    if not raw:
        return []
    text, enc = decode(raw)
    if text is None:
        log('디코드 실패 (%d바이트) — 파일을 건드리지 않는다' % len(raw))
        return []
    if enc != 'utf-8':
        log('주의: 응답이 %s 로 왔다. 실측(2026-08-03)은 UTF-8 이었다' % enc)
    try:
        doc = json.loads(text)
    except ValueError:
        log('JSON 파싱 실패 (%d바이트) — 파일을 건드리지 않는다' % len(raw))
        return []
    code = (doc.get('header') or {}).get('resultCode')
    if code != '00':
        log('resultCode=%r — 파일을 건드리지 않는다' % code)
        return []
    items = (doc.get('body') or {}).get('item') or []
    got = [x for x in items if x.get('sta_cde') == STATION]
    if not got:
        log('전국 %d행을 받았으나 %s 가 없다 — 파일을 건드리지 않는다'
            % (len(items), STATION))
    return got


def main():
    key = (os.environ.get('NIFS_KEY') or '').strip()
    if not key:
        log('NIFS_KEY 가 비어 있다 — 아무것도 하지 않는다')
        return 0

    got = rows_of(fetch(key))
    if not got:
        return 0

    now = dt.datetime.now(KST)
    # fetched_at 을 남기는 이유 — CHANGES #20.
    # obs_dat 가 4월에 멈춘 관측점이 섞여 있다. 걸러내지 않고 그대로 쌓되,
    # `fetched_at − (obs_dat + obs_tim)` 으로 노후도를 **나중에** 잴 수 있게 재료만 둔다.
    stamp = now.isoformat(timespec='seconds')
    lines = []
    for r in got:
        rec = {'fetched_at': stamp}
        for f in FIELDS:
            rec[f] = r.get(f)          # 없으면 null. 값 변환도 계산이므로 하지 않는다
        extra = sorted(set(r) - set(FIELDS))
        if extra:                      # 기관이 필드를 늘리면 버리지 않고 함께 쌓는다
            log('새 필드 발견: %s — 그대로 쌓는다' % ', '.join(extra))
            for f in extra:
                rec[f] = r[f]
        lines.append(json.dumps(rec, ensure_ascii=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, 'fsch6-%s.ndjson' % now.strftime('%Y-%m'))
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

    obs = got[0]
    log('%d행 추가 — %s %s (관측 %s %s) → %s'
        % (len(lines), STATION, stamp, obs.get('obs_dat'), obs.get('obs_tim'),
           os.path.basename(path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
