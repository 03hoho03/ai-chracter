import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";

/** 노트 비우기 확인. 확인 모달은 다른 feature라 편집기(feature)가 직접 부르지 못해 위젯이 넘긴다. */
export async function confirmClearMemoryNote(clear: () => Promise<void>) {
  await ConfirmChatRoomActionModal.call({
    title: "'꼭 기억할 것'을 비울까요?",
    description: "적어 둔 내용이 지워지고 다음 대화부터 반영돼요. 이 작업은 되돌릴 수 없어요.",
    confirmLabel: "비우기",
    mutationFn: async (call) => {
      await clear();
      call.end();
    },
  });
}
