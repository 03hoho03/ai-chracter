import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { ChatsPage } from "../pages/chats";

// techspec-chat-common.md §3 — 목록은 콘텐츠(캐릭터/스토리) 단위로 스코프되므로 contentId/contentType을
// search param으로 받는다. 콘텐츠 상세 진입점 없이(예: 헤더의 범용 링크) 들어오면 둘 다 없을 수 있어 optional.
// 모르는 값은 그 축만 기본값(= 파라미터의 부재)으로 흘려보낸다 — `validateSearch` 8곳 공통 처방.
const chatsSearchSchema = z.object({
  contentId: z.string().optional().catch(undefined),
  contentType: z.enum(["character", "story"]).optional().catch(undefined),
});

export const Route = createFileRoute("/chats")({
  validateSearch: chatsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { contentId, contentType } = Route.useSearch();
  return <ChatsPage contentId={contentId} contentType={contentType} />;
}
