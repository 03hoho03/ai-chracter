import type { ContentType } from "@/entities/content";
import { ChatRoomListView, MyChatRoomListView } from "@/widgets/chat-room-list";

// techspec-chat-common.md §3 — 목록은 콘텐츠(캐릭터/스토리) 단위로 스코프된다. 콘텐츠 상세화면의
// "내 대화 목록" 진입점(widgets/content-detail)이 contentId/contentType을 search param으로 넘겨주면
// 그 콘텐츠의 목록만, 그 외의 경로(헤더의 범용 진입점)로 파라미터 없이 들어오면 내 전체 대화방 목록을
// 보여준다.
export function ChatsPage({
  contentId,
  contentType,
}: {
  contentId?: string;
  contentType?: ContentType;
}) {
  if (contentId && contentType) {
    return <ChatRoomListView contentId={contentId} contentType={contentType} />;
  }

  return <MyChatRoomListView />;
}
