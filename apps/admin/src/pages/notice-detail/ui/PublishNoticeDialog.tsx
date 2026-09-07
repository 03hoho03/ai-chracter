import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

type PublishNoticeDialogProps = {
  title: string;
  action: "publish" | "unpublish";
  mutationFn: MutationFn<void>;
};

/** `PublishDialog`(`pages/legal/ui/`) 선례 — 다만 공지는 버전·재동의 입력이 없는 단순 확인이라
 * 폼 대신 `DeleteConfirmModal`(`features/act-on-report`)의 `useMutationFlow` 구조를 따른다.
 * 게시는 전체 유저에게 알림을 보내는 되돌리기 어려운 동작이라 확인 문구에 그 사실을 적는다
 * (techspec.md §6-2). */
export const PublishNoticeDialog = createCallable<PublishNoticeDialogProps, void>(
  ({ call, title, action, mutationFn }) => {
    const submit = useMutationFlow(call, mutationFn);
    const isPublish = action === "publish";
    const actionLabel = isPublish ? "게시" : "숨김";

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>공지 {actionLabel}</DialogTitle>
            <DialogDescription className="break-keep">
              {isPublish
                ? `'${title}' 공지를 게시하면 전체 유저에게 알림이 갑니다. 되돌려도 알림은 회수되지 않아요.`
                : `'${title}' 공지를 숨기면 유저 화면에서 보이지 않게 돼요. 언제든 다시 게시할 수 있어요.`}
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" disabled={submit.pending} onClick={() => submit()}>
              {submit.pending ? "처리 중..." : actionLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
