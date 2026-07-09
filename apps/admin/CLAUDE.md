# apps/admin

- 관리자 전용 별도 배포 앱. `apps/web`과 동일 스택(Vite/React/TanStack Router+Query/Jotai, `packages/ui`)을 재사용하되, `techspec-overview.md` §2에 따라 FSD 레이어 수를 단순하게 유지한다: `widgets`는 아직 없고 실제로 필요한 스토리(US-053/055 등)에서 그때그때 추가한다 — apps/web처럼 미리 빈 `.gitkeep` 레이어를 만들지 않는다.
- 개발 서버 포트는 5174로 고정(`vite.config.ts`의 `server.port`)해서 `apps/web`(5173, 기본값)과 동시에 띄울 수 있게 한다.
- `src/routeTree.gen.ts` 커밋 정책과 갱신 방법은 `apps/web/CLAUDE.md` 참고(동일하게 적용됨).
- **(US-118, 첫 실제 화면 — 관리자 로그인) `shared/lib/api/client.ts`/`entities/session`/`features/login`/`features/logout`가 apps/web의 동형 구현을 완전히 별도의 관리자 인증 엔드포인트(`POST /admin/auth/login`, `GET /admin/me`, `POST /admin/auth/logout`, US-117)로 그대로 복제한 것이다** — 코드 모양(쿼리 옵션 공유, `resetQueries`로 즉시 로그아웃 반영, `beforeLoad: requireSession` 라우터 가드)은 `apps/web/CLAUDE.md`의 대응 항목과 동일하니 그쪽을 먼저 참고할 것. `apps/web`의 `setUnauthorizedHandler`/구글 로그인/비밀번호 표시토글은 관리자 로그인에 해당 기능이 없어(내부 발급 계정, 소셜 로그인 없음) 가져오지 않았다.
- `app/router.tsx`/`routes/__root.tsx`가 이제 `createRootRouteWithContext<{queryClient}>`를 쓴다(apps/web과 동일한 이유 — `requireSession`이 라우터 컨텍스트의 `queryClient`를 필요로 함). 새 보호 라우트는 `beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href)`만 추가하면 된다.
- 아직 전역 헤더/네비게이션 셸이 없다 — `pages/home`이 로그아웃 버튼을 임시로 들고 있다. 실제 관리자 대시보드 셸(신고/이의제기/사용량 탭 등, US-119+)이 생기면 이 버튼을 그 셸로 옮길 것.
