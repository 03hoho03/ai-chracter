import { RouterProvider } from "@tanstack/react-router";
import { Agentation } from "agentation";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "./app/AppProviders";
import { router } from "./app/router";
import { AppToaster } from "./app/AppToaster";
import { initSentry } from "./app/sentry";

import "@ai-character-chat/ui/globals.css";

// 렌더보다 먼저 부른다 — 이 아래의 `#root` 부재 같은 부팅 단계 에러도 잡히게 한다(MT-7).
initSentry();

// `index.html`의 `#root`가 사라지면 `!`는 `createRoot(null)`로 넘겨 리액트 내부에서 터진다 —
// 스택이 앱 코드를 안 가리켜 원인을 찾기 어렵다. 부팅 지점이라 한 번만 도는 검사다.
const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("index.html에 #root가 없다");

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
      <AppToaster />
      {/* 개발 전용 주석 도구(agentation, devDependency) — 화면 요소를 찍어 남긴 코멘트를 MCP로
          에이전트가 읽어간다. 공식 문서는 `process.env.NODE_ENV`로 가드하지만 이 앱은 Vite라
          브라우저에 `process`가 없다(`process.env` 사용 0건, 관례는 `shared/api/client.ts:5`의
          `import.meta.env`). `import.meta.env.DEV`는 빌드 시 `false` 리터럴로 치환돼 이 분기와
          import가 프로덕션 번들에서 통째로 빠진다 — devDependency가 배포에 실리지 않는 근거다
          (실측: 3.5MB 패키지인데 `dist/`에서 문자열 0건, 번들 +3바이트).

          `endpoint`가 없으면 주석이 localStorage에만 쌓여 에이전트가 못 읽는다(타입 주석 원문:
          "If not provided, uses localStorage only"). 4747은 `agentation-mcp server`가 여는 포트다. */}
      {import.meta.env.DEV && <Agentation endpoint="http://localhost:4747" />}
    </AppProviders>
  </StrictMode>,
);
