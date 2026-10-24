import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { History } from "lucide-react";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";

import { createCallable } from "@/shared/lib/callable/createCallable";

type ConfirmChatRoomActionModalProps = {
  title: string;
  description: string;
  confirmLabel: string;
  /** 설명 아래 한 줄로 덧붙이는, 확정하면 함께 바뀌는 것(예: 수정이 지우는 대화의 스탯). 없으면 줄도 없다. */
  note?: string;
  mutationFn: MutationFn<void>;
};

/** "대화방 초기화·삭제 확인" react-call
 * 사례 — 둘 다 입력 없이 확인/취소만 있는 동일 구조라 하나의 컴포넌트로 공유한다. ReportContentModal과
 * 동일하게 실제 API 호출/토스트는 호출부의 mutationFn이 담당하고, 이 컴포넌트는 확인 UI + 제출 상태
 * 표시만 책임진다. */
export const ConfirmChatRoomActionModal = createCallable<ConfirmChatRoomActionModalProps, void>(
  ({ call, title, description, confirmLabel, note, mutationFn }) => {
    const submit = useMutationFlow(call, mutationFn);

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {/* 덧붙이는 줄도 설명 안에 둔다 — 대화 상자의 설명(aria-describedby)으로 함께 읽힌다. */}
            {note ? (
              <DialogDescription asChild>
                <div className="flex flex-col gap-2">
                  <p>{description}</p>
                  <p className="flex gap-2 text-foreground">
                    <History aria-hidden className="mt-1 size-3.5 shrink-0 text-muted-foreground" />
                    {note}
                  </p>
                </div>
              </DialogDescription>
            ) : (
              <DialogDescription>{description}</DialogDescription>
            )}
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" variant="destructive" disabled={submit.pending} onClick={() => submit()}>
              {submit.pending ? "처리 중..." : confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
