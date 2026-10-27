import { createFileRoute, Navigate, redirect } from "@tanstack/react-router";

import { hasEnabledFeature, requireSession, useSessionQuery } from "@/entities/session";
import { StudioNewNovelPage } from "@/pages/studio-new-novel";

// 소설화가 열린 계정만 쓰는 화면이다. 닫힌 계정은 주소로 들어와도 스튜디오 홈으로 보낸다 — 잠김 안내를 그리지 않는다
// (스튜디오 홈도 그 계정에는 이 화면으로 오는 칸을 두지 않는다).
export const Route = createFileRoute("/studio/new-novel")({
  beforeLoad: async ({ context, location }) => {
    const { session } = await requireSession(context.queryClient, location.href);
    if (!hasEnabledFeature(session.enabledFeatures, "novelize")) redirect({ to: "/studio", replace: true, throw: true });
    return { session };
  },
  component: RouteComponent,
});

function RouteComponent() {
  // 진입 판정은 그때의 세션 사본이라, 화면에 머무는 사이 허용이 회수되면(소설 쪽 403 을 받으면 전역 처리가 세션을 다시
  // 읽는다) 다시 받은 세션으로 한 번 더 본다.
  const { data: session } = useSessionQuery();
  if (session !== undefined && !hasEnabledFeature(session.enabledFeatures, "novelize")) {
    return <Navigate to="/studio" replace />;
  }
  return <StudioNewNovelPage />;
}
