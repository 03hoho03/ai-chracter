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

type DiscardEditsDialogProps = {
  dirtyCount: number;
};

/** 다른 저장이 먼저 반영돼 최신 표를 불러올 때, 저장하지 않은 편집을 저절로 버리지 않고 한 번 묻는다 — 운영자가 이력 표에서
 * 무엇이 바뀌었는지 먼저 볼 수 있게. */
export const DiscardEditsDialog = createCallable<DiscardEditsDialogProps, boolean>(({ call, dirtyCount }) => (
  <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
    <DialogContent className="sm:max-w-sm">
      <DialogHeader>
        <DialogTitle>최신 표를 불러올까요?</DialogTitle>
        <DialogDescription>저장하지 않은 편집 {dirtyCount}칸이 사라지고 최신 표로 바뀌어요.</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button type="button" variant="outline" autoFocus onClick={() => call.end(false)}>
          취소
        </Button>
        <Button type="button" onClick={() => call.end(true)}>
          불러오기
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
));
