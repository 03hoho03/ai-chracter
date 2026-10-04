# apps/admin

관리자 전용 **별도 배포 앱**. `apps/web`과 동일 스택(Vite/React/TanStack Router+Query/Jotai, `packages/ui`)이다.

**이 문서는 `apps/web`과 다른 점만 담는다.** 같은 것(FSD 의존 방향, `@/` alias, 라우터 컨텍스트, `apiClient`·쿼리키 규약, 폼, 검증 워크플로)은 [`apps/web/CLAUDE.md`](../web/CLAUDE.md)를 보고, 프리미티브는 `packages/ui/CLAUDE.md`, 비주얼 규범은 `DESIGN.md`다.

## web과 다른 점

| | apps/web | apps/admin |
|---|---|---|
| 테마 | 다크 기본 + 토글 | **라이트 고정** — `.dark`를 절대 붙이지 않는다 |
| dev 포트 | 5173 | **5174**(`vite.config.ts`의 `server.port`, 동시 기동용) |
| FSD 레이어 | 빈 레이어를 `.gitkeep`으로 미리 만든다 | **실제로 여러 화면이 공유할 때만 추가한다** |
| 서버 렌더 보조 | `worker/`(봇 메타·sitemap) | **없다** — `_worker.js`가 없는 정적 SPA다 |
| 색인 | Worker가 `robots.txt`를 만든다 | `public/robots.txt`로 **전면 차단**(`Disallow: /`) |
| 인증 | 세션 쿠키 + 구글 로그인 | 같은 모양, **다른 엔드포인트**(아래) |

- **라이트 고정이라 다크에서만 드러나는 문제를 여기서는 못 본다.** 반대로 `packages/ui`를 고칠 때 다크만 확인하면 admin이 깨진다.
- **`_worker.js`가 없어서 host 조건을 걸 자리가 없다** — 옛 `*.pages.dev` 주소를 새 도메인으로 넘기지 못하고(`_redirects`는 경로만 본다), `SameSite=lax` 쿠키라 거기서는 로그인도 안 된다. 의도된 결과이며 `admin.ddona.site`를 쓴다(`DEPLOY.md` "스택" 절).
- **색인 차단은 web과 완전히 무관하다** — 별도 Pages 프로젝트라 web의 `robots.txt`(Worker 생성)를 고쳐도 admin에는 아무 영향이 없다. 등록 정책은 `DEPLOY.md` "admin 색인 차단" 절.

## 인증

- **`shared/lib/api/client.ts`·`entities/session`·`features/login`·`features/logout`은 web 동형 구현의 복제다** — 쿼리 옵션 공유, `resetQueries`로 즉시 로그아웃 반영, `beforeLoad: requireSession` 가드까지 모양이 같으니 **그 규약은 `apps/web/CLAUDE.md`를 먼저 볼 것.**
- 다른 것은 **엔드포인트와 목록 기억 비우기**다: `POST /admin/auth/login` · `GET /admin/me` · `POST /admin/auth/logout`, 그리고 로그인·로그아웃 성공 시 목록 상태 기억(아래 프리미티브 절)을 비운다 — 로그아웃이 새로고침 없는 이동이라 같은 탭의 다음 관리자에게 앞 사람의 검색어가 남는다. 서버 쪽도 쿠키 이름(`admin_session_id`)과 Redis 프리픽스가 완전히 분리돼 있어 교차 인증이 구조적으로 불가능하다.
- **web에 있는데 가져오지 않은 것 둘**: 구글 로그인 · 비밀번호 표시 토글(내부 발급 계정이라 소셜 로그인이 없다).
- 새 보호 라우트는 `beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href)` 한 줄만 추가하면 된다.

## 라우팅

- **새 화면을 추가하면 `widgets/admin-shell/config/nav.ts`의 `ADMIN_NAV_GROUPS`에서 맞는 그룹(개요·검토 큐·콘텐츠·유저·서비스 설정)에 항목(`label`·`to`·lucide `icon`)을 더해야 한다** — 안 하면 라우트는 있어도 **내비로는 도달할 수 없다**. 그룹 배열 전체가 `as const`라 각 `to`가 리터럴로 좁혀져 라우터가 만든 경로 유니온과 대조되므로 없는 라우트는 타입 에러로 걸리는데, **에러는 `config/nav.ts`가 아니라 `ui/AdminNavList.tsx`(`Link`를 그리는 곳)에 뜬다**(`AdminNavItem` 타입이 이 목록에서 도출된 것이라 제약을 걸지 않는다). 사이드바·모바일 드로어·상단바 화면명이 모두 이 목록 하나를 쓴다.
- **현재 화면 표시(`aria-current`)는 `lib/resolveActiveNavTo.ts` 하나가 정한다** — `/`는 정확히 일치할 때만, 나머지는 하위 경로까지 접두 일치(가장 긴 것). 내비 `Link`는 `activeOptions={{ exact: true, includeSearch: false }}`로 자기 판정을 좁혀 둔다: `Link`는 자기 판정의 `aria-current`를 props 맨 끝에 덮어써서, 기본(접두 일치)으로 두면 판정 함수와 다른 항목이 함께 현재가 될 수 있다.
- **셸(`widgets/admin-shell`의 `AdminShell`)은 `routes/__root.tsx`가 마운트해 로그인 화면을 제외한 모든 라우트를 감싼다.** `/login`이 세션 없는 유일한 비보호 라우트라 `pathname === "/login"`으로 분기한다(pathless layout route를 쓰지 않은 이유는 라우트 파일 5개를 옮기고 레이아웃 파일을 새로 만들어야 해서다). `lg` 이상은 접을 수 있는 사이드바(펼침 224px / 아이콘 레일 64px, 접힘은 이 브라우저의 `localStorage`), 미만은 sticky `h-14` 상단바 + 좌측 드로어이고 둘은 CSS(`lg:`)로만 갈린다. **스크롤 컨테이너는 window 하나다** — 셸이나 본문 래퍼에 `overflow-*`를 걸면 상단바·사이드바의 sticky가 죽는다. 본문 래퍼가 문서의 유일한 `<main id="main-content">`(건너뛰기 링크의 목표)이다 — 화면은 `<main>`을 따로 두지 않고 `PageContainer`(div)로 폭·거터만 정한다.
- **목록과 그 상세를 형제 화면으로 두려면 목록 쪽을 `.index.tsx`로 명명한다.** `reports.tsx`(실제 경로를 가진 라우트) 옆에 `reports.$reportId.tsx`를 두면 TanStack Router가 상세를 **`reports`의 자식으로 중첩**시키고, 부모에 `<Outlet/>`이 없으면 **URL만 바뀌고 화면은 그대로 부모가 보인다**(콘솔 에러 없는 조용한 실패). `reports.index.tsx`로 두면 `reports`가 암묵적 pathless 레이아웃이 되어 둘이 형제로 분리된다 — 지금 `contents`·`users`·`reports` 셋 다 이 모양이다.
  - `apps/web`의 `builder.$type.*`가 이 함정에 안 걸리는 건 `builder.$type.tsx` 파일 자체가 없어 공유 프리픽스가 처음부터 암묵적 레이아웃이기 때문이다.
  - **라우트 파일을 rename한 직후 `routeTree.gen.ts`가 깨진 채(참조 없는 심볼이 남은 채) 재생성되는 경우가 있다** — dev 서버를 죽이고 `routeTree.gen.ts`를 지운 뒤 `vite build`로 처음부터 다시 만든다.

## UI

- **`react-call`(확인 모달)·`sonner`(토스트)는 web과 같은 관례다** — Callable은 `routes/__root.tsx`에 1회 마운트하고 `<Toaster />`는 `main.tsx`에 둔다. **두 의존성은 admin `package.json`에 직접 넣어야 한다**(pnpm 워크스페이스가 간접 의존성을 안 끌어온다).
- **Callable은 `@/shared/lib/callable/createCallable`로만 만든다** — 모달이 닫힌 뒤 연 버튼으로 포커스를 돌려주는 래퍼다(web 래퍼의 사본 — 앱끼리 import할 수 없다). `react-call`에서 직접 만들면 포커스가 `<body>`로 떨어지고, eslint `no-restricted-imports`가 막는다.
- **확인 모달의 첫 포커스는 `취소` 버튼이다**(`취소`에 `autoFocus`) — 무심코 Enter를 눌러도 아무 일도 일어나지 않게. 예외는 대상 이름을 다시 쳐야 확정되는 삭제 모달뿐이고 그 이름 확인칸이 첫 포커스다. 필수 칸(사유·수량)이 있어도 첫 포커스는 `취소`다.
  - **하단 조치 시트 안에서 열릴 수 있는 모달은 첫 포커스 대상에 `data-initial-focus`를 함께 달고 `DialogContent`에 `onOpenAutoFocus={focusInitialElement}`(`shared/lib/callable/focusInitialElement`)를 준다.** `autoFocus`만 두면 모달이 자리 잡기 전에 시트의 포커스 트랩이 포커스를 되돌려 첫 포커스가 닫기 X로 빗나간다(실측).
- **손가락 포인터에서 컨트롤을 40px로 올리는 규칙은 admin 전용 CSS `app/styles/admin.css`에 있다**(`packages/ui`에 넣으면 web까지 바뀐다). 프리미티브의 `data-slot`으로 걸고, 버튼만 Button의 기반 클래스로 건다 — Radix 트리거·닫기를 `asChild`로 씌우면 바깥 `data-slot`이 Button 것을 덮기 때문이다. 프리미티브가 아닌 손수 만든 행(내비 행 등)은 그 클래스에 `pointer-coarse:min-h-10`을 직접 둔다.
- **되돌릴 수 없는 삭제는 이름 완전 일치로 확인받는다** — `features/act-on-report/ui/DeleteConfirmModal.tsx`(`{contentName, mutationFn}`, 입력값이 `contentName`과 정확히 같아야 확정 버튼 활성화). 도메인이 다르면 새 컴포넌트로 만들되 이 검증 패턴을 재사용한다.
- **목록 항목에 상세 정보가 이미 다 들어 있으면 별도 라우트로 분리하지 말고 한 페이지 안에서 로컬 `useState`로 렌더한다**(`pages/appeals`가 그 사례 — 선택된 id로 `items.find(...)`). 별도 상세 쿼리도 라우트도 필요 없고, 필터·페이지가 바뀌어 선택된 id가 목록에서 사라지면 상세 섹션도 자연히 사라진다(정리 코드 불필요). **실제 detail 엔드포인트가 생기면** 그때 `reports` 패턴(형제 라우트 + 상세 쿼리)으로 옮긴다.

## 공용 화면 프리미티브 (`shared/ui`)

목록 7종(작품·유저·신고·이의제기·이미지 생성·문의·공지)과 상세 전부(신고 3종·작품·유저·문의·공지·유저 채팅·유저 생성 이미지)는 옮겼다. 대시보드·사용량·약관·프롬프트도 바깥 틀은 `PageContainer`다. 조치가 없거나 폼이 본문인 상세(문의 답변·공지 편집·열람 화면)는 `DetailLayout actions={null}`로 본문 열 폭만 받는다.

- **`PageContainer` + `PageHeader`** — 폭·거터의 단일 소스(`max-w-6xl`, `px-4 sm:px-6`)와 늘 줄바꿈되는 화면 머리. 머리는 쿼리 밖에 둬 로딩·오류에도 남긴다.
- **`FilterBar` + `selectFilter`·`dateRangeFilter`** — 필터 상태는 지금처럼 라우트 URL search 에 두고 콜백만 넘긴다. 셀렉트 값은 `selectFilter`가 옵션에서 다시 찾아 좁히므로 호출부에 술어·`as`가 필요 없다(불리언 search 는 호출부가 문자열 옵션과 오가며 바꾼다). 기간은 `dateRangeFilter`로, 바뀐 끝(`from`/`to`)만 담아 부른다. 자기 폭 672px(`@2xl`) 미만에서 필터 시트 + 해제 칩이 된다. 표 전체를 바꾸는 축(신고 대상)은 필터가 아니라 필터 바 밖에 둔다.
- **`DataList`** — 목록 행은 행 전체를 덮는 `Link` 하나다(`renderRowTarget`으로 타입 안전한 `Link`에 받은 props를 넘긴다). `tr role="button"`·셀 버튼으로 되돌리지 않는다 — 새 탭·접근 이름이 깨진다. 상세 라우트가 없는 목록(이의제기)만 그 자리에 고르는 버튼(`aria-current`)을 두고 `isRowSelected`를 넘긴다 — 고른 행의 채움·체크 글리프는 `DataList`가 그린다(호출부에 선택 클래스를 두지 않는다). 표에서는 행 대상 칸(이름·제목)만 줄바꿈하고 나머지 칸은 한 줄이다 — 사용자가 쓴 긴 제목이 상태·날짜 칸을 화면 밖으로 밀지 않게. 숫자를 가로로 비교하는 밀집 표는 카드 행 대신 `DenseTable`(첫 열 고정, 첫 열은 8~12rem 안에서 줄바꿈)로 감싼다.
- **목록 상태 기억** — 목록 라우트 컴포넌트가 `useRememberListSearch(라우트 id, Route.useSearch())`로 마지막 search 를 jotai 메모리에 적고, 상세의 "목록으로"는 `useRememberedListSearch`로 읽어 `search`에 싣는다(없으면 `{}` — 기본 목록). 대시보드·다른 상세 같은 입구로 들어와도 돌아가는 목록이 같고, 새로고침하면 빈다. 새 목록·상세를 더하면 `shared/lib/list-search-memory`의 `ListRouteId`에도 더한다. 내비·대시보드 카드처럼 늘 같은 목록을 여는 링크에는 싣지 않는다.
- **`QueryState`** — 로딩·오류(+ "다시 시도")·빈 상태를 한 모양으로. `card`·`popover` 위면 `surface="card"`(스켈레톤이 `secondary`). 페이지를 넘기는 목록은 `getPage={(data) => data}`를 넘긴다 — 기억된·뒤로 간 페이지가 끝을 넘어 비어 오면 빈 상태 대신 마지막 페이지로 URL 을 바꿔치기한다(search 키 `page`).
- **`DetailLayout`** — 상세의 조치는 `actions`로 넘긴다(`lg` 이상 sticky 열, 미만 하단 바 → 바텀시트). **"조치 없음" 판정은 호출부가 해 `null`을 넘긴다**(패널 안에서 `return null` 하지 않는다). 패널은 `render(host)` 안에서 한 번만 마운트되고, 성공하면(확인 모달이 있으면 모달이 닫힌 뒤) `host.onDone`을 부른다. 본문 열은 `@container`라 **그 안의 그리드·패딩은 뷰포트 `sm:`/`md:`가 아니라 `@xl:` 같은 컨테이너 쿼리로 가른다**(조치 열·사이드바에 따라 폭이 바뀐다).
- **`UnsavedChangesGuard`** — 편집 화면(약관·공지·프롬프트)에 `isDirty` 하나로 둔다(화면당 하나 — 둘이면 확인이 두 번 뜬다). 변경이 있는 동안에만 라우터 차단과 새로고침 확인(`beforeunload`)이 걸리고, 다른 화면으로 갈 때만 막는다. `isDirty` 는 저장·게시 직후 거짓이어야 하고, 저장 직후 같은 처리 안에서 이동하는 곳은 그 이동에 `ignoreBlocker: true` 를 준다(화면이 아직 "변경 있음"으로 그려져 있다).
- **탭 제목은 `shared/lib/useDocumentTitle(화면명, 대상 이름?)`** — `{화면명} · 또나 어드민`, 상세는 불러온 뒤 `{대상 이름} · {화면명} · 또나 어드민`. 화면마다 한 번만 부르고(둘이면 나중 것이 이긴다), 상세는 쿼리를 가진 본문 컴포넌트가 부른다. 라우트 `head` 를 쓰지 않는 이유는 상세에 loader 가 없어 대상 이름을 모르기 때문이다. 열람 사유를 받는 화면(채팅·생성 이미지)은 방·유저 이름이 브라우저 기록에 남지 않게 화면명만 둔다. 화면명은 내비 라벨·h1 과 같은 말이다.
- **`ActionChoice`** — 처리 방법 고르기는 이 세로 라디오 목록 하나로 한다(가로 토글 그룹에 `flex-1`을 주면 좁은 폭에서 글자가 겹친다). 되돌릴 수 없는 처리는 `tone: "destructive"`.

## 빠른 이동 팔레트·단축키

- **팔레트는 `widgets/admin-shell/ui/CommandPalette`**(`shared/ui/Command` = cmdk 위의 shadcn `Command`, 공용 `Dialog` 안). 항목: 내비 11개(`ADMIN_NAV_GROUPS` 그대로 — 새 화면은 내비에 더하면 팔레트에도 나온다), 붙여 넣은 UUID 의 작품·유저 상세 두 후보, 그 밖의 글자는 유저 목록 `?q=`(이메일·닉네임 일부 일치). 검색어 필터는 cmdk 가 아니라 호출부가 한다(`shouldFilter={false}`).
- **모든 이동은 라우터로** — 편집 화면의 이탈 확인이 그대로 걸린다. Esc·바깥 누르기로 닫으면 연 자리로, 항목으로 이동하면 `#main-content` 로 포커스가 간다(이탈 확인이 떴으면 빼앗지 않는다).
- **여는 자리**: `lg` 미만 상단바 돋보기, `lg` 이상 사이드바 머리 아래 "빠른 이동" 버튼, ⌘K / 컨트롤+K.
- **단축키는 둘뿐이다**(`model/useAdminShortcuts`): ⌘K·컨트롤+K(입력칸 안에서도, 다른 대화상자가 열려 있으면 무시)와 `/`(지금 화면의 `[data-filter-search]` 로 포커스). `/` 는 input·textarea·select·contenteditable·콤보박스·목록·차트 안이거나 대화상자·시트가 열려 있으면 아무것도 하지 않아 글자로 들어간다. 한글 조합 중 키는 무시한다. 단축키를 더하면 팔레트 바닥의 목록도 고친다.
