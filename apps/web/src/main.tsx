import "@ai-character-chat/ui/globals.css";

import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "./app/providers";
import { router } from "./app/router";
import { AppToaster } from "./app/toaster";

// `index.html`의 `#root`가 사라지면 `!`는 `createRoot(null)`로 넘겨 리액트 내부에서 터진다 —
// 스택이 앱 코드를 안 가리켜 원인을 찾기 어렵다. 부팅 지점이라 한 번만 도는 검사다.
const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("index.html에 #root가 없다");

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
      <AppToaster />
    </AppProviders>
  </StrictMode>,
);
