import { ConfirmChatRoomActionModal } from "@/features/manage-chat-room";

/**
 * 고친 메시지 뒤 대화가 여럿 지워질 때 저장 전에 묻는다. 확인하면 `save`를 부른다 — 취소하면 아무것도 하지 않아
 * 수정 폼과 고쳐 쓴 글이 그대로 남는다. 서버는 뒤 대화를 먼저 지우고 새 답을 만들므로 생성이 실패해도 지운 대화는
 * 돌아오지 않는다 — 그 점까지 말한다. 저장 요청 자체가 거절되면(재화 부족·앞 턴 진행 중) 아무것도 지워지지 않으므로
 * 문구는 생성 실패로 범위를 좁힌다. `statNote` 가 있으면(보이는 스탯이 있는 방) 지운 턴의 스탯이 어떻게 되는지 한 줄로
 * 덧붙인다(`editConfirmStatNote`).
 */
export async function confirmEditTruncation(removedCount: number, save: () => void, statNote: string | undefined) {
  await ConfirmChatRoomActionModal.call({
    title: "뒤 대화를 지울까요?",
    description: `이 메시지 뒤 ${removedCount}개가 지워지고 새 답을 받아요. 새 답을 만들다 실패해도 지운 대화는 돌아오지 않아요.`,
    confirmLabel: "지우고 저장",
    note: statNote,
    // 저장은 스트림을 열고 바로 돌아온다 — 답은 채팅 화면이 받으므로 모달은 기다리지 않고 닫는다.
    mutationFn: (call) => {
      save();
      call.end();
      return Promise.resolve();
    },
  });
}
