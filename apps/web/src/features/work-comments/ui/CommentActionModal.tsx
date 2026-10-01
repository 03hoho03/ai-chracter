import { Button } from "@ai-character-chat/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

type CommentActionModalProps = {
  title: string; description: string; confirmLabel: string; isDestructive?: boolean;
  mutationFn: MutationFn<void>; returnFocus: () => void;
};

export const CommentActionModal = createCallable<CommentActionModalProps, void>(
  ({ call, title, description, confirmLabel, isDestructive, mutationFn, returnFocus }) => {
    const submit = useMutationFlow(call, mutationFn);
    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="max-h-dialog overflow-y-auto sm:max-w-sm"
          onCloseAutoFocus={(event) => { event.preventDefault(); requestAnimationFrame(returnFocus); }}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="break-keep">{description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>취소</Button>
            <Button type="button" variant={isDestructive ? "destructive" : "default"}
              aria-disabled={submit.pending} className="aria-disabled:opacity-65"
              onClick={() => { if (!submit.pending) submit(); }}>
              {submit.pending ? "처리 중…" : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
