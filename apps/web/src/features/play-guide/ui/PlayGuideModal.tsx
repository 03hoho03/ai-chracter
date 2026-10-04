import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { useChatRoomPlayGuideQuery } from "@/entities/chat-room";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

type PlayGuideModalProps = {
  roomId: string;
  /** 연 방의 `{{user}}`·`{{char}}` 이름 — 이 모달은 루트에 마운트돼 방을 모른다. */
  macroNames: AuthorMacroNames;
};

/** "더보기 > 플레이가이드"에서 여는 읽기 전용 react-call 모달.
 * 입력/제출이 없어 mutationFn/useMutationFlow 없이 call.end()만으로 닫는다. */
export const PlayGuideModal = createCallable<PlayGuideModalProps, void>(({ call, roomId, macroNames }) => {
  const isOpen = !call.ended;
  const playGuideQuery = useChatRoomPlayGuideQuery(roomId, isOpen);

  return (
    <Dialog open={isOpen} onOpenChange={(next) => !next && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>플레이가이드</DialogTitle>
          <DialogDescription>대화를 이어가는 데 도움이 되는 진행 팁이에요.</DialogDescription>
        </DialogHeader>

        <PlayGuideBody query={playGuideQuery} macroNames={macroNames} />
      </DialogContent>
    </Dialog>
  );
});

/** 네 상태(로딩·에러·본문·빈 값)가 배타적이라 early return으로 순서를 강제한다. */
function PlayGuideBody({
  query,
  macroNames,
}: {
  query: ReturnType<typeof useChatRoomPlayGuideQuery>;
  macroNames: AuthorMacroNames;
}) {
  if (query.isPending) {
    return (
      <div className="flex flex-col gap-2">
        <div className="h-4 w-full animate-pulse rounded-md bg-secondary" />
        <div className="h-4 w-3/4 animate-pulse rounded-md bg-secondary" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <p className="py-4 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const playGuide = query.data?.playGuide;
  if (!playGuide) {
    return <p className="py-4 text-center text-sm text-muted-foreground">등록된 플레이가이드가 없어요.</p>;
  }

  return <p className="whitespace-pre-wrap text-sm text-foreground">{expandAuthorMacros(playGuide, macroNames)}</p>;
}
