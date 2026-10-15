# Postgres + pgvector 이미지

운영·CI·개발이 쓰는 `postgres:18-alpine` 에 벡터 확장 pgvector 를 컴파일해 얹은 이미지다.
`.github/workflows/postgres-image.yml` 이 빌드해 `ghcr.io/03hoho03/postgres-pgvector` 에 올린다
(main 병합·수동 실행 때. PR 에서는 빌드와 스모크만).

## 왜 alpine 위에서 컴파일하나

공식 `pgvector/pgvector` 이미지는 Debian(glibc) 기반이다. 같은 `en_US.utf8` 로캘이라도 glibc 와
musl 은 문자열 정렬 순서가 다르다. musl 은 바이트 순서로 비교해서 `SELECT 'a' < 'B'` 가 거짓이고,
glibc 는 참이다. 운영 DB 는 alpine(musl)에서 만들어졌으므로 glibc 이미지로 갈아타면 텍스트 칸의
B-tree 인덱스 순서가 서버의 비교 결과와 어긋나고, 모든 텍스트 인덱스를 재색인해야 한다.
그래서 베이스는 그대로 두고 확장만 소스에서 빌드한다. `smoke.sh` 가 이 정렬 결과(`f|f`)와
`datcollate` 를 매번 단언한다.

공식 postgres 이미지는 서버를 소스에서 빌드해 헤더와 PGXS 를 이미 갖고 있으므로 빌드에 필요한 것은
`make`·`gcc`·`musl-dev` 뿐이고, 빌드가 끝나면 지운다. `postgresql18-dev` 같은 apk 패키지는 이미지
안의 서버와 다른 빌드라 쓰지 않는다.

## 왜 digest 로 고정하나

- 베이스(`FROM`)는 운영에서 돌고 있는 이미지와 같은 다중 아키텍처 인덱스 digest 로 고정한다.
  `18-alpine` 태그는 Alpine·PostgreSQL 마이너 갱신 때마다 다른 이미지를 가리킨다.
- pgvector 는 태그 소스 tarball 을 받아 sha256 을 검증한다. 버전을 올릴 때는
  `PGVECTOR_VERSION` 과 `PGVECTOR_SHA256` 을 같이 바꾼다.
- 이 이미지를 쓰는 쪽도 태그가 아니라 워크플로 요약에 남는 매니페스트 digest
  (`ghcr.io/03hoho03/postgres-pgvector@sha256:…`)로 고정한다. 태그는 같은 버전으로 다시 빌드하면 밀린다.

## 운영 이미지 교체는 별도 절차다

이 디렉터리를 고쳐 병합해도 이미지가 레지스트리에 올라갈 뿐, 운영·CI·개발 DB 는 바뀌지 않는다
(`infra/` 는 배포 워크플로의 트리거 경로 밖이다). 운영 DB 컨테이너의 이미지를 바꾸는 일은 compose 를
고치는 별도 변경과 그에 맞는 교체·되돌리기 절차로 한다.

## 로컬 확인

```sh
docker build -t pgvector-local infra/postgres
infra/postgres/smoke.sh pgvector-local                 # 확장·halfvec 거리·정렬 규칙
infra/postgres/smoke.sh --expect-no-vector \
  postgres:18-alpine@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2  # 대조군
```
