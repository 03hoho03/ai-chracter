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

type DraftChangedDialogProps = {
  chainName: string;
};

/** 초안 저장이 "편집을 연 뒤 다른 곳(다른 탭·다른 관리자)에서 초안이 저장됨"으로 멈췄을 때 덮어쓸지 묻는다. 취소하면 아무것도
 * 저장되지 않고 편집은 폼에 그대로 남는다. 참이면 덮어쓰기다. */
export const DraftChangedDialog = createCallable<DraftChangedDialogProps, boolean>(({ call, chainName }) => (
  <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(false)}>
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>다른 곳에서 먼저 저장했어요</DialogTitle>
        <DialogDescription className="break-keep">
          이 편집을 연 뒤 <span className="font-medium text-foreground">{chainName}</span> 초안이 다른 곳에서
          저장됐어요. 덮어쓰면 그 저장은 사라지고 지금 편집으로 바뀌어요. 취소하면 편집은 그대로 남아요.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button type="button" variant="outline" autoFocus onClick={() => call.end(false)}>
          취소
        </Button>
        <Button type="button" onClick={() => call.end(true)}>
          덮어쓰기
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
));
