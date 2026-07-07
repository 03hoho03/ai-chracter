# apps/admin

- 관리자 전용 별도 배포 앱. `apps/web`과 동일 스택(Vite/React/TanStack Router+Query/Jotai, `packages/ui`)을 재사용하되, `techspec-overview.md` §2에 따라 FSD 레이어 수를 단순하게 유지한다: 현재는 `app/routes/pages`만 존재하고 `widgets/features/entities/shared`는 실제로 필요한 스토리(US-051/053/055 등)에서 그때그때 추가한다 — apps/web처럼 미리 빈 `.gitkeep` 레이어를 만들지 않는다.
- 개발 서버 포트는 5174로 고정(`vite.config.ts`의 `server.port`)해서 `apps/web`(5173, 기본값)과 동시에 띄울 수 있게 한다.
- `src/routeTree.gen.ts` 커밋 정책과 갱신 방법은 `apps/web/CLAUDE.md` 참고(동일하게 적용됨).
