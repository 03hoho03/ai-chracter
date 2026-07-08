import { createFileRoute } from "@tanstack/react-router";

import { requireSession } from "../entities/session";
import { ChatRoomPage } from "../pages/chat-room";

// US-055 — 캐릭터 챗 대화 화면. `widgets/content-detail/lib/usePlayContent.ts`가 방을 만든 뒤
// 이 라우트로 navigate한다(`routes/chat.$type.$id.tsx`는 아직 방 생성 API가 없는 스토리 챗 전용 스텁으로 남는다).
export const Route = createFileRoute("/chat/$roomId")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { roomId } = Route.useParams();
  return <ChatRoomPage roomId={roomId} />;
}
