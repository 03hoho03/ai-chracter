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
- **`_worker.js`가 없어서 host 조건을 걸 자리가 없다** — 옛 `*.pages.dev` 주소를 새 도메인으로 넘기지 못하고(`_redirects`는 경로만 본다), `SameSite=lax` 쿠키라 거기서는 로그인도 안 된다. 의도된 결과이며 `admin.ddona.site`를 쓴다(`DEPLOY.md` §0).
- **색인 차단은 web과 완전히 무관하다** — 별도 Pages 프로젝트라 web의 `robots.txt`(Worker 생성)를 고쳐도 admin에는 아무 영향이 없다. 등록 정책은 `DEPLOY.md` §7-4.

## 인증

- **`shared/lib/api/client.ts`·`entities/session`·`features/login`·`features/logout`은 web 동형 구현의 복제다** — 쿼리 옵션 공유, `resetQueries`로 즉시 로그아웃 반영, `beforeLoad: requireSession` 가드까지 모양이 같으니 **그 규약은 `apps/web/CLAUDE.md`를 먼저 볼 것.**
- 다른 것은 **엔드포인트뿐**이다: `POST /admin/auth/login` · `GET /admin/me` · `POST /admin/auth/logout`. 서버 쪽도 쿠키 이름(`admin_session_id`)과 Redis 프리픽스가 완전히 분리돼 있어 교차 인증이 구조적으로 불가능하다.
- **web에 있는데 가져오지 않은 것 셋**: `setUnauthorizedHandler` · 구글 로그인 · 비밀번호 표시 토글(내부 발급 계정이라 소셜 로그인이 없다).
- 새 보호 라우트는 `beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href)` 한 줄만 추가하면 된다.

## 라우팅

- **새 화면을 추가하면 `widgets/admin-sidebar/config/nav.ts`의 `ADMIN_NAV_ITEMS`에도 항목을 더해야 한다** — 안 하면 라우트는 있어도 **사이드바로는 도달할 수 없다**. 목록이 `as const`라 각 `to`가 리터럴로 좁혀져 라우터가 만든 경로 유니온과 대조되므로 없는 라우트는 타입 에러로 걸리는데, **에러는 `config/nav.ts`가 아니라 `ui/AdminSidebar.tsx`에 뜬다**(`AdminNavItem` 타입이 이 목록에서 도출된 것이라 제약을 걸지 않는다).
- **사이드바는 `routes/__root.tsx`가 마운트해 로그인 화면을 제외한 모든 라우트를 감싼다.** `/login`이 세션 없는 유일한 비보호 라우트라 `pathname === "/login"`으로 분기한다(pathless layout route를 쓰지 않은 이유는 라우트 파일 5개를 옮기고 레이아웃 파일을 새로 만들어야 해서다).
- **목록과 그 상세를 형제 화면으로 두려면 목록 쪽을 `.index.tsx`로 명명한다.** `reports.tsx`(실제 경로를 가진 라우트) 옆에 `reports.$reportId.tsx`를 두면 TanStack Router가 상세를 **`reports`의 자식으로 중첩**시키고, 부모에 `<Outlet/>`이 없으면 **URL만 바뀌고 화면은 그대로 부모가 보인다**(콘솔 에러 없는 조용한 실패). `reports.index.tsx`로 두면 `reports`가 암묵적 pathless 레이아웃이 되어 둘이 형제로 분리된다 — 지금 `contents`·`users`·`reports` 셋 다 이 모양이다.
  - `apps/web`의 `builder.$type.*`가 이 함정에 안 걸리는 건 `builder.$type.tsx` 파일 자체가 없어 공유 프리픽스가 처음부터 암묵적 레이아웃이기 때문이다.
  - **라우트 파일을 rename한 직후 `routeTree.gen.ts`가 깨진 채(참조 없는 심볼이 남은 채) 재생성되는 경우가 있다** — dev 서버를 죽이고 `routeTree.gen.ts`를 지운 뒤 `vite build`로 처음부터 다시 만든다.

## UI

- **`react-call`(확인 모달)·`sonner`(토스트)는 web과 같은 관례다** — Callable은 `routes/__root.tsx`에 1회 마운트하고 `<Toaster />`는 `main.tsx`에 둔다. **두 의존성은 admin `package.json`에 직접 넣어야 한다**(pnpm 워크스페이스가 간접 의존성을 안 끌어온다).
- **되돌릴 수 없는 삭제는 이름 완전 일치로 확인받는다** — `features/act-on-report/ui/DeleteConfirmModal.tsx`(`{contentName, mutationFn}`, 입력값이 `contentName`과 정확히 같아야 확정 버튼 활성화). 도메인이 다르면 새 컴포넌트로 만들되 이 검증 패턴을 재사용한다.
- **목록 항목에 상세 정보가 이미 다 들어 있으면 별도 라우트로 분리하지 말고 한 페이지 안에서 로컬 `useState`로 렌더한다**(`pages/appeals`가 그 사례 — 선택된 id로 `items.find(...)`). 별도 상세 쿼리도 라우트도 필요 없고, 필터·페이지가 바뀌어 선택된 id가 목록에서 사라지면 상세 섹션도 자연히 사라진다(정리 코드 불필요). **실제 detail 엔드포인트가 생기면** 그때 `reports` 패턴(형제 라우트 + 상세 쿼리)으로 옮긴다.
