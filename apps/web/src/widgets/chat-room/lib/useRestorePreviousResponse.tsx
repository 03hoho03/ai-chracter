import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { chatRoomKeys, useRestorePreviousResponseMutation } from "@/entities/chat-room";
import { UNDO_TOAST_DURATION_MS, UndoToastButton } from "@/features/build-common";

import {
  RESTORE_PREVIOUS_RESPONSE_SUCCESS_MESSAGE,
  toRestorePreviousResponseFailure,
} from "../model/restorePreviousResponseFailure";

const REGENERATED_TOAST_ID = "chat-regenerated-undo";

/** 재생성이 밀어낸 직전 응답으로 되돌리기. 메시지 메뉴와 재생성 직후 토스트의 [되돌리기]가 같은 `restore` 를 부른다.
 * `onRestored` 는 되돌린 방이 캐시에 들어간 뒤 불린다 — 메뉴를 연 응답이 다른 id 의 응답으로 바뀌어 사라지므로, 부르는 쪽이
 * 포커스를 둘 곳을 정한다. */
export function useRestorePreviousResponse(roomId: string, onRestored: () => void) {
  const queryClient = useQueryClient();
  const mutation = useRestorePreviousResponseMutation(roomId);
  // 토스트의 버튼은 띄운 렌더의 함수를 붙잡고 있어 `isPending` 이 낡는다. 진행 여부는 렌더와 무관한 ref 로 본다 — 두 번째
  // 요청은 서버에서 "대화가 바뀌었다"로 거절돼 사실과 다른 문구를 띄운다.
  const isRestoringRef = useRef(false);

  // 방을 떠나면 이 방의 되돌리기 안내를 거둔다. 토스트는 앱 루트에 있어 화면을 옮겨도 남는다.
  useEffect(
    () => () => {
      toast.dismiss(REGENERATED_TOAST_ID);
    },
    [roomId],
  );

  async function restore(messageId: string) {
    if (isRestoringRef.current) return;
    isRestoringRef.current = true;
    toast.dismiss(REGENERATED_TOAST_ID);
    try {
      await mutation.mutateAsync(messageId);
      onRestored();
      toast(RESTORE_PREVIOUS_RESPONSE_SUCCESS_MESSAGE);
    } catch (error) {
      const failure = toRestorePreviousResponseFailure(error);
      if (failure.message) toast.error(failure.message);
      if (failure.refetchRoom) void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
    } finally {
      isRestoringRef.current = false;
    }
  }

  /** 재생성이 끝난 직후 되돌릴 길을 알린다. 무료분 턴에도 같은 문구다. */
  function offerRestore(regeneratedMessageId: string) {
    toast("새 답변으로 바꿨어요", {
      id: REGENERATED_TOAST_ID,
      description: "되돌려도 다시 생성한 클로버는 돌아오지 않아요",
      duration: UNDO_TOAST_DURATION_MS,
      action: <UndoToastButton onClick={() => void restore(regeneratedMessageId)} />,
    });
  }

  /** 재생성 직후 띄운 되돌리기 안내를 거둔다. 턴이 시작되면 부른다 — 보내기·수정은 서버가 보관한 직전 응답을 지우고 다시
   * 생성은 그 보관본을 새 직전 응답으로 바꾸므로, 남은 [되돌리기]는 누르면 거절될 버튼이다. */
  function dismissRestoreOffer() {
    toast.dismiss(REGENERATED_TOAST_ID);
  }

  return { restore, offerRestore, dismissRestoreOffer };
}
