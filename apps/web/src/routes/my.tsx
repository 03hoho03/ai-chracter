import { createFileRoute, redirect } from "@tanstack/react-router";

import { myWorksSearchSchema } from "@/pages/my-works";
import { toStudioSearch } from "@/pages/studio";

// 옛 내 작품 주소의 북마크와 로그인 복귀 주소(`/login?redirect=/my…`)를 살리려고 남긴 라우트다. 만든 작품은 이제
// 스튜디오 홈에 있다. 서버 301 이 아니라 여기서 넘기는 이유는 브라우저가 301 을 캐시해 되돌리기가 안 되기 때문이다.
// 옛 스키마로 조건을 읽은 뒤 스튜디오 축으로 옮긴다 — 값을 그대로 넘기면 스튜디오가 모르는 값을 "전체"로 떨어뜨린다.
// 세션은 여기서 보지 않는다. 보면 비로그인이 로그인 뒤 이 주소로 돌아왔다가 한 번 더 튄다 — 스튜디오 홈이 본다.
// 리다이렉트는 기록을 바꿔치기해 뒤로가기에 이 주소가 남지 않는다.
export const Route = createFileRoute("/my")({
  validateSearch: myWorksSearchSchema,
  beforeLoad: ({ search }) => redirect({ to: "/studio", search: toStudioSearch(search), replace: true, throw: true }),
});
