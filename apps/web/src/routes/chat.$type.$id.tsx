import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatPage } from "../pages/chat";

// techspec-chat-common.md §3 — 플레이 버튼(widgets/content-detail)이 이동하는 목적지. 캐릭터 챗은
// US-055부터 `/chat/$roomId`(실제 대화 화면)로 바로 이동하므로 이 라우트는 더 이상 쓰이지 않는다.
// 스토리 챗은 대화방 생성 API(US-057)와 실제 대화 화면(US-060)이 아직 없어 여전히 ComingSoonPage로
// 연결해뒀다 — 그 스토리들에서 pages/chat/ui/ChatPage.tsx 내부만 교체하면 된다.
export const Route = createFileRoute("/chat/$type/$id")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: ChatPage,
});
