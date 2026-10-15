# 운영·CI·개발이 쓰는 postgres:18-alpine 과 바이트로 같은 베이스 위에 pgvector 를 컴파일해 얹는다.
# 공식 pgvector 이미지(Debian·glibc)로 바꾸지 않는 이유는 README.md 의 "왜 alpine 위에서 컴파일하나" 절.
#
# 베이스는 다중 아키텍처 인덱스 digest 로 고정한다 — 태그만 쓰면 Alpine·PostgreSQL 마이너가
# 조용히 바뀌어 운영 데이터 디렉터리와 어긋날 수 있다.
FROM postgres:18-alpine@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2

ARG PGVECTOR_VERSION=0.8.7
# GitHub 태그 소스 tarball(archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz)의 sha256.
# 버전을 올릴 때 같이 바꾼다.
ARG PGVECTOR_SHA256=cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85

# 공식 이미지는 PostgreSQL 을 소스에서 빌드해 서버 헤더(/usr/local/include/postgresql/server)와
# PGXS 를 이미 갖고 있다. 그래서 postgresql18-dev 같은 apk 패키지는 받지 않는다 — 받으면 이미지의
# 서버와 다른 빌드의 헤더가 섞인다. 필요한 것은 컴파일러와 make 뿐이다.
# with_llvm=no: JIT 비트코드를 만들지 않는다(이미지에 clang·llvm 이 없다).
# OPTFLAGS="": 빌드 머신 CPU 에 맞춘 -march=native 를 끄고 같은 아키텍처의 어느 CPU 에서도 돌게 한다.
# 설치 패키지 목록을 빌드 전후로 떠서 다르면 실패시킨다: 빌드 도구(예 musl-dev)가 의존성으로
# 런타임 패키지(예 musl)를 조용히 올리면 apk del 뒤에도 올라간 버전이 남아 베이스와 바이트로
# 같다는 전제가 깨진다. 비교용 파일은 같은 RUN 안에서 지워 레이어에 남기지 않는다.
RUN set -eux; \
    apk info -v | sort > /tmp/apk-before.txt; \
    apk add --no-cache --virtual .pgvector-build-deps make gcc musl-dev; \
    cd /tmp; \
    wget -O pgvector.tar.gz "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz"; \
    echo "${PGVECTOR_SHA256}  pgvector.tar.gz" | sha256sum -c -; \
    tar xzf pgvector.tar.gz; \
    cd "pgvector-${PGVECTOR_VERSION}"; \
    make with_llvm=no OPTFLAGS=""; \
    make with_llvm=no install; \
    cd /; \
    rm -rf /tmp/pgvector.tar.gz "/tmp/pgvector-${PGVECTOR_VERSION}"; \
    apk del --no-network .pgvector-build-deps; \
    apk info -v | sort > /tmp/apk-after.txt; \
    diff -u /tmp/apk-before.txt /tmp/apk-after.txt; \
    rm -f /tmp/apk-before.txt /tmp/apk-after.txt; \
    test -f /usr/local/share/postgresql/extension/vector.control
