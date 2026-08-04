#!/bin/sh
# launchd 가 부른다 — .env 를 읽어 collect.py 에 넘긴다.
#
# GitHub Actions 의 schedule 을 믿을 수 없어 옮겨 왔다 (2026-08-04).
# 16시간 동안 16회 돌았어야 하는데 2회만 돌았고, 그 2회도 아무것도 쌓지 않았다.
#
# git 을 건드리지 않는다. 파일만 쌓고, 커밋은 사람이 하는 일에 묻어간다.
# 자동 커밋을 넣으면 PRD 를 고치는 중에 끼어들어 반쯤 고쳐진 상태를 커밋할 수 있다.
cd "$(dirname "$0")/.." || exit 0
[ -f .env ] || exit 0
set -a
. ./.env
set +a
exec python3 scripts/collect.py
