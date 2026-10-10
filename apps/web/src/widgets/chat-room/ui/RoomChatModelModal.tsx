import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { useChatModelsQuery } from "@/entities/chat-model";
import { useChatRoomQuery } from "@/entities/chat-room";
import { ChatModelPicker } from "@/features/select-chat-model";
import { createCallable } from "@/shared/lib/callable/createCallable";

type RoomChatModelModalProps = {
  roomId: string;
};

/** 채팅방의 글쓰기 모델 선택. 더보기의 다른 항목처럼 "패널을 닫고 모달을 연다"로 둔 이유는 `RoomPersonaModal` 과
 * 같다(인라인 사이드바와 드롭업 시트가 같은 코드 한 벌을 쓴다).
 *
 * 목록은 열 때마다 서버에 다시 묻는다(`useChatModelsQuery`) — 상위 모델 허용은 세션 중에도 바뀐다. 지금 모델은 방
 * 상세 캐시의 유효 모델이고, 바꾸면 그 캐시를 응답으로 고쳐 입력창 위 잔량 표시와 부족 문구가 바로 따라온다. */
export const RoomChatModelModal = createCallable<RoomChatModelModalProps, void>(({ call, roomId }) => {
  const room = useChatRoomQuery(roomId).data;
  const modelsQuery = useChatModelsQuery();
  const models = modelsQuery.data;

  // 세 상태(불러오는 중·실패·목록)는 배타적이다 — 렌더 전에 한 갈래로 정한다(`RoomPersonaModal` 선례).
  let body: ReactNode;
  if (modelsQuery.isPending || !room) {
    body = <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>;
  } else if (!models) {
    body = (
      <div className="flex flex-col items-center gap-3 py-6">
        <p className="text-sm break-keep text-muted-foreground">모델 목록을 불러오지 못했어요.</p>
        <Button type="button" variant="outline" onClick={() => void modelsQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  } else {
    body = (
      <ChatModelPicker
        roomId={roomId}
        currentModelId={room.effectiveChatModel}
        models={models}
        onChanged={() => call.end()}
      />
    );
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>AI 모델</DialogTitle>
          <DialogDescription className="break-keep">
            이 대화방에서 캐릭터의 답을 쓰는 모델이에요. 바꾸면 다음 턴부터 적용되고, 지금 쓰고 있는 답과 지난 대화는
            그대로예요. 모델마다 문체가 달라 답의 느낌이 바뀔 수 있어요.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>{body}</DialogBody>
      </DialogContent>
    </Dialog>
  );
});
