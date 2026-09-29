import { createFileRoute } from "@tanstack/react-router";

import { CreationGuidePage } from "@/pages/creation-guide";

/** 공개 라우트 — 로그인 가드를 걸지 않는다. 빌더에서 새 탭으로 여는 작성 가이드라 로그인 여부와 무관하게
 * 보인다. */
export const Route = createFileRoute("/guide/character")({
  component: RouteComponent,
});

function RouteComponent() {
  return <CreationGuidePage topicId="character" />;
}
