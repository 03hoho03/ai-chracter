import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatPage } from "../pages/chat";

// techspec-chat-common.md §3 — 플레이 버튼(widgets/content-detail)이 이동하는 목적지. 대화방
// 생성 API(US-051 캐릭터 챗/US-057 스토리 챗)와 실제 대화 화면(US-055/US-060)이 아직 없어
// ComingSoonPage로 연결해뒀다 — 그 스토리들에서 pages/chat/ui/ChatPage.tsx 내부만 교체하면 된다.
export const Route = createFileRoute("/chat/$type/$id")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: ChatPage,
});
