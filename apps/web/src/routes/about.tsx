import { createFileRoute } from "@tanstack/react-router";

import { AboutPage } from "@/pages/about";

/** 공개 라우트 — `login.tsx`처럼 `beforeLoad: requireSession`이 없다. 로그인 여부와 무관하게
 * 서비스 소개를 보여준다. */
export const Route = createFileRoute("/about")({
  component: AboutPage,
});
