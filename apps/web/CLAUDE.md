# apps/web

- FSD 레이어 의존 방향: `app → pages → widgets → features → entities → shared` (역방향 import 금지). `routes/*`는 로직 없이 `pages/{page}`를 렌더링만 하는 얇은 어댑터로 유지한다.
- `src/routeTree.gen.ts`는 TanStack Router의 `@tanstack/router-plugin` Vite 플러그인이 `vite dev`/`vite build` 실행 시 자동 생성하는 파일이며, `tsc --noEmit`만으로는 fresh checkout에서 생성되지 않으므로 **git에 커밋**한다. 라우트를 추가/변경했다면 typecheck·커밋 전에 `vite build`(또는 `vite dev` 1회)를 먼저 실행해 이 파일을 최신 상태로 갱신해야 한다. 갱신을 빼먹어도 typecheck는 통과하지만(오래된 트리 기준으로만 검사) 새 라우트가 검증에서 누락된다.
