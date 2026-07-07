import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { BuilderPage } from "../pages/builder";

// techspec-builder-common.md §2 — 마이페이지 초안 카드가 이동하는 목적지. 실제 빌더는 US-100/US-106에서 구현된다.
export const Route = createFileRoute("/builder/$type/$draftId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: BuilderPage,
});
