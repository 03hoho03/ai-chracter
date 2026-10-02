import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { createCallable } from "@/shared/lib/callable/createCallable";

type MediaBookConfirmModalProps = {
  title: string;
  description: string;
  confirmLabel: string;
  /**
   * 모달이 완전히 닫힌 뒤 포커스를 둘 곳으로 옮긴다(확인·취소 모두). 지우면 모달을 연 버튼도 함께 사라지는 경우가
   * 많아, 모달의 기본 복원(연 버튼으로)에 맡기면 포커스가 body 로 떨어진다. 결과를 받은 직후에 옮기면 아직 닫히는 중인
   * 모달이 포커스를 도로 가둔다 — 그래서 닫힘 뒤 자리(`onCloseAutoFocus`)에서 부른다.
   */
  onRestoreFocus: () => void;
};

/**
 * 스토리 빌더에서 되돌릴 수 없는 삭제(이미지가 딸린 미디어 북 축 항목, 칸 비우기, 엔딩 조건이 딸린 스탯, 스탯·엔딩을 품은
 * 시작설정)를 확인한다. 삭제 동작은 호출부가 이어받는다.
 */
export const MediaBookConfirmModal = createCallable<MediaBookConfirmModalProps, boolean>(
  ({ call, title, description, confirmLabel, onRestoreFocus }) => (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent
        className="sm:max-w-sm"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          requestAnimationFrame(onRestoreFocus);
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="break-keep">{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button type="button" variant="destructive" onClick={() => call.end(true)}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ),
);
