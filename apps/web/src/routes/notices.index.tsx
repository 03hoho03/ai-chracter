import { createFileRoute } from "@tanstack/react-router";

import { NoticesPage } from "../pages/notices";

/** 공개 라우트 — `routes/terms.tsx`처럼 `beforeLoad: requireSession`이 없다(D-5). 약관이 약속한
 * 고지 채널이 로그인 뒤에 있으면 문구와 어긋난다. 목록은 `.index.tsx`로 둔다 — `notices.tsx` 옆에
 * `notices.$noticeId.tsx`를 두면 상세가 자식으로 중첩돼 URL만 바뀌고 화면은 부모가 그대로
 * 보인다(조용한 실패, `apps/web/CLAUDE.md` §아키텍처/라우팅). */
export const Route = createFileRoute("/notices/")({
  component: RouteComponent,
});

function RouteComponent() {
  return <NoticesPage />;
}
