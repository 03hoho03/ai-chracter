import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo } from "react";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";
import { useForm } from "react-hook-form";

import { createDeleteConfirmSchema, type DeleteConfirmFormValues } from "../model/schema";

type DeleteConfirmModalProps = {
  contentName: string;
  mutationFn: MutationFn<void>;
};

/** techspec-admin.md §1/§4 — 삭제는 되돌릴 수 없으므로, 콘텐츠명을 정확히 입력해야만 확정 버튼이 활성화된다.
 * 관리자 코멘트는 호출부가 이미 받아 mutationFn 클로저에 담아 넘기므로 이 모달은 입력을 다시 받지 않는다.
 *
 * "일치해야 활성화"는 `apps/admin/CLAUDE.md`가 정한 규약이라 버튼 게이트를 그대로 두되, 그 판정을
 * 컴포넌트에서 다시 계산하지 않고 `mode: "onChange"` + `formState.isValid`로 **스키마에서 도출한다** —
 * 일치 술어가 두 곳에 있으면 갈린다. 게이트를 뚫는 유일한 경로인 입력창 Enter는 `handleSubmit`이 막는다. */
export const DeleteConfirmModal = createCallable<DeleteConfirmModalProps, void>(({ call, contentName, mutationFn }) => {
  const schema = useMemo(() => createDeleteConfirmSchema(contentName), [contentName]);
  const {
    register,
    handleSubmit,
    formState: { isValid },
  } = useForm<DeleteConfirmFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { confirmText: "" },
    mode: "onChange",
  });

  const submit = useMutationFlow(call, mutationFn);

  const isConfirmBlocked = !isValid || submit.pending;

  function handleValidSubmit() {
    if (isConfirmBlocked) return;
    submit();
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>콘텐츠 삭제</DialogTitle>
          <DialogDescription>
            이 작업은 되돌릴 수 없습니다. 삭제를 확정하려면 콘텐츠명{" "}
            <span className="font-medium text-foreground">{contentName}</span>을(를) 아래에 정확히 입력하세요.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(handleValidSubmit)(event);
          }}
        >
          <Input placeholder={contentName} autoFocus aria-label="콘텐츠명 확인" {...register("confirmText")} />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button
              type="submit"
              variant="destructive"
              aria-disabled={isConfirmBlocked}
              className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            >
              {submit.pending ? "삭제 중..." : "삭제 확정"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
