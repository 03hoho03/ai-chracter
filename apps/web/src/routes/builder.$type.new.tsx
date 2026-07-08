import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { BuilderNewPage } from "../pages/builder";

// techspec-builder-character.md §0 / techspec-builder-story.md §0 — "new" static 세그먼트가
// builder.$type.$draftId.tsx의 동적 $draftId보다 먼저 매치된다(TanStack Router는 정적 경로를 우선한다).
export const Route = createFileRoute("/builder/$type/new")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { type } = Route.useParams();
  return <BuilderNewPage type={type === "story" ? "story" : "character"} />;
}
