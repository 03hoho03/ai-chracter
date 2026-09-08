# apps/api

FastAPI + SQLAlchemy 2.0(async) + Alembic + Postgres/Redis. `uv`로 관리되는 **독립 파이썬 프로젝트**라 pnpm workspace/turborepo 범위 밖이다 — 품질 체크는 항상 `apps/api` 안에서 따로 돌린다:

```sh
uv run mypy src migrations scripts   # strict. 경로 3개는 .github/workflows/api.yml과 동일하게 유지
uv run pytest --cov --cov-report=term-missing:skip-covered --cov-fail-under=95  # 로컬 Postgres/Redis 필요 (docker compose -f docker-compose.dev.yml up -d)
uv run alembic check                 # 모델과 마이그레이션이 정확히 일치하는지
```

아래는 **모르면 다시 터지는 것**만 담는다. 개별 기능의 구현 서사는 코드와 git 이력에 있다.

## 작업 라우팅 — "무슨 작업 → 무슨 패턴"

| 작업 | 패턴 / 위치 |
|---|---|
| 새 엔드포인트 | 라우터 파일은 URL이 아니라 **도메인 경계**로 정한다(모델 파일이 있는 곳과 다를 수 있다) |
| 요청·응답 스키마 | `core/schema.py`의 `CamelModel` 상속 (snake_case 필드 → camelCase JSON) |
| 인증 필요 라우트 | `Depends(get_current_user_id)`. 비로그인도 허용하면 `get_current_user_id_optional` |
| 마이그레이션 | autogenerate → **손으로 보정**(아래 §마이그레이션) → `alembic check` |
| LLM 호출 | `get_llm_client()` DI. 실패는 전부 `LLMClientError`로 정규화 |
| SSE 스트리밍 | 검증은 `Depends`로 빼고, **제너레이터 본문에서 raise 금지** |
| 응답 후 가벼운 후처리 | `BackgroundTasks` + `Depends(get_session_factory)` |
| 오래 걸리는 백그라운드 잡 | `images/jobs.py`의 `enqueue_generation` + 같은 세션 팩토리 |
| Redis read-modify-write | pipeline + `WATCH`/`MULTI`/`EXEC` (단순 GET-then-SET 금지) |
| 자산 → 렌더링 URL | `generate_presigned_get_url` + `run_in_threadpool` |
| 테스트 클라이언트 | `db_client` / `api_client` 픽스처 (`TestClient` 금지) |
| S3 흉내 | `moto.server.ThreadedMotoServer` (`mock_aws` 금지) |

## 프로젝트 구조 / 툴링

- src-layout: 패키지명은 `api`(`src/api/`), `import api.main` 식. `uv sync`가 editable로 설치한다.
- **`scripts/`는 설치되지 않는다**(src-layout 밖). `pyproject.toml`의 `[tool.mypy] mypy_path`와 `[tool.pytest.ini_options] pythonpath`에 둘 다 `"scripts"`가 있어야 하고, **`scripts/__init__.py`를 만들면 안 된다**(모듈 경로가 `scripts.x`로 바뀌어 mypy/pytest 양쪽이 어긋난다).
- **DB URL의 단일 소스는 `api.core.config.settings.database_url`이다.** `alembic.ini`의 `sqlalchemy.url`은 플레이스홀더이고 `migrations/env.py`가 기동 시 덮어쓴다 — 마이그레이션용 URL을 따로 관리하지 않는다.
- 새 모델은 `db/models/{domain}.py`에 두고 **`db/models/__init__.py`에 import**해야 한다. 빠뜨리면 `Base.metadata`가 비어 autogenerate가 조용히 빈 diff를 낸다.
- **Dockerfile**은 uv 멀티스테이지. `uv:` 이미지 태그를 `[build-system] uv_build` 버전과 맞춰 고정한다(어긋나면 빌드 백엔드 호환성 문제).

## 마이그레이션 (autogenerate가 못 만드는 것들)

**자동생성 결과는 첫 `upgrade head` 실행 전에 손으로 고친다.** 이미 적용한 뒤 `downgrade()`를 고치면 Alembic은 리비전 ID만 추적하므로 실제 실행된 SQL과 어긋나 `UndefinedObjectError`가 난다 — DB를 새로 만들어 처음부터 다시 적용해야 한다.

- **순환 FK**(신규 테이블 둘이 **서로** 참조): `use_alter`는 `create_all()`에서만 지켜지고 `op.create_table`은 무시한다. 인라인 FK를 지우고 두 테이블 생성 뒤 `op.create_foreign_key(...)`로, downgrade엔 drop 전에 `op.drop_constraint(..., type_='foreignkey')`. 단방향 참조(기존 테이블을 가리키기만)는 손댈 필요 없다.
- **ENUM 3종 함정**: (1) `op.drop_table`은 `DROP TYPE`을 안 내보내므로 downgrade 끝에 `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`를 **한 번만** 추가. (2) 기존 테이블에 `op.add_column`으로 enum 컬럼을 추가하면 `CREATE TYPE`이 안 나가므로 upgrade 맨 앞에 `.create(...)`. (3) 기존 타입에 **멤버 추가는 autogenerate가 감지조차 못 한다** — `op.execute("ALTER TYPE x ADD VALUE 'Y'")`를 직접 쓰고(대문자 `.name`), Postgres엔 `DROP VALUE`가 없으니 downgrade는 rename→재생성→`USING col::text::x`→drop.
- 같은 ENUM 이름을 한 리비전의 여러 테이블에 재사용하는 건 안전하다(`CREATE TYPE`은 한 번만 실행된다).
- **부분 인덱스의 `postgresql_where`에 bare 컬럼을 넣지 말 것.** `postgresql_where=published`처럼 `Mapped` 컬럼을 그대로 주면 autogenerate가 생성한 마이그레이션 소스에 `<sqlalchemy.orm.properties.MappedColumn object at 0x...>`라는 **repr을 문자 그대로 박아 넣어, 그 파일을 로드하는 순간 `SyntaxError`**가 난다(실측 재현). `published.is_(True)`처럼 **불리언 식**을 주면 렌더러가 `sa.text('published IS true')`로 정상 변환한다. `legal.py`의 `status == "draft"`가 이미 식이라 이 함정을 피해 갔다 — bool 컬럼일 때만 bare로 쓰고 싶어진다는 게 함정의 핵심이다.
- 시드성 마스터 데이터는 `op.execute("INSERT ...")`로 넣되 PK는 **작성 시점에 하드코딩한 리터럴 UUID**를 쓴다(`uuid4()` 호출 금지 — 환경마다 달라진다).

## 모델 규약

- **`relationship()`을 선언하지 않는다** — 순수 FK 컬럼만 쓰고 INSERT/DELETE 순서를 직접 지킨다. `ON DELETE CASCADE`도 없다.
  - **3단 이상 캐스케이드 삭제는 계층 사이마다 `await db.flush()`를 넣어야 한다.** 안 넣으면 SQLAlchemy가 한 flush 안의 DELETE 순서를 재정렬해 `ForeignKeyViolationError`가 난다.
- **`entity_id` 패턴**: 물리 PK `id`와 별개로 `entity_id`(버전을 넘어 안정적인 참조)를 둔다. 그래서 **버전 복제 시 `entity_id` 참조는 그대로 복사, 물리 FK는 반드시 remap**해야 한다 — 이 구분을 먼저 하고 코드를 짤 것.
- **Postgres ENUM 컬럼은 `.value`(소문자)가 아니라 `.name`(대문자)이 저장된다.** ORM만 쓰면 안 드러나지만 raw SQL에서 소문자를 쓰면 `invalid input value for enum`이다. 반대로 **plain `Text` 컬럼에 `str, Enum` 값을 넣을 때는 `.value`를 명시**한다(`str(member)`는 `"ClassName.MEMBER"`).
- `order`는 Postgres 예약어지만 SQLAlchemy가 항상 따옴표 처리하므로 컬럼명으로 그대로 써도 된다.
- 대상 테이블이 값에 따라 달라지는 **다형 참조**는 FK 없이 `Uuid` 컬럼 + docstring으로 두고, 그 참조를 소비하는 쪽은 `assert`로 500을 내지 말고 404를 낸다(FK가 있는 참조와 섞어 다룰 때 이 구분을 유지할 것).
- `async_session_factory`는 **`expire_on_commit=False`**다 — 커밋 직후 값을 다시 읽으려고 `db.refresh()`를 습관적으로 넣지 말 것.

## API 라우터

- **prefix가 다른 라우트는 같은 도메인 파일 안에 두 번째 `APIRouter`를 만든다**(`me_router` 등). `main.py`에서 import할 때 **이름이 겹치면 반드시 별칭**을 줄 것 — 나중 import가 앞의 것을 덮어써 라우트가 조용히 사라진다.
- **`Depends`는 시그니처 순서대로 순차 resolve된다**(앞의 것이 raise하면 뒤는 호출조차 안 됨). 순서가 중요한 검증은 함수 본문이 아니라 **앞선 `Depends`로** 뽑아낼 것.
- 외부 HTTP 호출(OAuth 토큰교환 등)은 그 호출 자체를 `Depends`로 감싼다 — 그래야 테스트에서 네트워크 없이 오버라이드된다.
- 다중 단어 쿼리 파라미터·예약어는 `Query(alias="contentId")` / `Query(None, alias="from")`. 날짜 범위는 `date`로 받아 `datetime.combine(d, time.min, tzinfo=UTC)`로 명시적 UTC 경계를 만든다(세션 타임존에 의존 금지).
- 구조화된 에러는 별도 스키마를 만들지 않고 `HTTPException(detail=dict)`로 던진다.

## SSE 스트리밍 (폭발 반경이 가장 큰 구역)

- 라우트를 `async def ... -> AsyncIterator[판별유니언]` 제너레이터로 정의하고 `response_class=EventSourceResponse`를 붙이면 FastAPI가 프레임을 만든다. `Depends`로 받은 리소스(DB 세션)는 **스트리밍이 끝날 때까지 살아 있다** — 세션 팩토리를 따로 열지 말 것(테스트 오버라이드를 우회하게 된다).
- **제너레이터 본문에서 `HTTPException`을 raise하면 안 된다.** 이미 스트리밍이 시작된 뒤라 예외 핸들러를 우회하고 커넥션이 깨진다. 소유권·바디 검증은 전부 별도 `Depends` 함수로 뺀다(바디 모델을 그 함수의 파라미터로 다시 선언해도 파싱은 한 번만 된다).
- **본문에서 새로 예외를 던질 수 있는 코드를 추가할 때는 폭발 반경을 먼저 본다.** 예외가 제너레이터를 뚫으면 → 태스크 취소 → 요청 스코프 DB 세션 강제 종료 → **망가진 asyncpg 커넥션이 풀로 반환돼 무관한 다른 요청이 500**이 된다(부하 실측: 커넥션 강제종료 9건 / `InterfaceError` 36건 / 500 응답 8건). 그래서 LLM 판단 블록은 통째로 `try/except LLMClientError`로 감싸 그 턴의 판정만 포기하고 스트림은 정상 종료시킨다. 짝이 되는 방어가 `db/session.py`의 `pool_pre_ping=True`다.
- **LLM 실패는 반드시 `logger.warning` 이상으로 남긴다** — uvicorn은 root logger에 핸들러를 안 붙여 `info`는 사라지고, 429는 화면상 "품질 문제"와 구분되지 않아 로그가 없으면 쿼터 소진이 조용히 진행된다.

## LLM

- SDK는 **`google-genai`**(`from google import genai`)이지 deprecated된 `google-generativeai`가 아니다.
- 서비스 로직은 구체 클래스가 아니라 `dependencies.py`의 `get_llm_client()`를 통해서만 클라이언트를 받는다. 네트워크/타임아웃 실패는 `google.genai.errors.APIError`가 아니라 **`httpx.HTTPError`로 온다** — 두 예외 계열을 함께 잡아야 하고, **`generate`/`generate_structured`가 같은 `except` 튜플을 쓰는 대칭을 유지할 것**(한쪽만 좁으면 위 §SSE의 폭발 반경이 그대로 열린다).
- **API를 거치는 LLM 동작의 모델은 실행 중인 서버 프로세스의 env로 정해진다** — CLI처럼 `GEMINI_MODEL_NAME=… uv run …`으로 우회할 수 없어 쿼터가 마르면 서버를 재기동해야 한다. `LLMClientError`에 별도 핸들러가 없어 **429가 HTTP 500으로 나가므로**, 발행·채팅이 500이면 코드보다 로그의 `RESOURCE_EXHAUSTED`를 먼저 볼 것.
- **Gemini 무료 티어는 모델당 하루 20요청**이고 태평양 자정에 리셋된다(429의 `retryDelay: 30s`는 분당 제한용 상용구라 일일 쿼터엔 무의미). **쿼터는 모델 단위**라 같은 모델에 프로세스를 늘려도 예산이 안 늘고, `GEMINI_MODEL_NAME`을 잔량 있는 모델로 바꾸면 그대로 늘어난다. 스토리 챗 1턴 = 생성 + 스탯판단 **2요청**(+게이트를 넘긴 엔딩 수만큼) — 수동 검증 전에 예산부터 계산할 것.

## 백그라운드 · Redis

- **백그라운드 태스크에서 요청 스코프 `Depends(get_db_session)`을 재사용하면 안 된다.** 라우트가 반환하는 순간 FastAPI가 그 세션을 닫는다 — `Depends(get_session_factory)`를 라우트에서 받아 핸들러에 넘기고 `async with session_factory() as session:`으로 새로 연다.
- "응답 후 가벼운 후처리"는 `asyncio.create_task`가 아니라 `BackgroundTasks`로 충분하다. 단 응답 객체가 필요한 일(쿠키 굽기 등)은 태스크로 넘기지 말 것 — 실행 시점엔 응답이 이미 나갔다.
- **동시 호출 가능성이 있는 Redis read-modify-write는 pipeline + `WATCH`/`MULTI`/`EXEC`(+`WatchError` 재시도)**를 쓴다. `asyncio.gather`로 같은 잡을 갱신하다 갱신 유실이 실측으로 재현됐다. `unwatch()`/`multi()`는 타입 스텁이 없어 `# type: ignore[no-untyped-call]`이 필요하다.
- Redis에 저장하는 상태는 `model_dump_json()`/`model_validate_json()`으로 pydantic 모델을 그대로 왕복시킨다(UUID·datetime을 알아서 처리). 키 프리픽스나 TTL이 다르면 기존 모듈을 파라미터화하지 말고 새 모듈로 분리하는 것이 이 코드베이스의 관례다.

## 테스트 정책 — 무엇을 얼마나 쓰는가

2026-09-08 정리로 870개였던 테스트가 830개가 됐고(42개 삭제 + T-9로 2개 보강), `tests/`는 누적 -1,202줄, 라인 커버리지는 97%→98%(5,013문 중 121 미커버)다. 스위트는 커버리지 포함 약 3분 50초에 끝난다.

### 순서: 테스트를 먼저 쓰고, 실패를 눈으로 본 뒤 구현한다

1. 테스트 작성 → 2. `uv run pytest -k <신규>` **→ 실패 확인(실측)** → 3. 실패 메시지를 `progress.md`에 한 줄 → 4. 구현 → 5. `uv run pytest` 전체 초록 → 6. 커밋(src + tests 하나)

**2번을 건너뛰지 않는다. 이유는 커버리지가 못 하는 것에 있다.**

커버리지는 *그 줄이 실행됐다*만 증명하고, *그 단언이 틀린 값에서 깨진다*는 증명하지 못한다. `assert resp.status_code == 200` 하나짜리 테스트는 라우터 본문 전체를 커버하면서 아무것도 검증하지 않는다 — **커버리지 100%와 신호 0이 양립한다.** CI의 95% 게이트는 이 빈틈을 원리적으로 못 막고, 빨간 걸 눈으로 보는 것은 막는다.

**이 근거는 실증됐다.** 순수 로직 7모듈 485줄에 뮤테이션 테스트(329 뮤턴트, 스코어 82.3%)를 1회 돌렸더니 생존 41개 중 **9개가 진짜 약한 테스트**였고, 그중 셋은 크래시·조용한 데이터 손실이었다 — `chat/stats.py`의 미시드 스탯 경로(`None + delta` → `TypeError`), 같은 파일의 `continue`→`break`(한 턴의 뒤쪽 유효 변경이 통째로 사라짐), `assets/image_processing.py`의 알파 채널 소실. **9개 전부 커버리지가 이미 그 줄을 덮고 있던 코드다**(파일 단위로는 7개 중 6개가 100%, `core/s3.py`만 98%이고 그 미커버 줄은 다른 곳이다).

> ⚠️ "TDD가 vacuous 테스트를 없애준다"는 **이 저장소에서는 근거가 되지 않는다.** 런 시작 시점 873개 중 신호 없는 테스트는 3개(0.34%)였다 — 전환 전에 이미 거의 없었다. 양쪽에서 같은 값이 나오는 근거는 아무것도 논증하지 못한다. 위의 커버리지·뮤테이션 논거만 쓴다.

**다만 이건 게이트가 아니라 습관이다.** CI는 "테스트를 먼저 썼는지"를 확인할 방법이 없다 — src+tests가 한 커밋으로 들어가면 순서는 기록에 안 남는다. 근거가 확실하다고 강제되는 건 아니니 스스로 지킬 것.

**예외 — 모델 + 마이그레이션 작업은 구현이 먼저다.** `create_all`이 이 코드베이스에 없어서 테이블은 오직 `alembic upgrade head`로만 생긴다(`conftest.py`의 `_migrated_schema`). 새 테이블을 건드리는 테스트는 마이그레이션 전에 **실행 자체가 불가능**하다. 게이트는 `alembic check` + `_migrated_schema`의 upgrade/downgrade 왕복이고, 로직 테스트는 그 위에 얹히는 다음 작업에서 TDD로 쓴다.

### 쓰기 전 관문: "이게 깨지는 시나리오"를 한 문장으로 쓴다

못 쓰면 쓰지 않는다. 아래는 이 관문을 통과하지 못한다.

- **선언을 되읊는 테스트.** FK·유니크·`Field(min_length=…)`·enum·`Literal`은 **선언이 곧 스펙**이다. `relationship()`이 금지(ruff `banned-api`)라 SQLAlchemy `ForeignKey`는 항상 DB 제약이 되고, `alembic check`가 이 범주의 model↔migration drift를 잡는다.
  - ⚠️ **예외 — CHECK 제약과 복합 PK는 이 규칙에서 빼라.** `alembic check`가 **이 둘을 비교하지 않는다**(alembic 1.18.5 `autogenerate/compare`에 `CheckConstraint`·`primary_key` 언급 0건, `setup()`이 등록하는 비교자는 index/unique·FK·nullable 셋뿐). 이 둘은 **`pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증**이니 지우지 마라. 2026-09-08에 이걸 모르고 지웠다가 6개 불변식이 무검증이 됐고, 적대적 리뷰가 잡아내 행위 테스트 6개를 되살렸다.
- **`sa.inspect()`로 스키마를 손으로 나열하는 테스트.** `alembic check`의 중복이다.

- 반대로 **라우터가 손으로 하는 검증은 테스트한다** — `admin_comment`/`reason_text` 공백 422처럼 pydantic이 아니라 코드가 판단하는 것.

2026-09-08에 위 두 부류를 합쳐 42개를 지웠다(FK·유니크 미러 17 + 타입선언 미러 11 + `test_migrations.py` 14).

### 밀도는 엔드포인트 수가 아니라 폭발 반경으로 정한다

| 구역 | 밀도 |
|---|---|
| 전 사용자 영향 + 되돌릴 수 없음 — 인증·세션·정지, 발행 트랜잭션, 탈퇴, 채팅 메시지 CRUD | **분기마다** |
| 전 사용자 영향 + 되돌릴 수 있음 — 목록·상세·좋아요·즐겨찾기 | happy path + 권한 가드 + 경계 1개 |
| 운영자 본인만 영향 — admin, 시드 CLI | happy path + 권한 가드 |

2026-09-08 실측에서 밀도는 균일했다(admin 5.7 tests/route, public 6.9). **균일한 것이 문제다** — admin 버그는 운영자 1명이 겪고 chat 버그는 전 사용자가 겪는다.

### 형태

- **같은 모양이 3번 나오고 + 접어서 실제로 짧아질 때만 `@pytest.mark.parametrize`.**
  - ⚠️ **3번 기준만으로는 부족하다.** 2026-09-08에 후보 11곳을 실제로 접어 보니 **8곳이 오히려 길어졌다**(`+1`~`+8`줄). 이득이 난 건 3곳뿐(`-21`·`-8`·`-2`).
  - 이득이 나는 조건은 둘이다 — **① 부를 헬퍼가 이미 있다**(`test_admin_users_api.py`의 `_assert_requires_admin_session`, -21줄) 또는 **② 멤버 본문이 여러 줄이다**. 멤버가 2~3개이고 본문이 3줄짜리면 `pytest.param` 리스트 + 데코레이터 + 래퍼 시그니처가 원본보다 길다.
  - 길어지면 접지 않는다. **간접층도 같이 늘어난다** — `db_client.delete("/me")`가 `db_client.request(method.upper(), path, json=json)`이 된다.
  - 케이스 id는 `pytest.param(..., id=...)`로 **명시한다.** path에 `uuid.uuid4()`가 섞이면 자동 id가 실행마다 바뀐다.
- **셋업 헬퍼는 `tests/factories.py`에.** 두 번째 파일에 복사하는 순간 옮긴다. 테스트 파일이 다른 테스트 파일을 import하는 일은 없어야 한다.
- **팩토리를 합치는 기준은 인자 3개.** 넘으면 합치지 말고 지역에 남긴다 — 팩토리가 두 번째 설정 언어가 되면 안 된다.
- LLM·외부 HTTP는 `mock.patch`가 아니라 **`app.dependency_overrides`**로 갈아끼운다(라우터가 `Depends`로 받는 이유가 이것이다).

### 지우는 규칙

- **커버리지 95%가 하한이다**(CI `--cov-fail-under=95`, 2026-09-08 기준 실측 98%라 여유 3%p). 이 선을 지키면 테스트를 지워도 된다.
- src에서 코드가 사라지면 그 테스트도 사라진다. 리팩터로 케이스가 합쳐지면 테스트도 합친다.
- **지울 때 근거가 "느낌"이면 지우지 않는다.** 지우기 전후로 커버리지를 재고, 떨어지면 되살린다.
- ⚠️ **이 안전장치는 스키마·제약 테스트에는 원리적으로 작동하지 않는다.** `sa.inspect()`·`pytest.raises(IntegrityError)` 계열은 `src/`를 실행하지 않으므로 지워도 커버리지가 안 떨어진다 — 2026-09-08에 커버리지가 97%→98%로 오르는 동안 여섯 불변식(CHECK 제약·복합 PK)의 검증이 함께 사라진 사고가 이 사실을 실증했다(위 "쓰기 전 관문"의 예외 참고). 이 부류는 **`alembic check`가 실제로 비교하는 범주인지**부터 확인하고 지워라.

### 커버리지로 부족하다고 느껴지면 뮤테이션 테스트

커버리지가 이미 100%인 구간에서 "이 테스트가 진짜 버그를 잡나"를 묻는 유일한 방법이다. 소스를 기계적으로 변형하고(`==`→`!=`, `>`→`>=`, 상수 치환) 테스트가 깨지는지 본다.

- **범위는 DB를 안 타는 순수 로직으로 못 박는다.** 그 구간은 뮤턴트당 2.5초지만 DB를 타면 3분이 된다(2026-09-08 실측).
- **1회성 측정이다. CI에 상시화하지 않는다.**
- **생존 뮤턴트를 셋으로 분류한 뒤에야 숫자를 인용한다** — ① 진짜 약한 테스트 ② 등가 뮤턴트(동작이 안 바뀜) ③ 테스트할 가치 없는 코드. 분류를 건너뛰고 스코어만 인용하면 등가 뮤턴트가 섞여 숫자가 부푼다.
- **2026-09-08 결과**: 7모듈 485줄, 329 뮤턴트, 스코어 82.3%(190/231, 커버 없는 98 제외). 생존 41개 중 **진짜 약한 테스트는 9개**였다.
- **뮤테이션이 잡아낸 것 중 가장 교훈적인 하나** — `chat/ending_rules.py`의 `(turn_count - turn_count_gate) % 5`에서 `-`를 `+`로 바꿔도 4개 테스트 전부가 통과했다. **테스트가 모두 `turn_count_gate=10`을 쓰고 `2×10 mod 5 == 0`이라, 두 연산자가 모든 `turn_count`에서 같은 값을 낸다.** 셋업이 검증 대상을 구분 불가능하게 만든 항진명제다. 같은 부류로 역할 라벨 삼항 3건이 걸렸는데(`history` 픽스처에 USER 메시지만 넣어 `else` 분기를 안 탐), **형제 함수들은 역할을 섞어 넣어서 그쪽 삼항은 생존 목록에 아예 없었다** — 우연이 아니라 픽스처 설계의 차이였다.
- **경계 값을 하나만 쓰지 마라.** 위 둘은 같은 원인이다 — 파라미터를 한 값으로만 테스트하면 그 값에서 우연히 같아지는 버그를 영구히 못 본다.

돌릴 때(`mutmut` 기준) 함정 넷:
- **`--max-children 1` 필수.** 기본값은 병렬 실행이라 자식들이 같은 공유 테스트 DB에 동시에 `alembic upgrade`/`downgrade`를 걸어 서로를 파괴한다.
- **`source_paths = src`로 둔다.** 대상 파일 9개로 좁히면 `conftest.py`의 `from api.main import app`이 `src/api` 트리 전체를 요구해서 실패한다 — 좁히는 건 `only_mutate` 쪽이다.
- **`also_copy`에 `alembic.ini`·`migrations/`를 넣는다.** 둘 다 `src/` 밖이라 기본 복사 대상이 아닌데 빠지면 모든 뮤턴트가 `FileNotFoundError`로 즉사한다.
- **"DB를 안 쓴다"를 `db_session`/`db_client` 미사용으로만 판단하면 Redis를 놓친다.** `api.core.redis.redis_client`는 모듈 레벨 싱글턴이라 최초 이벤트루프에 묶이는데, mutmut은 같은 프로세스에서 `pytest.main()`을 반복 호출하므로 `Future attached to a different loop`로 죽는다. 실제로 대상 9개 중 2개(`content/view_count.py`, `auth/verification.py`)가 여기 걸려 7개로 줄었다.

### 커버리지 계측 함정 (밟으면 30분 날아간다)

- **`concurrency = ["thread", "greenlet"]`이 없으면 라우트 핸들러 본문이 통째로 미커버로 나온다.** SQLAlchemy asyncio가 greenlet 위에서 돌기 때문이다. 2026-09-08 실측: 없으면 `auth/router.py` 62%, 있으면 96%. **통과하는 테스트가 있는데도 그 경로가 미커버로 찍히면 이 설정부터 의심한다.**
- `--cov=src/api`(경로 형태)는 `module-not-imported` 경고와 함께 조용히 어긋난다. `[tool.coverage.run] source = ["api"]`(패키지 이름)를 쓴다.

### pytest는 절대 동시에 두 개 돌리지 않는다 — 단, "동시"의 판정을 정확히 할 것

테스트 DB(`ai_character_chat_test`)가 **공유 싱글턴**이고 스위트가 teardown에서 `alembic downgrade base`로 테이블을 전부 지운다. 두 프로세스가 겹치면 한쪽이 상대의 스키마를 지워 대량 실패가 난다 — **회귀로 오독하기 쉽다.**

- **`pgrep -f pytest`만으로는 부족하다.** 잡힌 프로세스의 실행 경로를 `ps -o command= -p <pid>`로 봐야 한다. `.claude/worktrees/` 아래에서 도는 pytest는 그 워크트리 자신의 `.env`에 있는 `TEST_DATABASE_URL`/`TEST_REDIS_URL`을 쓰므로 **다른 자원이라 기다릴 필요가 없다.** 같은 `apps/api/.venv`에서 도는 것만 진짜 충돌이다.
- 저장소를 여러 세션이 공유하니 **자기 실행도 `TEST_DATABASE_URL`/`TEST_REDIS_URL`로 격리**해서 다른 세션의 실행과 부딪히지 않게 할 것.

### 알려진 갭 — `tests/`는 mypy 대상이 아니다

- **CI는 `tests/`를 mypy로 검사하지 않는다** (`mypy src migrations scripts`). 2026-09-08 기준 `uv run mypy tests`는 **11개 에러 / 7개 파일**을 낸다. 아래 `## 테스트 인프라`의 "LLM 페이크 시그니처가 어긋나면 `[override]` mypy 에러가 여러 테스트 파일에서 동시에 난다"는 **로컬에서 `mypy .`을 돌렸을 때만 참이다** — CI 는 그걸 잡지 못한다.

## 테스트 인프라

- **이벤트루프 스코프가 전부다.** `asyncio_default_fixture_loop_scope`/`_test_loop_scope`를 `"session"`으로 명시하지 않으면, 모듈 전역 engine(asyncpg 풀)이 최초 루프에 묶여 **두 번째 테스트부터 `InterfaceError`**가 난다.
  - 같은 이유로 **`TestClient`를 쓰지 않는다** — 호출마다 별도 백그라운드 루프를 띄워 세션 스코프 루프와 섞이면 "Future attached to a different loop"가 실행 순서에 따라 산발적으로 난다. `httpx.AsyncClient(transport=ASGITransport(app=app))`(`api_client`/`db_client`)를 쓸 것.
- **테스트는 dev와 분리된 DB(`ai_character_chat_test`)/Redis(1번)를 쓴다.** `conftest.py`가 `api.core.config` **import 전에** `DATABASE_URL`/`REDIS_URL`을 **직접 대입**한다(`setdefault`는 `--env-file .env`로 돌리면 조용히 무시돼 **dev DB를 밀어버린다**). 이름이 `_test`로 안 끝나면 `RuntimeError`로 거부하고, DB 껍데기는 절대 drop하지 않는다.
- `db_session`은 커넥션 단위 트랜잭션 + 롤백이고, `db_client`가 `get_db_session`·`get_session_factory`를 그 커넥션에 바인딩해 오버라이드한다(`conditional_savepoint` 덕에 애플리케이션 `commit()`이 바깥 트랜잭션을 끝내지 않는다).
  - **그래서 `now()`는 한 테스트 안에서 완전히 동일한 값이다**(트랜잭션 시작 시각 고정). 라이브 호출 여러 번으로 `created_at` 순서를 검증하려 하지 말고 `created_at`을 명시적으로 다르게 넣을 것.
- **S3는 `mock_aws()`가 아니라 `ThreadedMotoServer`로 흉내낸다** — `api.main`을 이미 import한 프로세스에서는 `mock_aws`의 패치가 `run_in_threadpool` 워커 스레드에 적용되지 않아 HeadObject가 **실제 AWS로 나간다**(실측). 새로 만드는 `boto3.client(...)`에도 항상 `endpoint_url=settings.s3_endpoint_url`을 명시할 것.
- DB I/O가 없는 순수 함수(스탯 클램핑, 규칙 평가, 키워드 매칭)는 **ORM 모델을 세션 없이 생성자로만 채워** 테스트한다(`nullable=False`는 DB 제약일 뿐이라 나머지 필드는 생략 가능).
- **`LLMClient`를 상속하는 모든 페이크는 실제 시그니처를 그대로 따라야 한다**(예: `generate_structured`의 `images` 파라미터) — 빠지면 `[override]` mypy 에러가 여러 테스트 파일에서 동시에 난다. LLM을 실제로 안 쓰는 실패 케이스 테스트도 `get_llm_client` 오버라이드가 필요하다(라우트 본문 전에 resolve되고, 키가 없으면 즉시 `ValueError`).

## mypy strict 함정

- **`func.count().label("count")` 금지** — `Row`가 tuple을 상속해 `count`가 내장 메서드와 충돌한다. `"message_count"`처럼 겹치지 않는 라벨을 쓸 것.
- 키셋 페이지네이션의 `tuple_(a, b) < (x, y)`는 **오른쪽을 평범한 파이썬 튜플로** 둔다(양쪽 다 `tuple_()`로 감싸면 인자 타입이 안 맞는다).
- `ARRAY` 포함 여부는 **SQLAlchemy 표현식을 좌변에**: `any_(Content.hashtags) == value`(반대로 쓰면 `str.__eq__`를 타서 `bool`로 추론된다).
- `Numeric` 컬럼에 float를 **속성 대입**하면 막힌다 → `Decimal(str(x))`. (생성자 kwarg는 `**kw: Any`라 통과한다 — 엄격도가 다르다.)

## 시드 콘텐츠 · 이미지 생성

- 시드의 UUID는 리터럴이 아니라 **uuid5 파생**(`seed_uuid`)이고 `seed_dev.py`는 `session.merge` 업서트라 "이 파일이 곧 시드의 단일 진실"이다. 상세 규약은 `scripts/seed_content/` 코드 주석과 `tasks/archive/prd-genre-seed-content.md` §7·§8에 있다.
- **`settingText`는 사용자용 소개문이 아니라 서술자에게 주는 지시문이다** — "당신은 …입니다"처럼 사용자를 주인공으로 부르면 서술자가 자기를 주인공으로 착각해 화자가 뒤집힌다(발행 검증도 유사도 게이트도 못 잡는다).
- **SDXL 프롬프트는 CLIP 77토큰에서 조용히 잘린다**(에러 없음). 긴 산문 대신 짧은 태그 나열로 쓰고 가장 중요한 지시(인물 수·시선·조명)를 앞에 둘 것.
- 이미 시딩된 환경의 이미지만 교체할 때는 `scripts/upload_seed_images.py`(DB 무변경) — `Asset.id`도 storage key도 slug 파생 고정값이라 바뀌어야 하는 건 바이트뿐이다.

## 알려진 갭

- **이메일 발송이 print 스텁**(`core/email.py`) — `logging.info`를 쓰면 uvicorn이 root logger에 핸들러를 안 붙여 조용히 사라진다. 프로바이더가 정해지면 이 함수 본문만 바꾼다.
- **`_update_story_draft`의 선재 버그**: 제거된 시작설정을 `keyword_notes` 조정보다 먼저 지워서, 어떤 키워드북이 가리키는 시작설정을 빼는 PATCH는 물리 FK 위반으로 500이 난다. 빌더의 시작설정 삭제를 다시 만질 때 같이 고칠 것(노트 prune을 앞으로 옮기거나 참조를 먼저 끊는다).
- **`contents.has_unpublished_changes`가 "초안이 발행본과 다른가"의 단일 소스다**(타임스탬프로는 판정 불가). 세우는 곳은 자동저장·편집취소·발행 셋뿐 — **초안을 바꾸는 새 엔드포인트를 추가하면 이 플래그를 반드시 함께 세울 것.**
