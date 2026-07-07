# apps/web

- FSD 레이어 의존 방향: `app → pages → widgets → features → entities → shared` (역방향 import 금지). `routes/*`는 로직 없이 `pages/{page}`를 렌더링만 하는 얇은 어댑터로 유지한다.
- `src/routeTree.gen.ts`는 TanStack Router의 `@tanstack/router-plugin` Vite 플러그인이 `vite dev`/`vite build` 실행 시 자동 생성하는 파일이며, `tsc --noEmit`만으로는 fresh checkout에서 생성되지 않으므로 **git에 커밋**한다. 라우트를 추가/변경했다면 typecheck·커밋 전에 `vite build`(또는 `vite dev` 1회)를 먼저 실행해 이 파일을 최신 상태로 갱신해야 한다. 갱신을 빼먹어도 typecheck는 통과하지만(오래된 트리 기준으로만 검사) 새 라우트가 검증에서 누락된다.
- 디자인시스템은 `packages/ui`(shadcn+Tailwind v4)를 그대로 쓴다. `vite.config.ts`에 `@tailwindcss/vite` 플러그인이 등록되어 있고, `main.tsx`에서 `@ai-character-chat/ui/globals.css` 한 번만 import하면 전체 앱에 토큰/유틸리티가 적용된다(이 앱 자체는 별도 `tailwind.config`/전역 css를 갖지 않는다). 컴포넌트는 `@ai-character-chat/ui/components/{name}`에서 가져온다. 자세한 내용은 `packages/ui/CLAUDE.md` 참고.
