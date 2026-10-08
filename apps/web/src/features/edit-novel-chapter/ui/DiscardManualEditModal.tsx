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

type DiscardManualEditModalProps = {
  /** 옮겨 갈 화 번호. 화가 아닌 곳(인물·설정 노트·버전·목록)으로 옮길 때는 없다. */
  chapterOrdinal?: number;
};

/** 직접 고치던 글을 두고 다른 곳으로 옮기기 전 확인. 옮기면 고치던 자리가 새로 그려져 쓴 글이 남지 않는다.
 * 돌려주는 값은 버리고 옮길 것인가다. 쓴 글을 지키는 쪽인 `취소` 가 먼저다. */
export const DiscardManualEditModal = createCallable<DiscardManualEditModalProps, boolean>(({ call, chapterOrdinal }) => (
  <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
    <DialogContent className="sm:max-w-sm">
      <DialogHeader>
        <DialogTitle>
          {chapterOrdinal === undefined ? "고치던 글을 버리고 옮길까요?" : `고치던 글을 버리고 ${chapterOrdinal}화로 갈까요?`}
        </DialogTitle>
        <DialogDescription className="break-keep">
          저장하지 않은 글은 남지 않아요. 남기려면 취소하고 먼저 저장해 주세요.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => call.end(false)}>
          취소
        </Button>
        <Button type="button" variant="destructive" onClick={() => call.end(true)}>
          버리고 이동
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
));
