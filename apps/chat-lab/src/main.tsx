import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "./app/AppProviders";
import { router } from "./app/router";

import "./app/styles.css";

// `index.html` 의 `#root` 가 사라지면 `createRoot(null)` 이 리액트 안에서 터져 스택이 앱 코드를 가리키지 않는다.
// 부팅 지점에서 한 번만 도는 검사다.
const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("index.html 에 #root 가 없다");

createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
