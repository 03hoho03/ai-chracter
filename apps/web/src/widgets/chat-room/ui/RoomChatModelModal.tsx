import { useEffect, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";

import { useChatModelsQuery } from "@/entities/chat-model";
import { chatRoomKeys, useChatRoomQuery } from "@/entities/chat-room";
import { ChatModelPicker } from "@/features/select-chat-model";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { isRoomModelMissingFromList, roomChatModelNotice } from "../model/roomChatModelNotice";

type RoomChatModelModalProps = {
  roomId: string;
};

/** 채팅방의 글쓰기 모델 선택. 더보기의 다른 항목처럼 "패널을 닫고 모달을 연다"로 둔 이유는 `RoomPersonaModal` 과
 * 같다(인라인 사이드바와 드롭업 시트가 같은 코드 한 벌을 쓴다).
 *
 * 목록은 열 때마다 서버에 다시 묻는다(`useChatModelsQuery`) — 상위 모델 허용은 세션 중에도 바뀐다. 지금 모델은 방
 * 상세 캐시의 유효 모델이고, 바꾸면 그 캐시를 응답으로 고쳐 입력창 위 잔량 표시와 부족 문구가 바로 따라온다.
 *
 * 방에 저장한 모델을 지금 쓸 수 없어 서버가 기본 모델로 돌리는 방이면 설명 끝에 그 사실을 한 줄 더한다. 받은 목록에
 * 방의 유효 모델이 없으면 그 값이 낡은 것이라 방 상세를 새로 받는다. */
export const RoomChatModelModal = createCallable<RoomChatModelModalProps, void>(({ call, roomId }) => {
  const room = useChatRoomQuery(roomId).data;
  const modelsQuery = useChatModelsQuery();
  const models = modelsQuery.data;
  const queryClient = useQueryClient();
  const effectiveChatModel = room?.effectiveChatModel;
  const notice = room && roomChatModelNotice(room);

  // 진행 중인 방 상세 조회가 있으면(모달이 열리며 방 상세 구독이 새로 붙어 다시 받는 중이면) 그 조회에 합류해 요청을
  // 늘리지 않는다. 새로 받은 유효 모델이 같은 값이면 의존값이 그대로라 다시 돌지 않는다.
  useEffect(() => {
    if (!models || effectiveChatModel === undefined || !isRoomModelMissingFromList(models, effectiveChatModel)) return;
    void queryClient.refetchQueries({ queryKey: chatRoomKeys.detail(roomId), exact: true }, { cancelRefetch: false });
  }, [models, effectiveChatModel, queryClient, roomId]);

  // 세 상태(불러오는 중·실패·목록)는 배타적이다 — 렌더 전에 한 갈래로 정한다(`RoomPersonaModal` 선례).
  // 목록 갈래는 본문과 확인 푸터를 `ChatModelOptions` 가 함께 그리고, 나머지 두 갈래는 본문만 있다.
  let body: ReactNode;
  if (modelsQuery.isPending || !room) {
    body = (
      <DialogBody>
        <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>
      </DialogBody>
    );
  } else if (!models) {
    body = (
      <DialogBody>
        <div className="flex flex-col items-center gap-3 py-6">
          <p className="text-sm break-keep text-muted-foreground">모델 목록을 불러오지 못했어요.</p>
          <Button type="button" variant="outline" onClick={() => void modelsQuery.refetch()}>
            다시 시도
          </Button>
        </div>
      </DialogBody>
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
            {/* 설명 문단 안에 두어 모달이 열릴 때 설명과 함께 읽힌다. 이 방에만 해당하는 사실이라 잉크를 한 칸 올린다. */}
            {notice && <span className="mt-2 block text-foreground">{notice}</span>}
          </DialogDescription>
        </DialogHeader>

        {body}
      </DialogContent>
    </Dialog>
  );
});
