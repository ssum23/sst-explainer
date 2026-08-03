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
import urllib.error
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


def verdict(msg):
    """성공/실패를 **한 줄로** 가른다.

    조용한 실패는 종료코드로 구분되지 않는다 — 어느 쪽이든 0 이다.
    §12 가 「3회 연속 실패하면 이슈를 연다」고 적어 둔 자리인데 아직 없으므로,
    최소한 **로그 한 줄과 실행 요약**으로는 구분되게 한다.

    GITHUB_STEP_SUMMARY 에도 같은 줄을 쓴다 — 그러면 Actions 실행 화면에서
    로그를 열지 않고도 보인다. 초록 체크만으로 성공을 믿지 않게.
    """
    line = '결과: ' + msg
    print(line, flush=True)
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        try:
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write('- `collect.py` **%s**\n' % msg)
        except OSError:
            pass
    return 0


def fetch(key):
    """(응답 바이트, 사유). 성공하면 사유는 None.

    사유를 **문자열로 돌려준다** — 로그에만 찍고 「위 줄이 사유다」라고 하면
    실행 요약에서 무엇이 잘못됐는지 알 수 없다. 2026-08-03 에 실제로 그랬다.
    """
    url = '%s?%s' % (URL, urllib.parse.urlencode({'id': 'risaList', 'key': key}))
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                return None, 'HTTP %s' % r.status
            return r.read(), None
    except urllib.error.HTTPError as e:
        # 메시지에 URL(=키)이 들어가므로 상태코드만 쓴다
        return None, 'HTTPError %s' % e.code
    except Exception as e:
        return None, '호출 실패 (%s)' % type(e).__name__


def decode(raw):
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, None


def rows_of(raw):
    """(창리 행 목록, 사유). 성공하면 사유는 None"""
    text, enc = decode(raw)
    if text is None:
        return [], '디코드 실패 (%d바이트)' % len(raw)
    if enc != 'utf-8':
        log('주의: 응답이 %s 로 왔다. 실측(2026-08-03)은 UTF-8 이었다' % enc)
    try:
        doc = json.loads(text)
    except ValueError:
        head = text[:60].replace('\n', ' ')
        return [], 'JSON 파싱 실패 (%d바이트, 앞부분 %r)' % (len(raw), head)
    header = doc.get('header') or {}
    code = header.get('resultCode')
    if code != '00':
        return [], 'resultCode=%r resultMsg=%r' % (code, header.get('resultMsg'))
    items = (doc.get('body') or {}).get('item') or []
    got = [x for x in items if x.get('sta_cde') == STATION]
    if not got:
        return [], '전국 %d행을 받았으나 %s 가 없다' % (len(items), STATION)
    return got, None


def main():
    key = (os.environ.get('NIFS_KEY') or '').strip()
    if not key:
        return verdict('건너뜀 — NIFS_KEY 가 비어 있다 '
                       '(저장소 Secrets 에 NIFS_KEY 가 있는지 · 이름 오타가 없는지 확인)')

    raw, why = fetch(key)
    if raw is None:
        return verdict('건너뜀 — %s. 이전 파일을 그대로 둔다' % why)
    got, why = rows_of(raw)
    if not got:
        return verdict('건너뜀 — %s. 이전 파일을 그대로 둔다' % why)

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
    return verdict('쌓음 %d줄 — 관측 %s %s · 받은 시각 %s → %s'
                   % (len(lines), obs.get('obs_dat'), obs.get('obs_tim'),
                      stamp, os.path.basename(path)))


if __name__ == '__main__':
    sys.exit(main())
