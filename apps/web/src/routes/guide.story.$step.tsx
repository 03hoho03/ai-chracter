import { createFileRoute } from "@tanstack/react-router";

import { CreationGuideStepPage } from "@/pages/creation-guide";

/** 공개 라우트 — 로그인 가드를 걸지 않는다(개요 라우트와 같은 이유). 모르는 단계 id 는 페이지가 개요로 돌려보낸다. */
export const Route = createFileRoute("/guide/story/$step")({
  component: RouteComponent,
});

function RouteComponent() {
  const { step } = Route.useParams();
  return <CreationGuideStepPage topicId="story" stepId={step} />;
}
