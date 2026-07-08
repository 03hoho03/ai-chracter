import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { createCallable } from "react-call";

// US-081 — "다른 시작설정 선택" 확인 전용. ConfirmChatRoomActionModal(Promise<void>, mutationFn을
// 그 컴포넌트가 직접 실행)과 달리, 확정 후 실제 동작(뮤테이션 호출 + 새 roomId로 navigate)을 호출부가
// 이어받아야 해서 Promise<boolean>만 반환한다.
export const ConfirmStartingSetupChangeModal = createCallable<void, boolean>(({ call }) => {
  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>시작설정을 변경할까요?</DialogTitle>
          <DialogDescription>변경 시 새로운 채팅방으로 이동됩니다.</DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button type="button" onClick={() => call.end(true)}>
            변경하기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
