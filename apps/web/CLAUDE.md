# apps/web

프론트엔드 앱 — FSD 6계층 + TanStack Router/Query + RHF/zod + Jotai, 디자인시스템은 `packages/ui`.

**이 문서는 지속 컨벤션과 작업 라우팅만 담는다.** 특정 코드를 만질 때만 필요한 국소 함정은 [`FRONTEND_NOTES.md`](./FRONTEND_NOTES.md), 비주얼 규범·대비 수치는 `DESIGN.md`, 프리미티브 구현은 `packages/ui/CLAUDE.md`다 — **여기에 그 내용을 복제하지 않는다.**

## 작업 라우팅 — "무슨 작업 → 무슨 패턴"

| 작업 | 패턴 / 위치 |
|---|---|
| 폼(멀티스텝 포함) | 단일 `useForm` + 단일 zod 스키마, 스텝 검증은 `form.trigger([...])` |
| 서버 상태 | 단일 `apiClient` · `entities/*/api`의 queryKey 팩토리 · `sessionQueryOptions` 재사용 |
| 인증 라우트 가드 | `beforeLoad: requireSession` — 진입에 데이터 필요 시 `loader`/`loaderDeps` |
| 라우트 파라미터/서치 | RouteComponent가 읽어 페이지에 props 주입(routes↔pages 순환 방지) |
| 서치 파라미터 스키마 | 모든 필드를 `.catch(...)`로 끝낸다 (빠지면 페이지가 통째로 죽는다) |
| 액션/확인 모달 | react-call 2계열 — 후속 동작이 호출부마다 다르면 `mutationFn` 주입형, 같으면 자체 호출형 |
| 자산 업로드 | `shared/api/asset/uploadAsset(file, purpose)` 재사용 |
| 카드 목록 | `entities/content`의 `ContentCard` + `ContentCardActionMenu` + `toContentStatusTags` |
| 브랜드 자산(파비콘·OG) | `public/`을 직접 고치지 말고 `brand/generate.sh`로 재생성 |
| 서버에서만 되는 일(봇 메타·sitemap·리다이렉트) | `worker/` — `dist/_worker.js`로 번들된다 |
| 라우트 추가/삭제 | `src/routes/*.tsx`와 `worker/routes.ts`의 `KNOWN_ROUTES`를 **함께** 고친다 |
| 조회 없이 정해지는 메타 | `index.html`의 `<head>` — Worker가 아니다 |
| 마운트 시 뮤테이션 | `mutateAsync`+`await`+로컬 로딩 state (StrictMode 콜백 손실 회피) |
| SSE | `shared/api/sse/openChatStream`의 `kind` 판별유니언에 분기 추가 |
| 발행 | draft PATCH 먼저 → `publish`(무바디), 400은 `missingFields`/`reason` 분기 |
| 테마 | `shared/model/theme.ts`의 `themeAtom`만 write (DOM·스토리지 직접 금지) |

## 아키텍처 / 라우팅

- **FSD 의존 방향**: `app → pages → widgets → features → entities → shared`(역방향 금지). 같은 레이어 슬라이스끼리 코드를 공유해야 하면 그 코드를 `entities`로 내린다(슬라이스 간 직접 import 금지). **단 폼 컨텍스트(`useFormContext`)를 읽는 UI는 내리지 않고 슬라이스를 합친다** — entity `ui`는 로직을 props로 받는 표현만 담는다(FSD-06; `entities/registration`을 `features/sign-up`으로 되돌린 이유, `fe-convention-refactor-goal-prompt.md R-10`). `routes/*`는 `pages/{page}`를 렌더링만 하는 얇은 어댑터다.
- **레이어를 넘는 import는 `@/` alias**, 같은 슬라이스 내부는 상대경로. 정의가 `tsconfig.json` `paths` + `vite.config.ts`·`vitest.config.ts` `resolve.alias` **세 곳**에 있어 함께 움직인다.
- **`routeTree.gen.ts`는 커밋한다.** `@tanstack/router-plugin`이 `vite dev`/`vite build` 때 생성하므로, 라우트를 바꿨으면 typecheck·커밋 전에 `vite build`를 한 번 돌린다 — `tsc --noEmit`만으로는 fresh checkout에서 생성되지 않아 새 라우트가 검증에서 통째로 누락된다.
- **라우터 컨텍스트**: `createRootRouteWithContext<{queryClient}>()`로 `app/AppProviders.tsx`의 **단일** `queryClient`를 넘긴다(`QueryClientProvider`와 다른 인스턴스면 캐시가 갈린다). 진입 자체에 서버 검증이 필요하면 `beforeLoad`가 아니라 `loader`/`loaderDeps`를 쓰고, 실제 호출은 라우트 파일이 아니라 `features/*`의 순수 async 함수에 둔다.
- **플랫 파일명은 `.`으로 경로를 구분한다**(`onboarding.google.tsx` → `/onboarding/google`). 같은 부모 아래서 정적 세그먼트가 동적 파라미터보다 먼저 매치된다. 인덱스 라우트는 `createFileRoute("/builder/")`(끝 슬래시)로 선언하지만 `fullPath`·`<Link to>`·`KNOWN_ROUTES`는 전부 `/builder`다 — `worker/routes.test.ts`의 `toRoutePattern`이 이 셋을 맞춘다.
- **화면 상태를 유지한 채 URL만 바꿔야 하면 라우트를 하나로 합친다.** 같은 라우트에서 파라미터만 바뀌면 리마운트가 없지만 **다른 라우트 파일로 넘어가면 리마운트한다** — `autoCodeSplitting`이 파일마다 별도 lazy 컴포넌트를 만들어서, 두 파일이 `component:`에 **같은 함수**를 넣어도 소용없다(실측). 빌더가 만들기와 이어쓰기를 `builder.$type.$draftId.tsx` 한 라우트로 받고 `new`를 sentinel로 쓰는 이유다.
- **쿼리 키가 바뀌는 URL 교체는 `setQueryData`로 캐시를 먼저 채우고 `navigate`한다** — 안 그러면 그 렌더가 `isPending`이 되어 아래 트리가 통째로 언마운트된다(리마운트가 없어도).
- **전역 Header는 `widgets/header`, `__root`에 1회 마운트한다**(개별 페이지가 헤더를 렌더하지 않음). 로그인 전용 하위 컴포넌트는 `me`를 props로 받고 세션을 재조회하지 않는다.
- 미구현 화면은 `shared/ui/ComingSoonPage`로 잇되, 라우트 파일은 그 스토리의 최종 형태(`beforeLoad: requireSession` 등)로 만들어 나중에 다시 손대지 않게 한다.

## Cloudflare Pages Worker (`worker/`)

- **`worker/index.ts` → `dist/_worker.js`(Pages Advanced Mode).** **서버 코드를 저장소 루트 `functions/`에 두지 말 것** — web·admin이 둘 다 Root directory를 저장소 루트로 두고 있어(pnpm workspace 때문에 필수) admin이 같은 코드를 집어가 SPA 라우팅이 깨진다.
- **`_worker.js`가 있으면 모든 요청이 Worker로 온다** — `public/_redirects`의 SPA 폴백은 적용되지 않고 Worker가 직접 한다(`serveAppShell`). `_redirects`는 배포 실패로 `_worker.js`가 누락될 때의 안전망이라 지우지 않는다.
- **`env.ASSETS.fetch()`는 존재하지 않는 경로에도 `index.html`을 200으로 준다.** 그래서 (1) 진짜 404는 Worker가 명시적으로 만들어야 하고, (2) **`/sitemap.xml`처럼 확장자가 있는 Worker 생성 경로는 정적 자산 검사보다 먼저** 매치해야 한다(`isStaticAssetPath`가 true를 주므로 그냥 넘기면 index.html이 나간다). `/og/...jpg`도 같은 함정이다.
- **라우팅 순서가 규약이다**: `legacyRedirect`(가장 앞 — 그래야 `/assets/*`·`/sitemap.xml`까지 넘어간다) → 정적 자산 → `KNOWN_ROUTES` 대조 → 봇 분기 → 마지막에 `applyIndexingPolicy`. 새 라우트를 추가할 때 `X-Robots-Tag`를 따로 신경 쓰지 말 것(한 곳에 모아 뒀다).
- **`src/routes/*.tsx`에 라우트를 추가하면 `worker/routes.ts`의 `KNOWN_ROUTES`도 고친다** — 목록에 없는 경로는 셸 본문 + status 404가 되어(soft 404 제거) 새 페이지가 통째로 404다. `worker/routes.test.ts`가 `import.meta.glob`으로 파일 목록을 읽어 대조하는 게 유일한 방어선이다.
- **URL은 요청 host가 아니라 `resolvePublicOrigin(env, request)`으로 만든다**(sitemap·canonical·og:url 전부). **단 `legacyRedirect`의 목적지만은 `env.PUBLIC_ORIGIN`을 직접 읽는다** — 그 함수는 값이 없을 때 요청 오리진으로 폴백하므로 여기서 쓰면 **자기 자신으로 가는 무한 루프**가 된다. 판별은 프로덕션 host **정확 일치**여야 한다(`endsWith`/`includes`는 프리뷰와 브랜치 별칭까지 날린다).
- **환경변수가 빠져도 사이트가 죽지 않게 배선한다**: `API_BASE_URL`(런타임 변수, 빌드타임 `VITE_API_BASE_URL`과 별개)이 없으면 Worker가 SEO 경로를 통째로 건너뛰고 자산만 서빙한다. `PUBLIC_ORIGIN`이 없거나 파싱되지 않으면 `noindex`를 **붙이지 않는다**(오타로 프로덕션이 색인에서 빠지는 쪽이 프리뷰가 색인되는 것보다 위험하다). 홈 메타는 조회가 없어 `API_BASE_URL` 가드보다 **위에** 배선한다.
- **검색엔진 소유확인 파일은 `public/`이 아니라 `worker/siteVerification.ts`에 등록한다** — Pages 자산 서버가 `/foo.html` → `/foo`를 308로 돌려주고, 확장자가 사라진 경로는 `KNOWN_ROUTES`에 없어 404가 된다. 등록 절차는 `DEPLOY.md` §7.
- **API 실패를 오류 응답으로 번역하지 않는다.** `fetchApiJson`은 던지지 않고 `ok`/`notFound`/`unavailable` 세 갈래를 준다 — **`notFound`와 `unavailable`을 절대 합치지 말 것**(장애를 "없음"으로 번역하면 검색엔진이 장애 중에 페이지를 지운다). sitemap은 실패해도 홈만 담은 최소 XML을 200으로 주고, **그 폴백은 Cache API에 넣지 않는다**(몇 초짜리 장애가 한 시간짜리 빈 sitemap이 된다 — 성공 응답만 `cache.put`).
- **봇 HTML은 한 경로로만 만든다**: `buildMetaTags` → `injectHead`. 사용자 입력은 예외 없이 `escapeHtml`을 **정확히 한 번** 통과한다(컨텍스트별로 분기하지 말 것 — 분기가 곧 누락 지점이고, 두 번 적용하면 이중 이스케이프된다). JSON-LD는 `buildJsonLd`로만(`<`를 이스케이프해 `</script>` 탈출을 막는다).
- **봇에게 보일지는 FE와 같은 규칙으로 판정한다** — `GET /contents/{id}`가 비공개·제한 콘텐츠에도 200을 주므로 `isViewableByCrawler`가 `canViewDetailPage`와 같은 조건을 **직접** 건다. 링크 공개(`link`)는 통과시킨다(링크 공유 미리보기가 목적).
- **og:image 주소는 만료되면 안 된다** — presigned URL은 Worker 안에서만 쓰고 버린다(리다이렉트로 넘기면 만료된 주소가 카카오·페이스북 og 캐시에 몇 달 박힌다). 실패는 **확실히 없는 것**(잘못된 UUID·비공개·삭제)만 404, **불확실한 것**(썸네일 미설정·API 장애)은 기본 이미지 200이다.
- **프로필 주입에는 `noindex`를 함께 넣는다**(공유 미리보기는 되게, 색인은 막게 — 사용자가 공개 노출에 동의한 적 없다). 그래서 canonical·JSON-LD도 두지 않고 sitemap에도 넣지 않는다.
- **크롤러는 HEAD를 보낸다.** `caches.default.put`은 non-GET에 던지므로 Worker 응답이 HEAD에서만 500이 될 수 있다(`worker/cache.ts` 어댑터가 막고 있다) — 로컬 검증에서 `curl`뿐 아니라 **`curl -I`도** 확인할 것.
- **런타임 전용 자원은 주입한다** — Cache API는 `WorkerDeps`의 `{match, put}`으로만 다루고 진입점에서 넣는다. 핸들러가 `caches.default`를 직접 참조하면 vitest(`environment: "node"`)에서 그 경로가 통째로 테스트 불가능해진다.
- **브라우저 검증은 vite dev가 아니다** — Worker는 빌드 산출물이므로 `build && dev:worker`(= `wrangler pages dev dist`). 로컬 API의 CORS가 `5173`/`5174`뿐이라 `--port 5174`로 띄운다.
- **알려진 갭**: 봇 경로가 `GET /contents/{id}`를 부르면 **조회수가 1 오른다**(Worker fetch에 쿠키가 없어 서버가 새 게스트로 센다). Cache API가 빈도를 누르지만 없애려면 백엔드에 크롤러 제외가 필요하다.

## 데이터 / 상태

- **단일 `apiClient`**(직접 `axios.create` 금지). 인증은 httpOnly 세션 쿠키 + `withCredentials`. 응답 인터셉터가 모든 에러를 `ApiError`로 정규화한다 — `detail`이 string이면 메시지, dict면 구조값, 422 배열이면 `fields`. **서버 `detail`(영어 디버그 문구)을 그대로 노출하지 말고** `status`로 분기해 한국어 카피를 쓴다.
- **세션은 `sessionQueryOptions` 하나를 `useSessionQuery`와 `requireSession`이 공유한다**(키·함수·staleTime이 어긋나면 캐시가 갈린다). 세션 변경 뮤테이션은 invalidate만 한다. 단 **로그아웃처럼 즉시 반영이 필요하면 `resetQueries`** — `invalidateQueries`는 리페치까지 옛 값을 유지하고 `setQueryData(key, undefined)`는 문서화된 no-op이다.
- 인증 과정에서만 쓰는 데이터(토큰·로그인 DTO)로 **별도 user entity를 만들지 않는다**(의존성 순환).
- **캐시 처방은 "낡았다"와 "틀렸다"로 갈린다.** 서버 상태를 **버리는** 뮤테이션(편집 취소·삭제)에는 `invalidateQueries`가 아니라 **`removeQueries`**다 — invalidate는 관찰자 없는 쿼리를 stale로 **표시만 하고 데이터를 남겨서**, 재마운트 시 낡은 값이 즉시 서빙되고 그 값으로 폼이 굳은 뒤 다음 자동저장이 **방금 버린 것을 서버에 도로 써넣는다**(빌더에서 실측 재현). **한 뮤테이션 안에서도 캐시마다 갈린다** — 같은 편집 취소가 초안 캐시는 `removeQueries`(틀렸다), 작가 목록 캐시는 `invalidateQueries`(낡았다)다. 목록에 remove를 쓰면 보고 있던 `useInfiniteQuery`가 `isPending`으로 되돌아가 "더 보기"로 불러온 페이지가 날아간다. 판단 기준은 **"이 캐시에 방금 버린 값이 들어 있나"**다.
- **서버 데이터를 `defaultValues`로 굳히는 화면에서는 그 데이터를 바꾸는 뮤테이션이 캐시도 함께 갱신해야 한다** — 안 하면 캐시가 진입 시점 스냅샷에 멈추고, `gcTime`(기본 5분) 안에 돌아온 사용자의 폼이 낡은 값으로 굳어 자동저장이 직전 편집을 덮어쓴다. 저장 경로에서는 invalidate가 아니라 **응답으로 `setQueryData`**를 쓴다(invalidate면 1.5초마다 리페치가 돈다).
- **presigned GET URL이 박힌 쿼리는 캐시 금지** — `gcTime: 0`. 기본 5분이면 모달을 다시 열 때 직전 스냅샷이 먼저 페인트된다.
- **자산 업로드는 `uploadAsset(file, purpose)`** — presigned 발급 → S3 직접 PUT(외부 절대 URL이라 `fetch`) → complete. PUT 전에 purpose별 `resizeImage`를 돌리므로 올라가는 건 언제나 WebP이고, `<input accept>`도 png/jpeg/webp뿐이다. 실패 카피는 직접 쓰지 말고 `uploadAssetErrorMessage(error)`를 그대로 토스트에 넘긴다. **새 purpose를 추가하면 `RESIZE_SPEC_BY_PURPOSE`/`MAX_UPLOAD_BYTES_BY_PURPOSE`(서버 `UPLOAD_SIZE_LIMIT_BYTES`와 같은 값)도 함께 채운다.**
- **retry 기본 3회 지수백오프는 4xx엔 무의미** → `retry: (n, e) => (e.status === 0 || e.status >= 500) && n < 3`(전역 기본값은 아직 없다).
- **잡 상태 폴링은 함수형 `refetchInterval`** — `(query) => isTerminal(query.state.data?.status) ? false : ms`. 고정 숫자는 영구 폴링이 된다.
- **`navigate({search})`에 객체 리터럴을 주면 다른 필드가 날아간다** → 항상 함수형 업데이터. **기본값은 파라미터의 *부재*로 표현한다**(스키마가 기본값 멤버를 아예 받지 않게 하고, 부재를 펴 주는 함수 하나를 화면·필터·라벨이 함께 본다 — 걸러내지 않는 정렬 축도 여기 넣는다). **한 축을 바꿀 때 다른 축도 정규화된 값으로 다시 쓴다** — 안 그러면 죽은 파라미터가 축을 되돌리는 순간 되살아난다.
- **`validateSearch` 스키마의 모든 필드는 `.catch(...)`로 끝난다.** 하나라도 빠지면 어긋난 URL이 페이지를 통째로 죽인다(라우터가 던져 앱 크롬 없는 영문 에러 상자만 남는다). **어긋남은 값이 목록 밖일 때만 생기지 않는다** — `parseSearchWith(JSON.parse)` 때문에 `?q=1`은 `z.string()`에 **숫자로** 도착한다. 기본값이 부재인 축은 `.optional().catch(undefined)`, 토큰류는 `.catch("")`로 "없음"에 접는다. `.catch()`는 `<Link search>` 타입 검사를 느슨하게 만들지 않는다(읽을 때 관대, 쓸 때 엄격). 규약은 `shared/lib/search-params/searchSchemaContract.test.ts`가 소스 스캔으로 강제한다(라우트 모듈을 import하면 vitest `node` 환경에서 `localStorage` 접근에 죽어서, 파일을 문자열로 읽어 검사한다).
- **낙관적 토글은 캐시 `onMutate`가 아니라 로컬 override state** + `useDebounce`로 네트워크만 지연 + `onSettled` 조건부 리셋. `setState`는 항상 함수형 업데이터(렌더 클로저를 캡처하면 배칭 시 스테일).
- **마운트 시 뮤테이션은 `mutateAsync`+`await`** — `useEffect`에서 `.mutate(vars, {onSuccess})`에 의존하면 StrictMode의 마운트→언마운트→재마운트가 `MutationObserver`를 영구 제거해 콜백과 반응형 `isPending`이 그 순간 값에 멈춘다. "결과와 무관하게 항상 일어나야 할" 부수효과는 훅 정의의 `onSuccess`에 둔다.
- **1회성 배너**: 뮤테이션 성공 즉시 꺼지는 서버 플래그를 렌더 조건으로 직접 쓰면 뜨자마자 사라진다 → "봤다"를 로컬 state로 분리한다.
- **SSE는 `openChatStream`** (fetch 기반, `credentials: "include"`, `kind` 판별유니언). 스트리밍 중 텍스트는 로컬 버퍼에 두고(Query 캐시와 이중상태 금지) 종료 시 비운다. 캐시 조작은 훅이 아니라 `QueryClient`를 인자로 받는 **순수 함수**로 두면 `new QueryClient()`만으로 테스트된다.
- **rule-engine(엔딩 스탯 규칙 타입·평가)은 `entities/chat-room/model/endingRules.ts`가 SSOT** — BE `apps/api/src/api/chat/ending_rules.py`의 `evaluate_item`/`evaluate_rule_list`와 같은 techspec §1.5 의사코드를 각자 구현한 짝이고(연산자는 FE 6 · BE 5, FRONTEND_NOTES), 같은 슬라이스의 `chatRoomState`가 재수출해 index로 공개한다. 빌더 스키마(`features/build-story`)는 BE와 맞춘 5개 연산자로 독자 선언하고 타입만 구조적으로 맞춘다(FRONTEND_NOTES). `noUncheckedIndexedAccess` 때문에 배열은 인덱싱 대신 구조분해 + `for...of`.
- **테마는 `themeAtom` 하나만 write**(localStorage 저장 + `<html>` dark 토글까지 이 atom 책임). 초기값 규칙("light" 저장값일 때만 라이트, 그 외 다크)은 `index.html`의 FOUC 방지 인라인 스크립트와 **반드시 동일**하게 유지한다.

## 폼 / 빌더

- **멀티스텝도 단일 `useForm` + 단일 zod 스키마**를 전체 스텝이 공유한다. 스텝 검증은 `form.trigger(['필드'])`(도달 안 한 스텝의 필수 필드가 현재 제출을 막지 않는다). `handleSubmit`은 전체 검증이라 스텝 제출에 쓰지 않는다. 위저드마다 `useForm`을 새로 만들고, **현재 스텝은 page의 `useState`가 소유해 위저드에 `step`/`onStepChange` props로 넘긴다**(모듈 전역 싱글턴 atom은 라우트를 떠나도 살아남아 폼 값만 비워진 채 중간 스텝으로 재진입하는 막다른 상태를 만든다).
- **`formToServer`/`serverToForm`이 이름·모양 변환을 전담한다.** draft를 표현해야 하는 필수 선택 필드는 `.nullable()`(`z.enum`엔 "미선택" 멤버가 없어 서버 `null`을 못 담는다), 배열 `order`는 배열 위치 자체(명시 숫자 필드를 만들지 말 것). **실제 필드명은 `packages/api-types/src/generated.ts`에서 확인한다** — 스펙 문서의 이름과 다른 사례가 있었다.
- **shadcn `Checkbox`는 `register()`로 못 묶는다**(Radix `checked`/`onCheckedChange`) → `Controller` 또는 `watch`/`setValue`.
- **shadcn `Select`로 숫자 필드를 다룰 때 `z.coerce.number()`를 쓰지 말 것** — `onValueChange`에서 이미 `Number(v)`로 넣는데, `z.coerce`는 스키마 input 타입을 `unknown`으로 만들어 `zodResolver`의 input/output이 어긋난다. `z.coerce`는 항상 string인 네이티브 컨트롤에만 필요하다.
- **자동저장은 `features/build-common`의 `useAutosave`** — 각 빌더는 자기 `formToServer`만 주입하고 디바운스를 재구현하지 않는다. 디바운스된 저장은 호출부에 catch할 자리가 없으므로 실패 토스트를 훅이 직접 띄운다(`saveNow`의 실패만 호출부 몫).
- **`useAutosave`에 넘기는 `save`는 렌더마다 같은 함수여야 한다.** 인라인 화살표를 주면 매 렌더 새 디바운스가 생기는데 이전 타이머는 취소되지 않아 **입력 한 글자마다 PATCH가 나간다**. `useWatch`가 키 입력마다 리렌더를 일으키므로 이 함정은 항상 켜져 있다. **의존성 배열에 바뀌는 값이 하나라도 있으면 깨진다** — `useDraftPersistence`가 `draftId`(undefined → 초안 id)를 클로저 대신 `useRef`로 읽는 이유다.
- **언마운트 때 대기 중인 디바운스 저장은 "버릴지 실행할지"를 갈라야 한다**(`flushOnUnmount`). 그냥 두면 떠난 화면 위로 실패 토스트가 뜨고 URL 교체가 **사용자를 빌더로 되돌려 놓는다**. 반대로 `cancel`만 하면 마지막 편집이 조용히 사라진다("자동으로 저장돼요"라고 적어 두고 어기는 셈이다). **초안이 이미 있으면 flush, 아직 없으면 cancel.**
- **반복 발화하는 시스템 주도 토스트는 `id` 고정 + `duration: Infinity` + `closeButton`이 한 세트다.** id가 없으면 실패 횟수만큼 쌓이고(600px 이하에선 전체 폭 바닥 고정이라 입력 필드를 가린다), 기본 4초면 "마지막 편집이 서버에 없다"는 **지속 상태**가 눈을 뗀 사이 사라진다. 해제는 다음 저장 성공·닫기·이탈 셋이고 언마운트에서도 같은 id를 dismiss한다. **성공 토스트는 띄우지 않는다**(1.5초마다 초록 토스트는 재앙).
- **`QueryClient`가 기본 `networkMode: "online"`이라 진짜 오프라인에서는 뮤테이션이 실패하지 않고 pause된다**(재접속 시 큐가 한꺼번에 발사된다 — 실측 9건 동시). "오프라인이면 실패 토스트가 뜬다"는 틀린 가정이다. **"저장 중/저장됨" 인디케이터를 만들 거라면 이 pause 구간에서 거짓말을 하지 않는지부터 확인할 것.**
- **빌더 초안은 첫 자동저장 시점에 만들어진다.** `useDraftPersistence`가 그 경로(없으면 생성 → PATCH → URL 교체)를 소유하고, 생성 1회 보장은 순수 헬퍼 `runOnce`가 맡는다. 초안 id가 필요한 액션은 값이 아니라 **함수**(`ensureContentVersionId()`)를 받아 생성을 먼저 트리거한다. `createEmptyDraft(type)`가 서버 기본값을 흉내 내므로 서버가 바뀌면 여기도 바꾼다.
- **발행 버튼은 비활성화하지 않는다** — `disabled`는 왜 못 누르는지 알려주지 않는다. 대신 `zodResolver` + `form.handleSubmit(handlePublish, handlePublishInvalid)`로 검증해 실패를 탭·필드 에러로 보여준다(builder-goal-prompt.md §5-2/§5-4, D-3 — 이전엔 `builderSchema.safeParse(useWatch({control}))`로 버튼을 비활성했었다).
- **발행은 `parse()` → `formToServer()` → draft PATCH → `publish()` 순서다**(`publish`가 무바디라 중간 debounce 미반영 값이 누락된다). 400 `detail`은 `{missingFields}`(토스트)와 `{reason}`(이의제기 배너) 두 모양 — `"reason" in detail`로 먼저 판별한다. nullable draft 스키마는 `safeParse`를 통과해도 서버 필수값이 빌 수 있어 `missingFields`→한국어 라벨 매핑이 필요하다.
- **`useFieldArray`**: 순서 없는 배열은 `fields.map(key={field.id})` + `append({id: crypto.randomUUID()})`. 순서=우선순위면 `@dnd-kit/sortable` + `move`(listeners는 드래그 핸들에만). 부모의 동적 인덱스에 `name`이 의존하는 중첩 배열은 **부모 안정 `id`로 key**를 줘 통째로 remount(인덱스로 key 금지). 재귀 트리는 `useFieldArray` 대신 `items`/`onChange` 순수 제어 컴포넌트로.

## UI / 컴포넌트

### 카드 · 목록

- **클릭 카드**는 바깥을 `role="button"` div(`tabIndex=0` + Enter/Space)로 만든다(`<button>` 중첩은 무효 HTML). 공용 `ContentCard`가 이 패턴이고, **`<Link>` 카드에는 focus 링을 직접 붙인다**(전역 base의 1px UA 아웃라인은 카드 위에서 3:1 미달) — `button.tsx`와 같은 문자열 + 터치의 유일한 피드백인 `active:translate-y-px`.
- **클릭 카드 안에 Radix 메뉴를 넣으면 트리거와 콘텐츠 *양쪽*에서 `onClick`과 `onKeyDown`을 **둘 다** `stopPropagation` 해야 한다** — 콘텐츠는 body로 포털되지만 React 합성 이벤트는 컴포넌트 트리를 타고 올라오고, 항목을 **키보드로** 고를 때의 Enter는 click이 아니라 keydown으로 카드에 닿는다(막지 않으면 확인 모달과 상세 모달이 동시에 열린다). **그래서 "⋯" 메뉴를 직접 만들지 말고 `ContentCardActionMenu`를 쓴다** — 지켜야 할 넷(양쪽 stopPropagation, `hover:bg-secondary aria-expanded:bg-secondary`, `w-auto`, 이름 있는 `aria-label`)이 전부 거기 있다. 계약으로 호출부에 떠넘겼더니 실제로 두 화면의 `aria-label`이 갈렸다.
- **hover 표면을 가진 클릭 카드 안의 `ghost` 아이콘 버튼은 hover가 픽셀상 사라진다** — 포인터가 버튼 위에 있으면 카드도 동시에 hover라 둘 다 `bg-muted`가 되어 값이 정확히 같아진다. 호출부에서 `hover:bg-secondary aria-expanded:bg-secondary`로 한 칸 올린다(`secondary`는 카드의 두 표면 양쪽에서 살아남는다). **⚠️ 2026-09-11 — `ContentCard`는 더 이상 여기 해당하지 않는다**: 카드 껍데기(배경·보더·hover)를 통째로 걷어 카드 hover 자체가 없어졌으므로 충돌할 표면이 없다. 그 카드의 `ContentCardActionMenu`·썸네일 웰·상태 배지에 남은 처방은 **지금은 불필요하지만 해롭지도 않아 그대로 뒀다**(값 자체는 여전히 유효한 대비를 낸다). 이 항목은 아직 button-outline 레시피를 쓰는 클릭 카드 4곳(`InquiriesPage`·`NoticesPage`·`BuilderTypeSelectPage`·`MyChatRoomListView`)에 유효하다.
- **`role="button"` 카드의 이름은 `aria-labelledby`로 푼다.** 카드가 접근가능 이름을 **콘텐츠에서 계산**하므로 안의 버튼 label을 통째로 흡수하고(⋯에 이름을 넣으면 제목을 두 번 읽는다), 그렇다고 ⋯를 `"더보기"`로만 두면 그리드에 같은 이름의 버튼이 32개 생긴다. 카드가 자기 제목·지표·배지 노드를 직접 가리키면 `actions`의 버튼만 이름에서 빠진다. **렌더되지 않은 자식의 id를 목록에 남기지 말 것**(조건부 슬롯이 많아 어긋난다).
- **카드 상태 배지 조합은 `toContentStatusTags`가 정한다 — 화면마다 만들지 말 것.** 공개범위 배지와 `이용제한` 배지는 **함께** 나간다(이용제한이어도 작가는 자기가 뭘로 설정했는지 알아야 한다). 조합을 두 화면이 각자 가지면 같은 작품이 한 화면에서는 `이용제한`, 다른 화면에서는 `공개`가 된다(실제로 그랬다).
- **잘린 제목 옆의 "⋯"는 `gap-2`**(4px면 말줄임 `…`과 아이콘의 점 여섯 개가 한 덩어리로 읽힌다). 한국어 제목은 카드 폭에서 거의 항상 잘린다. **버튼이 제목 줄 높이를 20→32px로 키우므로 로딩 스켈레톤의 제목 바도 함께 옮겨야** 목록 도착 시 점프가 없다.
- **커서 페이징 목록의 건수 라벨은 총계를 주장하면 안 된다**(총계 API가 없다) — 남은 페이지가 있는 동안만 `표시 중`을 달아 문구가 거짓이 되지 않게 한다. 클라이언트에서 거르는 축이 있으면 "불러온 N건 중 0건"인 상태가 존재하므로 빈 상태 문장도 범위를 좁히고 "더 보기"를 그 아래 남긴다.
- **여러 엔드포인트를 클라이언트에서 합치는 목록은 "더 보기"가 어느 스트림을 당기는지 한 함수가 정한다** — 필터 함수와 짝이 맞는지 테스트가 대조한다. 어긋나면 화면에서는 "버튼을 눌렀는데 아무 일도 안 일어난다"로만 보인다.
- **무한스크롤**은 `useInfiniteScrollSentinel` + `useInfiniteQuery`. 정렬·필터로 queryKey가 바뀌면 그 자체로 새 쿼리라 `isPending`이 다시 true다(별도 로딩 state 없이 스켈레톤 재사용).

### 메뉴 · 모달

- **react-call 2계열**: 성공 후 동작이 호출부마다 갈리면 `mutationFn` **주입형**(컴포넌트는 입력 UI만), 항상 같으면 **자체 호출형**. 입력 없는 확인/취소는 공용 모달 재사용. Callable은 `routes/__root.tsx`에 1회 마운트, `open={!call.ended}` + `onOpenChange`.
- **비활성 메뉴 항목에 사유를 붙일 거면 `disabled`가 아니라 `aria-disabled`다**(근거·수치는 `packages/ui/CLAUDE.md`). 사유는 항목 **바로 아래** `DropdownMenuLabel`에 두고 `aria-describedby`로 가리킨다 — **여기엔 구분선을 넣지 않는다**(그 문장은 다음 그룹의 머리가 아니라 위 항목의 설명이라, 넣으면 무엇에 대한 설명인지가 끊긴다). `w-auto` 메뉴에서는 문장 하나가 메뉴 폭을 정하므로 `max-w-*`와 `break-keep`을 함께 준다.
- **`DropdownMenuLabel`로 그룹을 나눴으면 `DropdownMenuSeparator`도 반드시 함께 둔다.** 콘텐츠에 flex도 gap도 없어 행 박스가 그대로 맞닿아, 그룹 경계의 광학 간격이 같은 그룹 안 항목 간격과 **완전히 같다**(근접성 축의 기여가 0이라 유사성 축 혼자 경계를 진다). "라벨이 이미 경계를 그으니 구분선은 중복"은 이 프리미티브에서 거짓이다.
- **카드 그리드의 메뉴에는 `collisionPadding={8}`** — 기본값 0이라 트리거가 화면 끝까지 가면 충돌 보정이 정확히 `x=0`에 놓는다. 필요한 지점에서만 발화하고 충돌 없는 위치의 `align="end"`는 흐트러지지 않는다(셸에 이미 들어 있다).
- **`SelectTrigger` 안에는 반드시 `SelectValue`가 있어야 한다.** 값 표시를 커스터마이즈하려고 텍스트를 직접 넣으면 `position="item-aligned"`(저장소 기본값)이 `valueNode`를 기다리다 포지셔닝·포커스 이관을 아예 하지 않아 **마우스로도 키보드로도 못 고르는** 드롭다운이 된다(타입체크·테스트·코드리뷰를 전부 통과하는 결함이다). 문구를 바꾸려면 루트에 `value=""` + `SelectValue placeholder`를 쓴다.
- **자동완성 드롭다운**은 `relative` 래퍼 + 조건부 `absolute` div로 충분하다(`packages/ui`에 Popover/Command 없음). 스크롤 컨테이너 **안**이면 `fixed`/포털이 필요하다.
- **뷰포트에 따라 Sheet ↔ 인라인 패널을 갈라야 하면 CSS가 아니라 JS로 분기한다**(`useMedia`). Sheet는 body로 포털되어 부모의 `lg:hidden`이 닿지 않고, 열린 Sheet는 포커스 트랩과 바깥 클릭 차단까지 걸어 인라인 패널과 공존할 수 없다 — **둘 중 하나만 마운트되어야 한다.** 브레이크포인트는 두 분기가 공유하는 훅 한 곳에 둔다.
- **알려진 갭 — 루트에 마운트된 react-call 모달은 트리거로 포커스를 돌려주지 않는다**(WCAG 2.4.3). 드롭다운 항목 → 확인 모달 → 닫기 뒤 `activeElement`가 `<body>`로 떨어져 다음 Tab이 헤더부터 다시 시작한다(취소로 닫아도 그렇다). 원인은 Callable이 `__root.tsx`에 마운트돼 카드 트리 밖에서 열리는 것 — DropdownMenu의 복원과 Dialog의 복원이 서로를 모른다. **한 호출부만 고치면 관습이 갈리므로 Callable 래퍼가 `call()` 시점의 `activeElement`를 저장했다가 `call.end()`에서 복원하는 전역 작업으로 잡을 것.**

### 필터 · 빈 상태

- **단일선택 필터 칩은 `Button`이 아니라 `ToggleGroup variant="outline" size="sm"`이다**(`Button`엔 선택 상태가 없어 호출부가 선택 표현을 발명하게 되는데 `DESIGN.md` §Toggles가 그걸 금지한다). 클릭 칩(비필터)은 `Button variant="secondary" size="sm" rounded-full`.
- **필터 축을 `Select`로 그리면 값이 걸렸을 때 채움을 준다** — `SelectTrigger size="sm"`은 `ToggleGroupItem variant="outline" size="sm"`과 **셸이 사실상 같아서**(둘 다 높이 32px·같은 `border-input`·투명 배경. 반경만 D-13 이후 갈린다 — `SelectTrigger`는 `lg`(8px), 칩은 pill), 칩 줄 안에 두면 목록을 32→1건으로 줄인 축이 *꺼진 칩*처럼 보이고 아무것도 안 거른 `전체` 칩만 켜져 **활성 표현이 정확히 뒤집힌다**. `value !== "all" && "bg-secondary"` — 무채색이라 유일한 유채색 솔리드(활성 칩)를 늘리지 않고 형태로도 갈린다. **이 근거는 D-13에서 일부 약해졌다** — 반경이 갈린 만큼 혼동이 줄었다. 다만 높이·보더·배경이 같고 같은 줄에 놓이므로 강조를 뺄 근거는 아니다(강조 없는 상태를 다시 재보지는 않았다).
- **한 줄에 두 필터 축을 놓으면 간격이 3배는 벌어져야 갈린다.** 칩과 `SelectTrigger`의 셸이 픽셀 단위로 같아 축 사이 `gap-3`·칩 사이 `gap-2`(1.5배)면 Gestalt 임계 아래라 **"한 축 5선택지"로 읽힌다** → `gap-6`.
- **"보여줄 게 없다"는 이유마다 다른 문장과 다른 다음 행동을 가져야 한다.** 특히 **필터가 안 걸렸는데 0건**인 경우를 따로 갈라라 — 걸린 조건이 없으니 "조건에 맞는 작품이 없어요"는 거짓말이고 `필터 해제`는 눌러도 아무 일도 하지 않는다(지연 생성 이후 **모든 신규 창작자의 첫 화면**이다). **부분 실패 배너는 0건 분기에서도 렌더한다** — 목록이 비었다는 early return이 배너보다 앞에 있으면 실패를 감춘 채 "아직 만든 작품이 없어요"라고 말하게 된다.
- **빈 상태 패널의 액션 버튼에 `size="sm"`을 쓰지 말 것** — 패널 한가운데의 32px 버튼은 보조 액션으로 읽히는데 그게 그 화면의 **유일한 앞길**인 경우가 많다. 채움을 올리지 말고(솔리드는 진짜 CTA 자리다) 기본 크기로만 올린다.
- **같은 목적지로 가는 진입점이 한 화면에 둘이면 크기가 아니라 라벨로 가른다** — `size="lg"`는 `default`와 패딩이 같아 폭이 완전히 같아지고(`packages/ui` §호출부), 라벨·역할·목적지까지 같으면 스크린리더에 같은 항목이 **연달아** 읽힌다.
- **dashed 빈 상태 패널 셸은 손으로 복사된 사본이 셋이다**(`ContentListEmptyState`·`MyWorksFullErrorState`·`GeneratedImageLibraryPanel`). 한쪽에 여백·줄바꿈 클래스를 더하면 나머지도 함께 고쳐야 "같은 셸"이라는 주석이 참으로 남는다. **컨테이너 클래스만 맞추고 끝내지 말 것** — 액션 버튼 크기도 갈린다(`GeneratedImageLibraryPanel`은 아직 32px이다).

### 포커스 (WCAG 2.4.3 / 1.4.11)

- **비동기 액션 버튼을 로딩 중에 `disabled`로 막으면 누를 때마다 포커스가 사라진다** — 브라우저가 `disabled`가 붙는 즉시 blur해서 `activeElement`가 `<body>`로 떨어지고, 키보드 사용자는 **한 번 누를 때마다** 헤더부터 Tab을 다시 시작한다. 버튼이 DOM에 남아 있어도 그러므로 "사라져서 그렇다"로 오진하기 쉽다. 처방은 `aria-disabled` + 핸들러 첫 줄 early return이고, `button.tsx`의 흐림은 `disabled:`에만 걸려 있으므로 `aria-disabled:opacity-65`를 함께 준다.
- **자기가 속한 패널을 언마운트시키는 버튼도 같은 결함이다**(빈 상태의 액션). 상태를 바꾸기 **전에** 동기로, 그 분기에서 언마운트되지 않는 컨트롤로 포커스를 옮긴다(라우터 커밋에 기대는 `requestAnimationFrame`을 쓰지 않는다). 목표를 `[data-state=on]`으로 집으면 **바꾸기 전 값**이 잡히므로 곧 켜질 값을 `data-*` 표식으로 지목한다.
- **`overflow-x-auto`는 focus 링을 네 방향 모두 클립한다**(가로만 스크롤해도 세로가 함께 클립된다) — 경계에 붙은 첫/마지막 자식은 3px 링이 통째로 사라진다. 링 두께 이상을 안팎으로 상쇄한다(`-m-1 p-1`).
- **문장 속 인라인 링크의 포커스는 `focus-visible:underline`으로 준다** — 카드용 3px 링 레시피는 라인박스를 깨서 못 쓰고, 전역 base의 1px 아웃라인은 3:1 미달이다. 인라인 링크는 24×24 타깃 요건에서 제외된다(WCAG 2.2 SC 2.5.8 "Inline" 예외).

### 한국어 조판

- **접힐 수 있는 한국어 본문 블록에는 전부 `break-keep`**(없으면 어절 중간이 끊긴다). 어절이 컨테이너보다 길지만 않으면 오버플로를 만들지 않는다(`min-w-0`과 함께).
  - **줄바꿈 결함은 넓은 화면에만 있을 수 있다** — 좁은 폭에서 우연히 문장 경계로 접히는 경우가 많다. 좁은 쪽만 재고 넘어가지 말 것.
  - **"호출부 몫인가 프리미티브 몫인가"는 호출부가 클래스를 얹을 수 있느냐로 갈린다** — children을 받는 자리는 호출부가, **문자열 prop**으로만 들어오는 자리는 프리미티브가 진다. 새 문자열 prop을 만들 때 한 번 물어볼 것.
  - **`break-keep`은 어절 *경계*를 허용한다** — `내 작품`처럼 공백이 든 목적지 이름은 갈리므로 `whitespace-nowrap`을 함께 준다.

### 레이아웃 · 이미지

- **카드 표면 레시피는 `DESIGN.md` §5 Cards가 정한다** — hover 표면이 필요한 클릭 카드는 `bg-card`가 아니라 button-outline 레시피(`bg-background` + `hover:bg-muted`)를 쓰고(`bg-card` 위에서는 hover가 픽셀상 no-op이다), 그 카드 안의 요소는 rest·hover **두 표면 모두에서** 살아남는 토큰이어야 한다. **카드 안에 새 요소를 넣을 때 두 표면에서 각각 확인할 것.** 지금 이 레시피를 쓰는 곳은 `InquiriesPage`·`NoticesPage`·`BuilderTypeSelectPage`·`MyChatRoomListView` 넷이다.
- **⚠️ `ContentCard`는 2026-09-11에 이 레시피에서 빠져나왔다** — 카드에 배경·보더·hover가 없고 border는 **썸네일에만**(`border-foreground/10`) 있으며 hover 신호 자체를 두지 않는다(레퍼런스 둘 다 카드 hover가 없다 — 케이브덕은 픽셀 동일 + hover 클래스 0개, 크랙은 카드 스타일 불변). 그래서 **그 카드 안의 요소에는 "두 표면" 제약이 더는 걸리지 않는다.** 웰이 `bg-secondary`인 이유도 바뀌었다 — hover 표면과의 충돌이 아니라 페이지 배경(0.160) 위에서 보여야 해서다(0.260). 근거: `DESIGN.md` §5 Cards.
- **이미지 로딩 정책**: 기본은 `loading="lazy"` + `decoding="async"`. 예외 둘 — (1) 목록 첫 화면 카드는 `priority` prop으로 `eager`(호출부가 `index < toPriorityCount(aspect)`를 준다 — 그 사다리의 **최대 열 수**다). **손으로 적은 숫자를 쓰지 말 것**: 2026-09-11 에 열 사다리를 바꿨을 때 호출부 4곳의 `index < 4`가 그대로 남아 md 이상에서 **첫 줄 마지막 카드가 lazy 로 빠졌다** — 그래서 값을 `cardLayout.ts` 의 사다리에서 도출하게 바꿨다, 그중 `fetchPriority="high"`는 LCP 후보 **1장**에만(여러 장에 주면 신호가 희석된다), (2) 모달·상세의 주인공 이미지는 이미 뷰포트에 있으므로 `decoding="async"`만.
- **비율을 모르는 원격 이미지는 `max-h-*`로 흘려보내지 말고 `aspect-*` 웰을 먼저 깔고 `object-contain`/`object-cover`로 채운다** — 안 그러면 도착하는 순간 아래 콘텐츠가 밀린다(CLS). 웰 배경은 다크에서 순백이 되면 안 되므로 `bg-muted`.
- **탭은 `variant="line"`**(활성 탭은 `primary`가 아니라 `foreground` 밑줄 — `DESIGN.md` One-Accent Rule).
- **`width` 없는 `absolute` 안의 `grid-cols-N`은 intrinsic 폭이 0으로 붕괴한다** → 명시 `w-*` 필수.
- **인라인 편집 우선** — 리스트 항목 하나를 즉석 수정하는 액션은 모달 대신 항목의 `isEditing` 로컬 state로 스위칭한다(편집 대상 id는 호출부 단일 state).
- **자기완결 위젯** — 트리거 + Sheet/Dropdown 콘텐츠를 위젯이 통째로 소유하고(열림 atom도 내부) 호출부는 컴포넌트 하나만 배치한다.
- **공용 컴포넌트는 로컬 재구현 말고 import한다**(`ContentCard`·`GeneratedImageField` 등).

## 검증 워크플로

- **"리마운트 없이 URL만 바꿨다"는 값이 아니라 포커스로 판정한다.** 입력값이 남아 있는 건 증거가 못 된다 — 리마운트돼도 방금 저장한 값으로 폼이 다시 채워지기 때문이다. `document.activeElement`와 `selectionStart`(캐럿)를 100ms 간격으로 샘플링할 것.
- **브라우저 계측은 스크린샷 픽셀 디코드로만 한다.** `agent-browser eval`의 `getComputedStyle`과 인라인 스타일 쓰기는 신뢰할 수 없다(`!important`를 넣어도 computed가 안 바뀌는 세션이 있었다 — 속성은 붙는데 재계산이 안 온다).
  - **hover는 `hover` 직후 `screenshot`을 연속 3번 찍고 2·3번째를 쓴다**(`wait`를 넣으면 포인터가 떠나 rest 값을 기록한다. 1번째는 전이 중간값이다). `el.matches(":hover")`로 매번 검증할 것.
  - **`opacity`·포커스 링처럼 전이가 걸린 값은 정착 후에 잰다**(`transition-all`이 opacity도 애니메이션해서 직후엔 계속 `1`로 읽힌다 — 이걸로 "클래스가 안 먹는다"고 오진한 적이 있다).
  - **`set viewport` 직후의 rect도 정착 전 값이다**(768px 리사이즈 직후 403.5px → 400ms 뒤 384px). 폭을 바꾼 뒤에는 기다렸다가 잰다.
  - **Radix `enter` 애니메이션이 `t=0`에 고정된 구간에서는 `getBoundingClientRect`가 실제의 0.95배를 준다** — `offsetWidth`로 교차검증한다.
  - **문장에 인라인 자식(`<Link>` 등)이 있으면 `getClientRects().length`가 요소 경계마다 rect를 쪼개 과다 계수한다**(1줄짜리가 5개) — 줄 수는 서로 다른 `top` 값의 개수로 센다.
- **vitest**: UI 컴포넌트가 아니라 **핵심 순수 로직만**, 테스트 파일은 대상 옆 `*.test.ts`(`environment: "node"`, 별도 `vitest.config.ts`). CI는 typecheck → test → build.
- **소비 화면 없는 공용 UI**는 `/ui-demo`에 임시 데모 섹션을 추가해 확인한 뒤 그 페이지 변경분만 원복한다(커밋엔 컴포넌트 + `index.ts` export만 남긴다).
