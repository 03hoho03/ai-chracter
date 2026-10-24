import { toast } from "sonner";

import { isPremiumChatModel, type ChatModel, type ChatModelId } from "@/entities/chat-model";

import { useSetRoomChatModelMutation } from "../api/useSetRoomChatModelMutation";
import { isChatModelNotAllowedError } from "../model/chatModelError";
import { ChatModelOptions } from "./ChatModelOptions";

type ChatModelPickerProps = {
  roomId: string;
  /** 방이 지금 실제로 쓰는 모델(유효 모델). 저장한 상위 모델을 쓸 수 없게 되면 서버가 기본 모델로 알려 준다. */
  currentModelId: ChatModelId;
  models: ChatModel[];
  onChanged: () => void;
};

/** 대화방의 글쓰기 모델 목록. 기본 모델로는 누르면 바로 바꾸고, 상위 모델은 고른 뒤 한 번 더 확인받는다.
 *
 * 상위 모델에만 확인을 두는 이유: 그 모델은 무료 대화 없이 턴마다 클로버를 쓰고, 바꾼 뒤에는 하루 한 번 확인도 묻지
 * 않는다 — 이 확인이 그 방에서 클로버를 쓰겠다는 유일한 동의다. 기본 모델로 되돌리는 것은 돈이 덜 드는 쪽이라 묻지
 * 않는다(허용을 거둔 뒤에도 되돌릴 수 있다).
 *
 * 목록·확인 블록의 화면은 `ChatModelOptions` 가 그리고, 여기는 고른 모델을 방에 저장하고 결과를 알리는 일만 한다. */
export function ChatModelPicker({ roomId, currentModelId, models, onChanged }: ChatModelPickerProps) {
  const setRoomChatModelMutation = useSetRoomChatModelMutation(roomId);

  function save(modelId: ChatModelId, cancelConfirm: () => void) {
    setRoomChatModelMutation.mutate(modelId, {
      onSuccess: () => {
        toast.success("모델을 바꿨어요. 다음 턴부터 적용돼요.");
        onChanged();
      },
      onError: (error) => {
        cancelConfirm();
        toast.error(
          isChatModelNotAllowedError(error)
            ? "이 모델을 지금 이 계정에서 쓸 수 없어요."
            : "모델을 바꾸지 못했어요. 잠시 후 다시 시도해주세요.",
        );
      },
    });
  }

  return (
    <ChatModelOptions
      currentModelId={currentModelId}
      models={models}
      listLabel="이 대화방의 글쓰기 모델"
      commitLabel="이 모델로 바꾸기"
      isCommitting={setRoomChatModelMutation.isPending}
      needsConfirm={isPremiumChatModel}
      onCommit={save}
    />
  );
}
