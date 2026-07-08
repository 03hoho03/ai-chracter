import { ChatRoomListView } from "../../../widgets/chat-room-list";

// techspec-chat-common.md §3 — 목록은 콘텐츠(캐릭터/스토리) 단위로 스코프된다. 콘텐츠 상세화면의
// "내 대화 목록" 진입점(widgets/content-detail)이 contentId/contentType을 search param으로 넘겨준다.
// 그 외의 경로(예: 헤더의 범용 진입점)로 파라미터 없이 들어오면 안내 문구만 보여준다.
export function ChatsPage({
  contentId,
  contentType,
}: {
  contentId?: string;
  contentType?: "character" | "story";
}) {
  if (!contentId || !contentType) {
    return (
      <main className="mx-auto flex max-w-2xl flex-col items-center gap-2 px-6 py-20 text-center">
        <h1 className="text-xl font-bold tracking-tight text-foreground">내 채팅목록</h1>
        <p className="text-sm text-muted-foreground">
          캐릭터·스토리 상세화면의 "내 대화 목록"에서 들어오면 해당 작품의 대화방을 확인할 수 있어요.
        </p>
      </main>
    );
  }

  return <ChatRoomListView contentId={contentId} contentType={contentType} />;
}
