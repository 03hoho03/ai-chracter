# packages/ui

- shadcn 컴포넌트는 `components.json` 설정으로 `npx shadcn@latest add <name> -c packages/ui`(또는 이 패키지 안에서 `-c .`)로 추가한다. CLI가 이 패키지 스코프(`@ai-character-chat/ui`)의 alias를 그대로 써서 `src/components/*.tsx`에 생성한다.
- Tailwind는 v4(CSS-first)라 `tailwind.config.js`가 없다. 색상/타이포/spacing/radius 토큰은 전부 `src/styles/globals.css`의 `:root`/`@theme inline` 블록 하나에만 정의한다(DESIGN.md와 동일 소스 유지). 새 앱(`apps/admin` 등)이 이 패키지를 쓰려면 `@tailwindcss/vite` 플러그인만 추가하고 진입점에서 `@ai-character-chat/ui/globals.css`를 import하면 된다.
- `globals.css`의 `@source` 경로는 CSS 파일 실제 위치(`packages/ui/src/styles/`) 기준 상대경로다. 새 앱을 추가할 때 그 앱의 `src`가 이미 `../../../../apps/**/*.{ts,tsx}` 글롭에 걸리는지 확인하고, 걸리지 않으면 새 `@source` 줄을 추가한다.
- 다크모드는 아직 구현하지 않았다(다크모드 요구사항이 생기면 `.dark` 블록과 `@custom-variant dark`를 다시 추가하고, `sonner.tsx`에 `next-themes`를 다시 연결해야 한다 — 지금은 `theme="light"`로 고정되어 있다).
- shadcn 컴포넌트 소스를 그대로 가져오되 `dark:` variant 클래스는 제거했고(다크모드 미구현), 사용자 노출 텍스트("Close" 등)는 한국어로 교체했다 — 새 컴포넌트를 추가할 때도 동일하게 정리한다.
- Toast는 shadcn에서 deprecated된 `toast` 대신 `sonner`를 쓴다. `<Toaster />`는 앱 루트에 한 번만 마운트(`apps/web/src/main.tsx`)하고, 실제 호출은 각 기능 코드에서 `import { toast } from "sonner"`로 직접 한다(패키지 재노출 없음) — 그래서 `sonner`를 쓰는 앱은 자신의 `package.json`에도 `sonner`를 직접 의존성으로 추가해야 한다(pnpm 워크스페이스는 간접 의존성을 자동으로 끌어오지 않음).
- 한글 UI이므로 폰트는 Pretendard(`pretendard` npm 패키지의 variable dynamic-subset)를 쓴다. Fontsource 계열이 아니라 `pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css`를 globals.css에서 직접 import한다.
