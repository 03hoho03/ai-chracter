#!/bin/sh
# Postgres 이미지 스모크. 워크플로와 로컬이 이 파일 하나를 같이 쓴다.
#
#   infra/postgres/smoke.sh <이미지>                      # pgvector 이미지: 확장·halfvec 거리·정렬 규칙
#   infra/postgres/smoke.sh --expect-no-vector <이미지>   # 원래 alpine: 정렬 규칙은 같고 확장은 없어야 한다
#
# 두 번째 형태는 이 스모크가 확장 유무를 실제로 가려낸다는 것을 보이는 대조군이다 — 원래 이미지에서도
# 통과하는 스모크라면 새 이미지의 통과는 아무것도 증명하지 못한다.
# 컨테이너 이름은 SMOKE_CONTAINER 로 바꿀 수 있다. 끝나면 성공·실패와 관계없이 지운다.
set -eu

expect_no_vector=0
if [ "${1:-}" = "--expect-no-vector" ]; then
  expect_no_vector=1
  shift
fi
image="${1:?사용법: smoke.sh [--expect-no-vector] <이미지>}"
name="${SMOKE_CONTAINER:-pgvector-smoke-$$}"

cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$name" -e POSTGRES_PASSWORD=smoke "$image" >/dev/null

# 엔트리포인트는 initdb 뒤 소켓 전용 임시 서버를 한 번 띄웠다 내리므로, TCP 로 물어야 본 서버를 기다린다.
i=0
until docker exec "$name" pg_isready -q -h 127.0.0.1 -U postgres; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "FAIL: 60초 안에 서버가 뜨지 않았다" >&2
    docker logs "$name" >&2
    exit 1
  fi
  sleep 1
done

psql() { docker exec -i "$name" psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -XAtq "$@"; }

expect() {
  label="$1"; want="$2"; got="$3"
  if [ "$got" != "$want" ]; then
    echo "FAIL: $label — 기대 '$want', 실제 '$got'" >&2
    exit 1
  fi
  echo "ok: $label = $got"
}

echo "server: $(psql -c 'SHOW server_version')"

# 정렬 규칙. musl 의 strcoll 은 바이트 순서라 대문자(0x42)가 소문자(0x61·0x62)보다 앞선다.
# glibc 이미지라면 'a' < 'B' 가 참이 되고, 그러면 운영 텍스트 인덱스를 전부 재색인해야 한다.
expect "'a' < 'B', 'b' < 'B'" "f|f" "$(psql -c "SELECT 'a' < 'B', 'b' < 'B'")"
expect "datcollate|datctype|datlocprovider" "en_US.utf8|en_US.utf8|c" \
  "$(psql -c "SELECT datcollate, datctype, datlocprovider FROM pg_database WHERE datname = 'postgres'")"

if [ "$expect_no_vector" -eq 1 ]; then
  if out=$(psql -c 'CREATE EXTENSION vector' 2>&1); then
    echo "FAIL: 이 이미지에서 CREATE EXTENSION vector 가 성공했다 — 대조군이 아니다" >&2
    exit 1
  fi
  case "$out" in
    *'extension "vector" is not available'*) ;;
    *) echo "FAIL: 확장이 없어서가 아닌 다른 이유로 실패했다: $out" >&2; exit 1 ;;
  esac
  echo "ok: CREATE EXTENSION vector 실패(기대대로) — $(printf '%s' "$out" | head -n 1)"
  echo "PASS (확장 없음 대조군): $image"
  exit 0
fi

psql -c 'CREATE EXTENSION vector'
echo "vector extversion: $(psql -c "SELECT extversion FROM pg_extension WHERE extname = 'vector'")"

# halfvec 칸 한 줄과 코사인 거리(<=>). [1,0,0] 과 [0,1,0] 은 직교라 거리 1.
expect "halfvec <=> distance" "1" "$(psql <<'SQL'
CREATE TABLE smoke_items (id int PRIMARY KEY, embedding halfvec(3));
INSERT INTO smoke_items VALUES (1, '[1,0,0]');
SELECT embedding <=> '[0,1,0]'::halfvec FROM smoke_items WHERE id = 1;
SQL
)"

echo "PASS: $image"
