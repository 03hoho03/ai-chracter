import { createFileRoute } from "@tanstack/react-router";

import { LegalDocumentPage } from "@/pages/legal-document";

/** 공개 라우트 — `login.tsx`처럼 `beforeLoad: requireSession`이 없다. 로그인 여부와 무관하게
 * 최신 게시본을 보여준다. */
export const Route = createFileRoute("/terms")({
  component: RouteComponent,
});

function RouteComponent() {
  return <LegalDocumentPage kind="terms" />;
}
