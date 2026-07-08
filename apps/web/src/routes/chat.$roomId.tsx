import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatRoomPage } from "../pages/chat-room";

// US-055/060 — 캐릭터/스토리 공용 챗 대화 화면. `widgets/content-detail/lib/usePlayContent.ts`가
// 콘텐츠 타입과 무관하게 방을 만든 뒤 이 라우트로 navigate한다.
export const Route = createFileRoute("/chat/$roomId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { roomId } = Route.useParams();
  return <ChatRoomPage roomId={roomId} />;
}
