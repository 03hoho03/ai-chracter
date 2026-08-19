# apps/web

프론트엔드 앱 — FSD 6계층 + TanStack Router + TanStack Query + RHF/zod + Jotai, 디자인시스템은 `packages/ui`. 아래는 **지속 컨벤션과 작업 라우팅**만 담는다. 특정 코드를 만질 때만 필요한 국소 함정·결정은 [`FRONTEND_NOTES.md`](./FRONTEND_NOTES.md) 참고.

## 작업 라우팅 — "무슨 작업 → 무슨 패턴"

| 작업 | 패턴 / 위치 |
|---|---|
| 폼(멀티스텝 포함) | 단일 `useForm` + 단일 zod 스키마, 스텝 검증은 `form.trigger([...])` |
| 서버 상태 | 단일 `apiClient` · `entities/*/api`의 queryKey 팩토리 · `sessionQueryOptions` 재사용 |
| 인증 라우트 가드 | `beforeLoad: requireSession` — 진입에 데이터 필요 시 `loader`/`loaderDeps` |
| 라우트 파라미터/서치 | RouteComponent가 읽어 페이지에 props 주입(routes↔pages 순환 방지) |
| 액션/확인 모달 | react-call 2계열 — 후속 동작이 호출부마다 다르면 `mutationFn` 주입형, 같으면 자체 호출형 |
| 자산 업로드 | `shared/lib/asset/uploadAsset(file, purpose)` 재사용 |
| 브랜드 자산(파비콘·OG 이미지) | `public/`의 파일을 직접 고치지 말고 `brand/generate.sh`로 재생성 (원본·이유는 `brand/README.md`) |
| 서버에서만 할 수 있는 일(봇 메타 주입·sitemap·리다이렉트) | `worker/` — Cloudflare Pages Worker. `dist/_worker.js`로 번들된다 |
| 마운트 시 뮤테이션 | `mutateAsync`+`await`+로컬 로딩 state (StrictMode 콜백 손실 회피) |
| SSE | `shared/lib/sse/openChatStream`의 `kind` 판별유니언에 분기 추가 |
| 오프닝 선택지 노출 | `entities/chat-room`의 `shouldShowSuggestedReplies`(replies·turnCount·hasUserMessage) — 인라인 조건 금지 (ChatRoomView·PreviewSessionView 참조) |
| 발행 | draft PATCH 먼저 → `publish`(무바디), 400은 `missingFields`/`reason` 분기 |
| 테마 | `shared/model/theme.ts`의 `themeAtom`만 write (DOM·스토리지 직접 금지) |

## 아키텍처 / 라우팅

- **FSD 의존 방향**: `app → pages → widgets → features → entities → shared`(역방향 import 금지). 동일 레이어 슬라이스가 코드를 공유해야 하면 그 코드를 `entities`로 내려 각자 하위 의존한다(슬라이스 간 직접 import 금지). `routes/*`는 로직 없이 `pages/{page}`를 렌더링만 하는 얇은 어댑터.
- **내부 import는 `@/` alias**(`@/*` → `src/*`): 레이어를 넘는 import는 `@/entities/...`처럼 alias로, 같은 슬라이스 내부는 상대경로. 정의는 `tsconfig.json` `paths` + `vite.config.ts`·`vitest.config.ts` `resolve.alias` 세 곳이 함께 움직인다. 기존 상대경로는 그 파일을 만질 때 점진 전환.
- **routeTree.gen.ts**: `@tanstack/router-plugin`이 `vite dev`/`vite build` 때 생성하며 git에 커밋한다. 라우트 추가/변경 후 typecheck·커밋 전에 `vite build`(또는 `vite dev` 1회)로 갱신할 것 — `tsc --noEmit`만으론 fresh checkout에서 생성되지 않고, 빼먹으면 새 라우트가 검증에서 누락된다.
- **디자인시스템**: `packages/ui`(shadcn + Tailwind v4). `main.tsx`에서 `@ai-character-chat/ui/globals.css`를 1회 import하면 전체 앱에 토큰/유틸 적용(이 앱은 별도 tailwind.config/전역 css 없음). 컴포넌트는 `@ai-character-chat/ui/components/{name}`. 상세는 `packages/ui/CLAUDE.md`.
- **라우터 컨텍스트**: `createRootRouteWithContext<{ queryClient }>()`로 `app/providers.tsx`의 단일 `queryClient` 인스턴스를 실어 넘긴다(`QueryClientProvider`와 반드시 같은 인스턴스라야 캐시가 맞는다). 인증 라우트는 `beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href)`. 진입 자체에 서버 검증 데이터가 필요하면 `beforeLoad`가 아니라 `loader`/`loaderDeps`를 쓰고, 실제 API 호출은 라우트 파일이 아니라 해당 `features/*`의 순수 async 함수에 둔다.
- **플랫 파일명**은 `.`으로 경로 세그먼트를 구분한다(`routes/onboarding.google.tsx` → `/onboarding/google`). 같은 부모 아래에서 정적 세그먼트가 동적 파라미터보다 우선 매치된다(`builder.$type.new.tsx` vs `builder.$type.$draftId.tsx`).
- **라우트 파라미터/서치**는 `RouteComponent`가 `Route.useParams()`/`Route.useNavigate()`로 읽어 페이지에 **props/콜백으로** 넘긴다. 페이지가 `routes/*`를 import하면 `routes → pages → routes` 순환이 생긴다.
- **전역 Header**는 `widgets/header`, `__root`의 `RootComponent`에 1회 마운트한다(개별 페이지가 헤더를 렌더하지 않음). 로그인 분기는 `useSessionQuery().data` 유무. 로그인 전용 하위 컴포넌트(`ProfileMenu` 등)는 `me`를 props로 받고 세션을 재조회하지 않는다.
- **미구현 화면**은 `shared/ui/ComingSoonPage`(제목/설명 props)로 임시 연결하고, 라우트 파일은 그 스토리의 최종 형태(`beforeLoad: requireSession` 등)로 만들어 나중에 다시 손대지 않게 한다.

## Cloudflare Pages Worker (`worker/`)

- **역할과 위치**: `worker/index.ts`가 esbuild로 `dist/_worker.js`(Pages Advanced Mode)로 번들된다(`build` 스크립트의 `build:worker` 스텝). **서버 코드를 저장소 루트 `functions/`에 두지 말 것** — web·admin Pages 프로젝트가 둘 다 Root directory를 저장소 루트로 두고 있어(pnpm workspace 설치 때문에 필수) admin이 같은 코드를 집어가 SPA 라우팅이 깨진다. `dist/_worker.js`는 web 빌드 출력에만 따라붙는다.
- **`_worker.js`가 있으면 Pages가 모든 요청을 Worker로 보낸다.** `public/_redirects`의 `/* → /index.html 200`은 더 이상 적용되지 않으므로 **SPA 폴백은 Worker가 직접** 한다(`serveAppShell`). `_redirects`는 배포 실패로 `_worker.js`가 누락될 때의 안전망이라 삭제하지 않는다.
- **`env.ASSETS.fetch()`는 존재하지 않는 경로에도 `index.html`을 200으로 돌려준다**(Pages 자산 서버의 SPA 처리). 진짜 404를 만들려면 Worker가 명시적으로 404를 반환해야 한다.
- **런타임 전용 자원은 주입한다**: Cache API는 `WorkerDeps`의 `{ match, put }`(`worker/types.ts`)로만 다루고 진입점(`worker/index.ts`)에서 `createRuntimeCache()`를 넣는다. 핸들러가 `caches.default`를 직접 참조하면 vitest(`environment: "node"`)에서 그 경로 전체가 테스트 불가능해진다. Node 18+에는 `Request`/`Response`/`fetch`가 전역이라 나머지는 핸들러를 그냥 함수로 호출해 테스트한다(`worker/handler.test.ts`).
- **`API_BASE_URL`은 Pages 런타임 환경변수**다 — 빌드타임 `VITE_API_BASE_URL`과 별개로 대시보드에 넣어야 한다. 없으면 Worker가 SEO 경로를 통째로 건너뛰고 정적 자산만 서빙한다(환경변수 하나가 사이트를 죽이지 않도록).
- **봇에게 내려보내는 HTML은 한 경로로만 만든다**: `worker/meta.ts`의 `buildMetaTags(PageMeta)` → `worker/html.ts`의 `injectHead(indexHtml, metaHtml)`. 사용자 입력(캐릭터 이름·소개·닉네임·bio)은 예외 없이 `escapeHtml`을 **정확히 한 번** 통과한다 — 텍스트/속성 컨텍스트를 분기하지 말 것(분기가 곧 누락 지점이고, 두 번 적용하면 `&`가 `&amp;amp;`로 이중 이스케이프된다). `injectHead`는 **주입하는 태그와 같은 키(title·name:*·property:*·canonical)의 기존 태그를 지운 뒤** `</head>` 앞에 넣으므로, index.html에 박아 둔 홈 기본 og와 상세 페이지 주입이 중복되지 않는다(크롤러 대부분이 중복 og 속성에서 앞의 것을 쓴다). JSON-LD는 `buildJsonLd`로만 만든다(`<`를 전부 이스케이프해 `</script>` 탈출을 막는다).
- **봇 판별은 `worker/crawler.ts`의 `isCrawler(userAgent)`** — UA 토큰 목록 `includes` 검사다. 크롤러를 추가할 일이 생기면 이 목록 한 곳만 고친다.
- **브라우저 검증은 vite dev가 아니라** `pnpm --filter @ai-character-chat/web build && pnpm --filter @ai-character-chat/web dev:worker`(= `wrangler pages dev dist`) — Worker는 빌드 산출물이라 vite dev 서버에는 없다. 로컬 API(:8000)의 `CORS_ALLOW_ORIGINS`가 `localhost:5173`/`5174`뿐이므로 `--port 5174`로 띄우고, 그 빌드는 `VITE_API_BASE_URL=http://localhost:8000`으로 만든다.

## 데이터 / 상태

- **단일 apiClient**: 모든 API는 `shared/lib/api/client.ts`의 `apiClient`(직접 `axios.create` 금지). 인증은 httpOnly 세션 쿠키 + `withCredentials`(요청 인터셉터에서 토큰 안 붙임). 응답 인터셉터가 모든 에러를 `@ai-character-chat/api-types`의 `ApiError`로 정규화한다. `ApiError`는 FastAPI의 `{detail}` 형태 — string이면 메시지, dict면 구조값(예: 429의 `retryAfterSeconds`), 422 배열이면 `fields`로 필드명→메시지. 서버 `detail`(영어 디버그 메시지)을 그대로 노출하지 말고 `apiError.status`로 분기해 한국어 카피.
- **세션**: `entities/session`의 `sessionQueryOptions`(`queryOptions()`) 하나를 `useSessionQuery`(`useQuery`)와 `requireSession`(`ensureQueryData`)이 공유한다(쿼리키/함수/staleTime/retry가 어긋나면 캐시 분열). 세션 변경 뮤테이션은 `sessionKeys.current()` invalidate만 하고 세션 갱신을 직접 구현하지 않는다. 단, 마운트된 모든 컴포넌트가 세션 소실을 **즉시** 반영해야 하면(로그아웃) `invalidateQueries`(리페치까지 옛 값 유지)나 `setQueryData(key, undefined)`(문서화된 no-op) 대신 **`resetQueries`**.
- **인증 데이터는 shared/session에**: 토큰·로그인 응답 DTO 등 인증 과정에서만 쓰는 데이터로 별도 user entity를 만들지 않는다(의존성 순환 유발).
- **자산**: 업로드는 `shared/lib/asset/uploadAsset(file, purpose)` 재사용(presigned 발급 → S3 직접 PUT은 `fetch`(외부 절대 URL이라 `apiClient` 아님) → complete). `uploadAsset`은 PUT 전에 purpose별 규격으로 `resizeImage`를 돌리므로 올라가는 건 언제나 `image/webp`이고, 실패는 `UploadAssetError.code`(`FILE_TOO_LARGE`/`DECODE_FAILED`/`ENCODE_FAILED`/`SIZE_LIMIT_EXCEEDED`/`UPLOAD_FAILED`) 하나로 갈린다 — 호출부는 카피를 직접 쓰지 말고 `shared/lib/asset/uploadAssetErrorMessage(error)`를 `toast.error(...)`에 그대로 넘긴다(분류 못 한 `ApiError` 등은 일반 문구로 폴백). 업로드 `<input>`의 `accept`는 `image/png,image/jpeg,image/webp` — 결과가 WebP로 재인코딩되므로 그 밖의 형식은 받지 않는다. 새 purpose를 추가하면 `RESIZE_SPEC_BY_PURPOSE`/`MAX_UPLOAD_BYTES_BY_PURPOSE`(후자는 서버 `UPLOAD_SIZE_LIMIT_BYTES`와 같은 값)도 함께 채워야 한다. presigned GET URL은 매 조회 새로 서명되므로 **캐시 금지** — 응답에 presigned URL이 박혀 있는 쿼리는 `gcTime: 0`으로 둔다(기본 5분이면 모달을 다시 열 때 직전 스냅샷이 먼저 페인트돼, 그새 바뀐 서버 상태가 옛 값으로 잠깐 보인다).
- **retry**: 기본 3회 지수백오프는 4xx엔 무의미 → `retry: (n, e) => (e.status === 0 || e.status >= 500) && n < 3`. 결과 `status`로 에러 화면을 분기하는 쿼리는 이 패턴 재사용(전역 기본값은 아직 없음).
- **무한스크롤**: `shared/lib/infinite-scroll/useInfiniteScrollSentinel` + `useInfiniteQuery`. 정렬/필터로 queryKey가 바뀌면 그 자체로 새 쿼리라 `isPending`이 다시 true — 별도 로딩 state 없이 스켈레톤 재사용.
- **잡 상태 폴링**(비동기 생성 등): `useXQuery(id, enabled)` 훅에 `refetchInterval: (query) => isTerminal(query.state.data?.status) ? false : intervalMs` 함수형을 준다 — 완료(성공/실패) 상태에 도달하면 자동으로 멈춘다(고정 `refetchInterval` 숫자는 영구 폴링이 되어 부적합). `entities/image-job/api/useImageJobStatusQuery.ts` 참고.
- **navigate search**: 여러 서치 파라미터를 독립 관리하는 라우트에서 `navigate({ search: {...} })` 객체 리터럴은 다른 필드를 날린다 → 항상 함수형 업데이터 `search: (prev) => ({ ...prev, ... })`.
- **낙관적 토글**: 캐시 `onMutate` 대신 로컬 override state로 화면에 즉시 반영 + `react-use`의 `useDebounce`로 네트워크만 지연 + `onSettled` 조건부 리셋(실패 시 override 제거로 자동 롤백). `setState`는 항상 함수형 업데이터 `(cur) => !(cur ?? base)` — 렌더 클로저 값을 캡처하면 배칭 시 스테일.
- **마운트 시 뮤테이션**: `useEffect`에서 `.mutate(vars, { onSuccess })`에 의존하면 StrictMode(dev)의 마운트→언마운트→재마운트가 `MutationObserver`를 영구 제거해 콜백·반응형 `isPending`/`data`가 그 순간 값에 멈춘다 → **`mutateAsync`+`await`로 결과를 받고 로딩은 로컬 state**로 판단한다. 캐시 채우기 등 "결과와 무관하게 항상 일어나야 할" 부수효과는 훅 정의의 `onSuccess`에 둔다(Observer 구독과 무관하게 항상 실행). 세션이 비동기 로드되는 상황의 마운트 로직은 `useEffectOnce`가 아니라 `useEffect(..., [isPending, data])` + `useRef` 가드로 "정확히 한 번".
- **1회성 배너**: 뮤테이션 성공 즉시 꺼지는 서버 플래그(`versionAutoUpgraded` 등)를 렌더 조건으로 직접 쓰면 뜨자마자 사라진다 → "봤다"는 로컬 state로 분리해서 판단.
- **SSE**: `shared/lib/sse/openChatStream`(fetch 기반, `credentials: "include"`, `kind` 판별유니언). 새 SSE 액션은 이 함수의 분기만 늘린다. 스트리밍 중 텍스트는 로컬 버퍼로 두고(Query 캐시와 이중상태 금지) 종료 시 비운다. `entities`는 `shared`를 import 못 하므로(FSD) 대응 요청 타입은 명목상 별개지만 구조적으로 호환되게 유지.
- **순수 함수 캐시 조작**: `applyStreamEvent` 등은 훅이 아니라 `QueryClient`를 인자로 받는 순수 함수 → `new QueryClient()` + `setQueryData`/`getQueryData`만으로 테스트.
- **rule-engine SSOT**: `shared/lib/rule-engine`(타입 + `evaluateRuleList`). `entities/chat-room` 등은 로컬 재정의 대신 `export type {...} from`. `noUncheckedIndexedAccess` 때문에 배열은 인덱싱 대신 구조분해 + `for...of`.
- **테마**: `shared/model/theme.ts`의 `themeAtom` 하나만 write(이 atom이 localStorage 저장 + `<html>` dark 클래스 토글까지 책임). 초기값 규칙("light" 저장값일 때만 라이트, 그 외 다크)은 `index.html`의 FOUC 방지 인라인 스크립트와 **반드시 동일** 유지.

## 폼 / 빌더

- **멀티스텝 폼**: 스텝마다 별도 `useForm`을 두지 않고 **단일 `useForm` + 단일 zod 스키마**를 전체 스텝이 공유한다. 스텝별 검증은 `form.trigger(['필드'])`(도달 안 한 다음 스텝의 필수 필드가 현재 제출을 막지 않음). `handleSubmit`은 전체 검증이라 스텝 제출엔 쓰지 않는다. 위저드마다 `useForm`·스텝 atom은 새로 만든다(모듈 전역 싱글턴 atom 공유 시 라우트 간 상태 누수).
- **shadcn Checkbox**는 Radix `checked`/`onCheckedChange`라 `register()`로 못 묶는다 → `Controller`(단일 필드) 또는 `watch`/`setValue`(여러 필드 동시).
- **shadcn Select로 숫자 필드를 다룰 땐 `z.coerce.number()`를 쓰지 말 것** — Select value는 항상 string이라 `Controller`의 `onValueChange={(v) => field.onChange(Number(v))}`로 이미 number로 변환해서 RHF에 넣는데, `z.coerce.number()`는 스키마의 input 타입을 `unknown`으로 만들어(출력은 number) `zodResolver`의 input/output 타입이 어긋나 타입에러가 난다(`features/generate-images/model/schema.ts`의 `count` 필드에서 발견). 이미 number로 변환해서 넣는 필드는 그냥 `z.number()`를 쓸 것 — `z.coerce`는 `<input>` 같은 항상 string인 네이티브 컨트롤에서만 필요하다.
- **formToServer/serverToForm 경계**: draft 상태를 표현해야 하는 필수 선택 필드는 `.nullable()`(`z.enum`은 "미선택" 멤버가 없어 서버 `null`을 담을 수 없음). 배열 `order`는 배열 위치 자체(명시 숫자 필드 만들지 말 것). **실제 필드명은 techspec 코드블록이 아니라 `packages/api-types/src/generated.ts`에서 확인**(techspec의 `worldSetting`이 실제 `settingText`인 사례 등) — rename은 이 경계 함수가 전담.
- **자동저장**: `features/build-common`의 `useAutosave`(`subscribe`/`formToServer`/`save`/`debounceMs`). 각 빌더는 자기 `formToServer`만 주입하고 디바운스/즉시저장을 재구현하지 않는다.
- **발행 가능 여부**는 `formState.isValid`/개별 `trigger()`가 아니라 `builderSchema.safeParse(useWatch({ control }))`로 판단(미구현 탭 필수 필드가 자연스럽게 발행 버튼을 비활성 유지).
- **useFieldArray**: 순서 없는 배열(add/remove만)은 `fields.map`(`key={field.id}`) + `append({ id: crypto.randomUUID() })`. 순서=우선순위면 `@dnd-kit/sortable` + `move(from, to)`(listeners는 드래그 핸들에만). 부모의 동적 인덱스에 `name`이 의존하는 중첩 `useFieldArray`는 부모 안정 `id`로 `key`를 줘 통째로 remount(인덱스로 key 금지). discriminated union 재귀 트리 배열은 `useFieldArray` 대신 `items`/`onChange` 순수 제어 컴포넌트로 재귀.
- **컴포넌트 선택**: `switch`(즉시 on/off) vs `Toggle`(눌림 상태 버튼) vs `Checkbox`(폼 체크) — 의미가 다르다.
- **발행**: `publish`는 무바디라 서버에 저장된 초안을 발행한다 → 반드시 `schema.parse()` → `formToServer()` → **draft PATCH 저장** → `publish()` 순서(중간 debounce 미반영 값 누락 방지). 400 `detail`은 `{missingFields}`(필수 누락, 토스트)와 `{reason}`(자동 필터 거부, 이의제기 배너) 두 모양 — `"reason" in detail`로 먼저 판별. nullable draft 스키마는 `safeParse` 통과해도 서버 필수값이 빌 수 있어 `missingFields`→한국어 라벨 매핑으로 안내.

## UI / 컴포넌트

- **react-call 모달 2계열**: 성공 후 동작이 호출부마다 갈리면 `mutationFn` **주입형**(`ReportContentModal` — 컴포넌트는 입력 UI만), 항상 같으면 **자체 mutation 호출형**(`UpdateInfoModal`/`AppealModal`). 입력 없는 확인/취소는 공용 모달(`ConfirmChatRoomActionModal`) 재사용. Callable은 `routes/__root.tsx`에 1회 마운트, `open={!call.ended}` + `onOpenChange={(o) => !o && call.end()}`.
- **인라인 편집 우선**: 리스트 항목 하나를 즉석 수정하는 액션은 모달 대신 항목 컴포넌트의 `isEditing` 로컬 state로 표시/편집 모드 스위칭(편집 대상 id는 호출부 단일 state).
- **클릭 카드**: 카드 전체가 클릭 영역인데 안에 다른 동작의 클릭 요소를 넣어야 하면 바깥을 `role="button"` `div`(`tabIndex=0` + Enter/Space `onKeyDown`)로 바꾼다(`<button>` 중첩은 무효 HTML). 공용 `entities/content/ui/ContentCard`가 이 패턴.
- **자동완성 드롭다운**: `packages/ui`에 Popover/Command 없이 `relative` 래퍼 + 조건부 `absolute` div로 충분(배경은 `bg-popover ... ring-1 ring-foreground/10` 재사용). 스크롤 컨테이너 **안**이면 `fixed`/포털 필요.
- **클릭 칩**: 새 컴포넌트 대신 `Button` `variant="secondary" size="sm" className="rounded-full"`(hover/focus/disabled 공짜). 비클릭 뱃지와 혼동 금지.
- **자기완결 위젯**: 트리거 + Sheet/Dropdown 콘텐츠를 위젯이 통째로 소유(열림 atom도 위젯 내부), 호출부는 컴포넌트 하나만 배치.
- **뷰포트에 따라 Sheet ↔ 인라인 패널을 갈라야 하면 CSS가 아니라 JS로 분기한다**(`react-use`의 `useMedia`). `Sheet`/`Dialog`는 body로 포털되므로 부모의 `lg:hidden`이 닿지 않고, 열린 Sheet는 포커스 트랩 + 바깥 클릭 차단까지 걸어 인라인 패널과 공존할 수 없다 — 둘 중 하나만 마운트되어야 한다. 브레이크포인트는 두 분기가 공유하는 훅 한 곳에 두고(`widgets/chat-room/lib/useIsChatMoreSidebarLayout.ts`), 항목 목록·핸들러는 별도 컴포넌트로 뽑아 양쪽이 같은 것을 쓰게 한다.
- **탭**: shadcn `tabs` `variant="line"`(DESIGN.md Flat-at-Rest / One Accent Rule — 활성 탭은 `primary`가 아니라 `foreground` 밑줄).
- **absolute + grid-cols**: `width` 없는 `absolute` 안의 `grid-cols-N`(=`minmax(0, 1fr)`)은 intrinsic 폭이 0으로 붕괴한다 → 명시 `w-*` 필수.
- **공용 컴포넌트 재사용**: `ContentCard`·`GeneratedImageField` 등은 로컬 재구현 말고 import.
- **이미지 로딩 정책**: `<img>`의 기본값은 `loading="lazy"` + `decoding="async"`다. 예외는 두 갈래 — (1) 목록 첫 화면 카드는 `priority` prop으로 `loading="eager"`(공용 `ContentCard`와 프로필 로컬 카드가 받는다. 호출부가 `index < 4`를 준다: 그리드가 `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라 첫 줄이 뷰포트에 따라 2/3/4장으로 갈리므로 최대값 기준), 그중 `fetchPriority="high"`는 LCP 후보 **1장**(`index === 0`)에만 준다(여러 장에 주면 우선순위 신호가 희석된다). (2) 모달·상세 뷰의 주인공 이미지는 열리는 순간 이미 뷰포트에 있어 lazy가 이득이 없으므로 `decoding="async"`만 준다. **비율을 모르는 원격 이미지**(채팅 인라인 이미지, 콘텐츠 썸네일)는 `max-h-*`로 흘려보내지 말고 `aspect-*` 웰(`bg-muted`)을 먼저 깔고 그 안에서 `object-contain`/`object-cover`로 채운다 — 그렇지 않으면 이미지가 도착하는 순간 아래 콘텐츠가 밀린다(CLS). 웰 배경은 다크에서 순백이 되면 안 되므로 `bg-muted`를 쓴다.

## 검증 워크플로

- **vitest**: UI 컴포넌트가 아니라 **핵심 순수 로직만**, 테스트 파일은 대상 옆 `*.test.ts`(`environment: "node"`, 별도 `vitest.config.ts`). CI는 typecheck → test → build.
- **소비 화면 없는 공용 UI**는 `/ui-demo`에 임시 데모 섹션을 추가해 확인한 뒤 그 페이지 변경분만 원복한다(커밋엔 컴포넌트 + `index.ts` export만 남김).
